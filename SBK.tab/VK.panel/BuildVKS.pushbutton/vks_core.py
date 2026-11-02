# -*- coding: utf-8 -*-
"""Менеджер спецификаций — логика без окон.

Шаги (всё одной группой транзакций, Ctrl+Z — одним шагом):
 1. Системы модели; «ИмяСистемы» = встроенное «Имя системы» Revit (вложенные — от родителя), по нему спецификации
    сортируются всегда, скрыто.
 2. Изоляция: наименование с наружным диаметром трубы, длина изоляции фитингов/арматуры.
 3. ADSK_Количество: штучным не дописывается (только предупреждение; отдельная кнопка «Заполнить количество»
    в окне), трубам без количества — длина.
 4. Группы систем → ADSK_Система_Обозначение (фильтр спецификаций).
 5. Порядок: материал и тип (шаг 3, можно выключить — тогда «по имени»), диаметр; ранг — в параметр сортировки.
 6. Спецификации из шаблонов «О_…» по группам и категориям в порядке ГОСТ 21.601 п. 9.4.
 7. Дополнительные материалы (покраска, крепёж): одна таблица на связку групп — спецификация пустой категории
    «Комплекты мебели», строки текстом в разделе «Заголовок».
 8. Позиции ADSK_Позиция; 9. листы комплекта: Форма 5 / Форма 6, связки, перенос, нумерация, штамп.
"""
from __future__ import print_function
import os
import re
import io
import imp
import json
import math
import time
import traceback

from System.Collections.Generic import List
from Autodesk.Revit import DB

HERE = os.path.dirname(os.path.abspath(__file__))
D = imp.load_source("spec_manager_defaults", os.path.join(HERE, "vks_defaults.py"))
L = imp.load_source("spec_manager_layout", os.path.join(HERE, "vks_layout.py"))
L.RESIZE_ROWS_ALL = getattr(D, "RESIZE_ROWS_ALL", L.RESIZE_ROWS_ALL)
L.SEGMENT_FRAME_MM = getattr(D, "SEGMENT_FRAME_MM", L.SEGMENT_FRAME_MM)

FT = 304.8
P_SYS = u"ИмяСистемы"
P_GROUP = u"ADSK_Система_Обозначение"
P_MAIN = u"ADSK_Система_Имя"          # прежняя версия: основная система; больше не пишется и не сортируется
P_KIT = u"ADSK_Позиция_Комплект"
P_SORT = u"ADSK_Позиция_Сортировка"
P_POS = u"ADSK_Позиция"
P_QTY = u"ADSK_Количество"
P_NAME = u"ADSK_Наименование"
P_UNIT = u"ADSK_Единица измерения"
P_GRP = u"ADSK_Группирование"
P_PURPOSE = u"ADSK_Назначение вида"
P_SECTION = getattr(D, "P_SECTION", u"ADSK_Номер секции")      # блок / секция (ФОП2021: текст, экземпляр)
SKIP = u"!Не учитывать"
SHARED = {P_MAIN: "24c33696-0fa2-4a85-affd-e47d1cf20fb3", P_GROUP: "dc4f8698-20e2-4304-b11e-febeb19c2ecc"}
PIECE_UNITS = (u"", u"шт", u"шт.", u"компл", u"компл.", u"к-т", u"к-т.", u"комплект", u"пара")

doc = None
EXT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

# этапы для окна хода работы: run(..., progress=fn) / prepare(..., progress=fn) -> fn(этап, i, n)
STAGES = [u"Параметры и ИмяСистемы", u"Изоляция и количество", u"Группы, порядок, малые строки",
          u"Спецификации и материалы", u"Позиции", u"Листы"]
READ_STAGES = [u"Категории и системы", u"Элементы модели", u"Количество и настройки", u"Поля спецификаций"]
_PROG = None
_NOTE = None         # итог этапа в окне хода работы: fn(этап, текст)
_TIMES = []          # [(этап, секунды)] — замеры текущего чтения / сборки
_T0 = [None, None]   # (номер этапа, время начала)


def _p(stage, i=None, n=None):
    if _T0[0] != stage:                      # смена этапа — замер прошлого
        now = time.time()
        if _T0[0] is not None:
            _TIMES.append((_T0[0], now - _T0[1]))
        _T0[0], _T0[1] = stage, now
    if _PROG is not None:
        try:
            _PROG(stage, i, n)
        except Exception:
            pass


_NOTE_PREFIX = [u""]   # сборка по блокам: «1.6: » перед итогом этапа


def _n(stage, text):
    if _NOTE is not None:
        try:
            _NOTE(stage, _NOTE_PREFIX[0] + text)
        except Exception:
            pass


def plural(n, one, few, many):
    """1 спецификация, 2 спецификации, 5 спецификаций."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        w = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        w = few
    else:
        w = many
    return u"{0} {1}".format(n, w)


def _timing_start(progress, note=None):
    global _PROG, _NOTE
    _PROG = progress
    _NOTE = note
    del _TIMES[:]
    _T0[0], _T0[1] = None, None


def _timing_stop(n):
    """-> [секунды по этапам 0..n-1] (этап без замера — 0)."""
    if _T0[0] is not None:
        _TIMES.append((_T0[0], time.time() - _T0[1]))
        _T0[0] = None
    out = [0.0] * n
    for st, sec in _TIMES:
        if 0 <= st < n:
            out[st] += sec
    return [round(x, 2) for x in out]


def fmt_sec(sec):
    sec = int(round(max(0.0, sec)))
    return u"{0}:{1:02d}".format(sec // 60, sec % 60) if sec >= 60 else u"{0} с".format(sec)


class Laps(object):
    """Замер подэтапов внутри этапа: lap(имя) — секунды с прошлой отметки. В журнал — через stats
    («время, с: имя», как в сборке по разделам) или одной строкой отчёта по порядку (text())."""

    def __init__(self, stats=None):
        self.stats = stats
        self.items = []
        self.t = time.time()

    def lap(self, name):
        now = time.time()
        sec = round(now - self.t, 1)
        self.t = now
        self.items.append((name, sec))
        if self.stats is not None:
            self.stats[u"время, с: " + name] = sec

    def text(self):
        return u"; ".join(u"{0} {1:g}".format(n, s) for n, s in self.items)


def set_doc(d):
    global doc
    doc = d
    L.doc = d
    L.EXTRA_TITLE_MM.clear()
    TS_WARNED.clear()


# ------------------------------------------------------------------
# мелочи
# ------------------------------------------------------------------
def id_int(eid):
    return int(eid.Value)          # Revit 2025: ElementId.Value (Int64)


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def nat_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(u"(\\d+)", s or u"")]


def bic(name):
    return getattr(DB.BuiltInCategory, name, None)


ACTIVE_KEYS = None      # категории, найденные в проекте (None — ещё не искали: все)
FOUND_KINDS = []        # "pipe" / "duct"
SYS_KIND = {}           # имя системы -> "pipe" | "duct"


def detect_categories():
    """Какие категории искать: трубы есть — трубопроводные, воздуховоды есть — вентиляционные (+ общие).
    По одному короткому запросу на признак раздела. Ничего не найдено — как раньше, трубопроводные."""
    global ACTIVE_KEYS, FOUND_KINDS
    kinds = []
    for kind, names in D.KIND_MARKERS.items():
        for bname in names:
            b = bic(bname)
            if b is None:
                continue
            eid = safe(lambda: DB.FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType()
                       .FirstElementId())
            if eid is not None and eid != DB.ElementId.InvalidElementId:
                kinds.append(kind)
                break
    if not kinds:
        kinds = ["pipe"]
    kinds.sort()
    FOUND_KINDS = kinds
    ACTIVE_KEYS = set(k for k, b, t, o in D.CATS if D.CAT_KIND.get(k, "pipe") in ["common"] + kinds)
    return ACTIVE_KEYS


def active_cats():
    if ACTIVE_KEYS is None:
        detect_categories()
    return [c for c in D.CATS if c[0] in ACTIVE_KEYS]


def cat_def(key):
    for c in D.CATS:
        if c[0] == key:
            return c
    return None


def pval(el, name):
    """Значение параметра экземпляра: строка / число / None."""
    if el is None:
        return None
    p = safe(lambda: el.LookupParameter(name))
    if p is None:
        return None
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString()
    if st == DB.StorageType.Double:
        return p.AsDouble() if p.HasValue else None
    if st == DB.StorageType.Integer:
        return p.AsInteger() if p.HasValue else None
    return safe(lambda: p.AsValueString())


def tval(el, name):
    """Экземпляр, иначе тип."""
    v = pval(el, name)
    if v not in (None, u""):
        return v
    t = safe(lambda: doc.GetElement(el.GetTypeId()))
    return pval(t, name) if t is not None else v


def set_val(el, name, value):
    """-> 'ok' | 'same' | 'none' | 'ro' | 'err'."""
    p = safe(lambda: el.LookupParameter(name))
    if p is None:
        return "none"
    if p.IsReadOnly:
        return "ro"
    try:
        if p.StorageType == DB.StorageType.String:
            cur = p.AsString() or u""
            if cur == (value or u""):
                return "same"
            p.Set(value or u"")
        elif p.StorageType == DB.StorageType.Double:
            if p.HasValue and abs(p.AsDouble() - float(value)) < 1e-9:
                return "same"
            p.Set(float(value))
        elif p.StorageType == DB.StorageType.Integer:
            if p.HasValue and p.AsInteger() == int(value):
                return "same"
            p.Set(int(value))
        else:
            return "err"
        return "ok"
    except Exception:
        return "err"


# ------------------------------------------------------------------
# любые параметры категории (поля, которые Revit даёт в спецификацию)
# ------------------------------------------------------------------
SFIELDS = {}     # key категории -> [{"name", "pid", "ftype"}]
AMAP = {}
_DEFS = {}


def _param_of(el, pid):
    if el is None or pid is None:
        return None
    if pid < 0:
        import System
        bip = safe(lambda: System.Enum.ToObject(DB.BuiltInParameter, int(pid)))
        return safe(lambda: el.get_Parameter(bip)) if bip is not None else None
    if pid not in _DEFS:
        import System
        pe = safe(lambda: doc.GetElement(DB.ElementId(System.Int64(pid))))
        _DEFS[pid] = safe(lambda: pe.GetDefinition()) if pe is not None else None
    dfn = _DEFS.get(pid)
    return safe(lambda: el.get_Parameter(dfn)) if dfn is not None else None


def _pvalue(p):
    if p is None or not safe(lambda: p.HasValue, False):
        return None
    st = p.StorageType
    if st == DB.StorageType.String:
        return p.AsString()
    if st == DB.StorageType.Double:
        return p.AsDouble()
    if st == DB.StorageType.Integer:
        return p.AsInteger()
    if st == DB.StorageType.ElementId:
        t = safe(lambda: doc.GetElement(p.AsElementId()))
        if isinstance(t, DB.Level):
            return t.Elevation                      # уровни — по отметке, а не по имени
        return safe(lambda: p.AsValueString()) or safe(lambda: t.Name)
    return None


def field_value(el, f):
    """Значение для сортировки по строке настроек {"param", "pid"?}: экземпляр, иначе тип."""
    pid = f.get("pid") if isinstance(f, dict) else None
    name = f["param"] if isinstance(f, dict) else f
    if pid is None:
        return tval(el, name)
    v = _pvalue(_param_of(el, pid))
    if v not in (None, u""):
        return v
    t = safe(lambda: doc.GetElement(el.GetTypeId()))
    v2 = _pvalue(_param_of(t, pid)) if t is not None else None
    if v2 not in (None, u""):
        return v2
    return v if v is not None else tval(el, name)


def schedulable_fields():
    """Поля «экземпляр»/«тип», которые Revit предлагает в спецификацию каждой категории."""
    out = {}
    tpls = safe(find_templates, {}) or {}
    need_tmp = []
    for key, bname, title, order in active_cats():
        vs = tpls.get(key)
        sfs = safe(lambda: list(vs.Definition.GetSchedulableFields())) if vs is not None else None
        if sfs is None:
            need_tmp.append(key)
        else:
            out[key] = sfs
    if need_tmp and not doc.IsReadOnly:
        t = DB.Transaction(doc, u"Менеджер спецификаций: поля категорий")
        try:
            t.Start()
            for key in need_tmp:
                b = bic(cat_def(key)[1])
                vs = safe(lambda: DB.ViewSchedule.CreateSchedule(doc, DB.ElementId(b)))
                if vs is not None:
                    out[key] = safe(lambda: list(vs.Definition.GetSchedulableFields()), [])
        except Exception:
            pass
        finally:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
    res = {}
    kinds = {DB.ScheduleFieldType.Instance: "inst", DB.ScheduleFieldType.ElementType: "type"}
    for key, sfs in out.items():
        lst, seen = [], {}
        for sf in sfs or []:
            ft = kinds.get(sf.FieldType)
            if ft is None:
                continue
            nm = safe(lambda: sf.GetName(doc)) or u""
            if not nm:
                continue
            pid = id_int(sf.ParameterId)
            if nm in seen:
                if seen[nm] != pid:
                    lst.append({"name": nm + u" [тип]" if ft == "type" else nm + u" [экз.]", "param": nm, "pid": pid, "ftype": ft})
                continue
            seen[nm] = pid
            lst.append({"name": nm, "param": nm, "pid": pid, "ftype": ft})
        lst.sort(key=lambda x: (not x["name"].startswith(u"ADSK"), x["name"].lower()))
        res[key] = lst
    return res


def fam_type(el):
    t = safe(lambda: doc.GetElement(el.GetTypeId()))
    if t is None:
        return u"", u""
    fam = safe(lambda: t.FamilyName) or u""
    tn = L.tname(t)
    return fam, tn


class UserError(Exception):
    """Причина отмены сборки для пользователя (без трассировки)."""


TX_WARNINGS = {}     # предупреждения Revit за сборку: текст -> [сколько раз, id элементов] (в отчёт)


def _ids_text(ids):
    return u" (эл. id: {0}{1})".format(u", ".join(str(i) for i in ids[:5]), u" …" if len(ids) > 5 else u"") \
        if ids else u""


def _failure_parts(f):
    """Текст сбоя Revit и id элементов — чтобы найти их в модели."""
    t = (safe(lambda: f.GetDescriptionText()) or u"").strip() or u"без описания"
    ids = safe(lambda: [id_int(x) for x in f.GetFailingElementIds()], []) or []
    return t, ids


class _Failures(DB.IFailuresPreprocessor):
    """Сбои Revit при записи шага. Предупреждения — убрать и запомнить текст (идёт в отчёт). Ошибки — откат шага,
    текст — причина отмены сборки. Окно Revit не открывается: под окном хода работы его не видно, и сборка ждала
    его (421-1-ОВ, 02.11.2026: 37 мин на создании листа блока, затем откат — «спецификации не разложены»)."""
    __namespace__ = "SpecManager.Core.v0131"

    def __init__(self):
        self.warnings = []
        self.errors = []

    def PreprocessFailures(self, fa):
        err = False
        for f in fa.GetFailureMessages():
            text, ids = _failure_parts(f)
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                self.warnings.append((text, ids))
                fa.DeleteWarning(f)
            else:
                self.errors.append(text + _ids_text(ids))
                err = True
        if err:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


class Tx(object):
    """Транзакция шага. Итог Commit проверяется: Revit откатил шаг -> UserError с текстом сбоя (вся сборка
    отменяется, модель не меняется). Предупреждения — в TX_WARNINGS."""

    def __init__(self, name):
        self.name = name
        self.t = DB.Transaction(doc, name)
        self.fp = None

    def __enter__(self):
        self.fp = _Failures()
        o = self.t.GetFailureHandlingOptions()
        o.SetFailuresPreprocessor(self.fp)
        o.SetClearAfterRollback(True)          # после отката сбои не всплывают окном
        self.t.SetFailureHandlingOptions(o)
        self.t.Start()
        return self.t

    def __exit__(self, et, ev, tb):
        if et is not None:
            if self.t.HasStarted() and not self.t.HasEnded():
                self.t.RollBack()
            return False
        st = self.t.Commit()
        for text, ids in self.fp.warnings:
            w = TX_WARNINGS.setdefault(text, [0, []])
            w[0] += 1
            w[1].extend(ids[:5 - len(w[1])] if len(w[1]) < 5 else [])
        if st != DB.TransactionStatus.Committed:
            why = u"; ".join(self.fp.errors[:5]) or u"статус {0}".format(st)
            if len(self.fp.errors) > 5:
                why += u"; … ещё {0}".format(len(self.fp.errors) - 5)
            raise UserError(u"Revit не дал выполнить шаг «{0}»: {1}. Сборка отменена, модель не "
                            u"изменена.".format(self.name, why))
        return False


def warnings_report(report):
    """Предупреждения Revit за сборку — одной строкой в отчёт (они убраны, окно Revit не показывалось)."""
    if not TX_WARNINGS:
        return
    items = sorted(TX_WARNINGS.items(), key=lambda x: -x[1][0])
    txt = u"; ".join(u"«{0}»{1}{2}".format(t, u" ×{0}".format(v[0]) if v[0] > 1 else u"", _ids_text(v[1]))
                     for t, v in items[:8])
    if len(items) > 8:
        txt += u"; … ещё {0}".format(len(items) - 8)
    report.append(u"предупреждения Revit при сборке (убраны, сборку не останавливают): " + txt)


# ------------------------------------------------------------------
# настройки
# ------------------------------------------------------------------
def settings_path(d=None):
    d = d or doc
    title = re.sub(u"[\\\\/:*?\"<>|]+", u"_", (d.Title or u"проект"))
    folder = os.path.join(EXT_ROOT, u"_settings")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.join(folder, u"vks_{0}.json".format(title))


def load_cfg(path=None):
    path = path or settings_path()
    if os.path.isfile(path):
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except Exception:
            pass
    return {}


def save_cfg(cfg, path=None):
    path = path or settings_path()
    txt = json.dumps(cfg, ensure_ascii=False, indent=1)
    if not isinstance(txt, type(u"")):
        txt = txt.decode("utf-8")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    return path


# ------------------------------------------------------------------
# журнал запуска: %LOCALAPPDATA%\Spec_Manager\logs\run_ГГГГММДД_ЧЧММСС.txt
# Только файл, без окон. Любая ошибка записи глушится: журнал не должен ронять команду.
# ------------------------------------------------------------------
LOG_KEEP = 50            # сколько последних журналов хранить


class RunLog(object):
    def __init__(self, d=None):
        self.t0 = time.time()
        self.lines = []
        self.path = None
        try:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(u"~")
            folder = os.path.join(base, u"Spec_Manager", u"logs")
            if not os.path.isdir(folder):
                os.makedirs(folder)
            self.path = os.path.join(folder, u"run_{0}.txt".format(time.strftime("%Y%m%d_%H%M%S")))
            self._trim(folder)
        except Exception:
            self.path = None    # нет доступа к папке — журнал просто не пишется
        title = u""
        try:
            title = (d or doc).Title
        except Exception:
            pass
        self.add(u"Запуск. Проект: {0}".format(title))

    def _trim(self, folder):
        try:
            old = sorted(f for f in os.listdir(folder) if f.startswith("run_") and f.endswith(".txt"))
            for f in old[:max(0, len(old) - LOG_KEEP + 1)]:
                os.remove(os.path.join(folder, f))
        except Exception:
            pass                # чистка необязательна

    def add(self, text):
        try:
            if not isinstance(text, type(u"")):
                text = str(text).decode("utf-8", "replace") if hasattr(str, "decode") else str(text)
            self.lines.append(u"{0}  +{1:.1f} с  {2}".format(time.strftime("%H:%M:%S"),
                                                              time.time() - self.t0, text))
            self.save()
        except Exception:
            pass                # журнал не должен мешать работе

    def error(self, where):
        try:
            tb = traceback.format_exc()
            if not isinstance(tb, type(u"")):
                tb = tb.decode("utf-8", "replace")
            fixed = []
            for ln in tb.split(u"\n"):
                try:            # IronPython читает строки исходника как latin-1 — вернуть кириллицу
                    ln = ln.encode("latin-1").decode("utf-8")
                except Exception:
                    pass        # строка уже нормальная
                fixed.append(ln)
            self.add(u"ОШИБКА ({0}):\n{1}".format(where, u"\n".join(fixed)))
        except Exception:
            pass                # журнал не должен мешать работе

    def save(self):
        if not self.path:
            return
        try:
            with io.open(self.path, "w", encoding="utf-8") as f:
                f.write(u"\n".join(self.lines) + u"\n")
        except Exception:
            pass                # файл занят/нет места — пропускаем


# ------------------------------------------------------------------
# системы (логика Bim2B «ИмяСистемы»)
# ------------------------------------------------------------------
def own_sys(el):
    p = safe(lambda: el.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM))
    return (safe(lambda: p.AsString()) or u"").strip() if p is not None else u""


def top_parent(el):
    sup = safe(lambda: el.SuperComponent)
    last = None
    while sup is not None:
        last = sup
        sup = safe(lambda: sup.SuperComponent)
    return last


def bim2b_sys(el):
    v = own_sys(el)
    if v:
        return v
    sup = safe(lambda: el.SuperComponent)
    while sup is not None:
        v = own_sys(sup)
        if v:
            return v
        sup = safe(lambda: sup.SuperComponent)
    hid = safe(lambda: el.HostElementId)
    if hid is not None and hid != DB.ElementId.InvalidElementId:
        h = doc.GetElement(hid)
        if h is not None:
            return bim2b_sys(h)
    return u""


def split_sys(v):
    return [x.strip() for x in (v or u"").split(u",") if x.strip()]


def system_abbr_map():
    """Трубопроводные и вентиляционные системы -> (сокращение, классификация); SYS_KIND — раздел системы."""
    from Autodesk.Revit.DB.Plumbing import PipingSystem
    classes = [("pipe", PipingSystem)]
    try:
        from Autodesk.Revit.DB.Mechanical import MechanicalSystem
        classes.append(("duct", MechanicalSystem))
    except Exception:
        pass
    out = {}
    SYS_KIND.clear()
    SYS_COLORS.clear()
    for kind, cls in classes:
        for s in safe(lambda: list(DB.FilteredElementCollector(doc).OfClass(cls)), []) or []:
            t = doc.GetElement(s.GetTypeId())
            hx = type_color(t)
            if hx:
                SYS_COLORS[s.Name] = hx
            ab = safe(lambda: t.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM).AsString()) or u""
            cl = safe(lambda: s.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_CLASSIFICATION_PARAM).AsString()) or u""
            out[s.Name] = (ab.strip() or re.split(u"\\s", s.Name)[0], cl)
            SYS_KIND[s.Name] = kind
    return out


SYS_COLORS = {}         # система -> цвет линий её типа в модели «#RRGGBB» (таблетки на «Системах»)


def type_color(t):
    """Цвет линий типа системы (MEPSystemType.LineColor) -> «#RRGGBB» или None (не задан / чёрный по умолчанию)."""
    c = safe(lambda: t.LineColor) if t is not None else None
    if c is None or not safe(lambda: c.IsValid, False):
        return None
    r, g, b = int(c.Red), int(c.Green), int(c.Blue)
    if r == g == b == 0:
        return None
    return u"#%02X%02X%02X" % (r, g, b)


def abbr_of(sysname, amap):
    if sysname in amap:
        return amap[sysname][0]
    m = re.match(u"^\\s*([^\\s,;]+)", sysname or u"")
    return m.group(1) if m else sysname


def gost_desc(abbr, kind="pipe"):
    a = abbr or u""
    if kind == "duct":
        for k, v in D.GOST_DUCT_SYSTEMS:
            if a.startswith(k):
                return v
        return u"вентиляция"
    for k, v in D.GOST_SYSTEMS:
        if a == k:
            return v
    for k, v in D.GOST_SYSTEMS:
        if a.startswith(k):
            return v + (u", напорная" if a.endswith(u"Н") else u"")
    return u""


def abbr_key(a):
    m = re.match(u"^(\\D*)(\\d*)(.*)$", a or u"")
    letters, num, rest = m.group(1), m.group(2), m.group(3)
    li = D.LETTER_ORDER.find(letters[:1]) if letters else -1
    return (li if li >= 0 else len(D.LETTER_ORDER), letters, int(num) if num else 0, rest)


def sys_sort_key(name, amap):
    if name == D.NO_SYSTEM:
        return (9, (99,), [])
    return (1 if SYS_KIND.get(name) == "duct" else 0, abbr_key(abbr_of(name, amap)), nat_key(name))


# ------------------------------------------------------------------
# сбор элементов
# ------------------------------------------------------------------
class Info(object):
    def __init__(self, el, key):
        self.el = el
        self.id = id_int(el.Id)
        self.key = key
        self.fam, self.typ = fam_type(el)
        if key == "ins":
            self.fam = u"Изоляция трубы"
        elif key in ("dins", "dlin"):
            self.fam = u"Изоляция воздуховода" if key == "dins" else u"Внутренняя изоляция воздуховода"
        self.name = tval(el, P_NAME) or u""
        self.unit = (tval(el, P_UNIT) or u"").strip()
        self.sysraw = bim2b_sys(el)
        self.systems = split_sys(self.sysraw)
        self.units = self.systems           # единицы группировки: системы или значения ADSK_Группирование (set_units)
        self.grp = None                     # ADSK_Группирование (своё или родителя) — читается в set_units
        self.sec_own = u""                  # ADSK_Номер секции элемента
        self.sec = u""                      # секция для сборки: у вложенных — родителя, у изоляции труб — трубы
        self.sec_src = None                 # "parent" | "host" — откуда взята секция (её нужно записать элементу)
        self.host = None                    # изоляция: труба / воздуховод
        parent = top_parent(el)
        self.parent = parent
        self.parent_id = id_int(parent.Id) if parent is not None else None
        self.parent_key = None
        self.diam = 0.0
        self.part = u""
        self.group = None
        self.main = u""
        self.hidden = False
        self.kit = 0
        self.sortv = 0
        self.mat = 0
        self.tp = 0


def connectors(el):
    cm = safe(lambda: el.MEPModel.ConnectorManager)
    if cm is None:
        cm = safe(lambda: el.ConnectorManager)
    if cm is None:
        return []
    out = []
    for c in cm.Connectors:
        try:
            if c.Domain in (DB.Domain.DomainPiping, DB.Domain.DomainHvac):
                out.append(c)
        except Exception:
            pass
    return out


def conn_diam(el):
    best = 0.0
    for c in connectors(el):
        try:
            best = max(best, c.Radius * 2 * FT)
        except Exception:
            pass
    return best


def part_type(el):
    try:
        fam = doc.GetElement(el.GetTypeId()).Family
        p = fam.get_Parameter(DB.BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        return p.AsValueString() or u""
    except Exception:
        return u""


DIAM_RE = [re.compile(u"(?:ø|Ø|Ду|DN|Dn|D)\\s*=?\\s*(\\d+(?:[.,]\\d+)?)"), re.compile(u"(\\d+(?:[.,]\\d+)?)\\s*мм")]


def name_diam(text):
    for rx in DIAM_RE:
        m = rx.search(text or u"")
        if m:
            try:
                return float(m.group(1).replace(u",", u"."))
            except Exception:
                pass
    return 0.0


def collect(progress=None):
    """Элементы категорий спецификаций. progress(i, n) — каждые 200 элементов."""
    infos = []
    cats = []
    total = 0
    for key, bname, title, order in active_cats():
        b = bic(bname)
        if b is None:
            continue
        n = safe(lambda: DB.FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType()
                 .GetElementCount(), 0) or 0
        cats.append((key, b))
        total += n
    done = 0
    for key, b in cats:
        for el in DB.FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType():
            done += 1
            if progress is not None and done % 200 == 0:
                progress(done, total)
            infos.append(make_info(el, key))
    link_infos(infos)
    return infos


def make_info(el, key):
    """Info одного элемента: диаметр, секция (своя; изоляции — основы), основа изоляции."""
    it = Info(el, key)
    it.sec_own = sec_text(el)
    if key == "pipe":
        it.diam = safe(lambda: el.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).AsDouble() * FT, 0.0)
    elif key == "ins":
        h = safe(lambda: doc.GetElement(el.HostElementId))
        it.host = h
        if h is not None:
            hs = sec_text(h)
            if hs:                          # изоляция труб — секция трубы (решение 02.11.2026)
                it.sec, it.sec_src = hs, "host"
            if h.Category is not None and id_int(h.Category.Id) == int(DB.BuiltInCategory.OST_PipeCurves):
                it.diam = safe(lambda: h.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).AsDouble() * FT, 0.0)
            else:
                it.diam = conn_diam(h)
    else:
        if key in ("dins", "dlin"):        # изоляция воздуховодов — секция воздуховода
            h = safe(lambda: doc.GetElement(el.HostElementId))
            it.host = h
            hs = sec_text(h) if h is not None else u""
            if hs:
                it.sec, it.sec_src = hs, "host"
        it.diam = conn_diam(el)
        if key == "fit":
            it.part = part_type(el)
    if not it.diam:
        it.diam = name_diam(it.name)
    return it


def link_infos(infos, only=None):
    """Связи с родителем: категория родителя, диаметр, секция вложенного — родителя. only — множество id, которые
    нужно связать (перечитанные); None — все."""
    byid = dict((i.id, i) for i in infos)
    psec = {}
    for it in infos:
        if only is not None and it.id not in only:
            continue
        if it.parent_id is not None:
            p = byid.get(it.parent_id)
            it.parent_key = p.key if p is not None else None
            if not it.diam and p is not None:
                it.diam = p.diam
            if it.parent_id not in psec:
                psec[it.parent_id] = p.sec_own if p is not None else sec_text(it.parent)
            if psec[it.parent_id]:              # вложенное общее семейство — секция родителя
                it.sec, it.sec_src = psec[it.parent_id], "parent"
        if not it.sec:
            it.sec, it.sec_src = it.sec_own, None


def element_by_id(i):
    """Элемент по числовому id (Revit 2025: ElementId(Int64))."""
    try:
        from System import Int64
        return doc.GetElement(DB.ElementId(Int64(i)))
    except Exception:
        return safe(lambda: doc.GetElement(DB.ElementId(int(i))))


def refresh_infos(infos, ids):
    """Перечитать только элементы ids (панель «Исправить в Revit»): Info на месте прежних, удалённые из модели —
    убрать. ADSK_Количество и ADSK_Группирование читаются заново. -> (перечитано, удалено)."""
    ids = set(ids)
    _TQ.clear()
    upd, gone = set(), 0
    for k in range(len(infos) - 1, -1, -1):
        it = infos[k]
        if it.id not in ids:
            continue
        el = element_by_id(it.id)
        if el is None or not safe(lambda: el.IsValidObject, False):
            del infos[k]
            gone += 1
            continue
        new = make_info(el, it.key)
        st, where = qty_state(el) if new.key in ZERO_KEYS else ("ok", None)
        new.zq, new.zq_where = (None, None) if st == "ok" else (st, where)
        infos[k] = new
        upd.add(new.id)
    link_infos(infos, upd)
    return len(upd), gone


PROBLEMS = [
    ("qty", u"ADSK_Количество пусто / 0"),
    ("sortro", u"Параметр сортировки только для чтения (формула в семействе)"),
    ("grp", u"ADSK_Группирование не определено"),
    ("nogroup", u"Элементы вне групп"),
    ("name", u"ADSK_Наименование пусто"),
]
NAME_FREE = ("gen", "ins", "dins", "dlin")       # наименование не нужно: обобщённые; у изоляции его пишет сборка


def _hidden_catfam(it, hidden):
    """Скрыта категорией или семейством на шаге 2 (скрытые «по наименованию» — не в счёт)."""
    if it.key in (hidden.get("cats") or []):
        return True
    for k, f in hidden.get("fams") or []:
        if k == it.key and f == it.fam:
            return True
    return False


def problems(infos, cfg):
    """Проблемные элементы для панели «Исправить в Revit» -> {вид: [Info]} (виды — PROBLEMS). Только в памяти;
    единицы групп (it.units) — как после последнего set_units / regroup."""
    hidden = cfg.get("hidden") or {}
    gsys = set()
    for g in cfg.get("groups") or []:
        gsys.update(g.get("systems") or [])
    skip = set(cfg.get("skip_units") or [])
    out = dict((k, []) for k, t in PROBLEMS)
    sp = sort_param(cfg)
    for it in infos:
        if it.key == "gen":
            continue
        hid = is_hidden(it, hidden)
        if sp and not hid:
            p = safe(lambda: it.el.LookupParameter(sp))
            if p is not None and p.IsReadOnly:
                out["sortro"].append(it)
        if getattr(it, "zq", None) and not hid:
            out["qty"].append(it)
        units = units_of(it)
        if GROUP_BY[0] == "grouping" and not units:
            out["grp"].append(it)
        elif units and not hid and not (set(units) & gsys) and not set(units) <= skip:
            out["nogroup"].append(it)
        if it.key not in NAME_FREE and not (it.name or u"").strip() and not _hidden_catfam(it, hidden):
            out["name"].append(it)
    return out


def sec_text(el):
    """ADSK_Номер секции элемента — текст без пробелов по краям (число — как есть, без «.0»)."""
    v = pval(el, P_SECTION)
    if v is None:
        return u""
    if isinstance(v, float):
        v = u"%g" % v
    return (u"%s" % v).strip()


def sections_found(infos):
    """-> ([(секция, число элементов)] по порядку, число элементов без секции). Обобщённые модели не считаются."""
    cnt, nosec = {}, 0
    for it in infos:
        if it.key == "gen":
            continue
        if it.sec:
            cnt[it.sec] = cnt.get(it.sec, 0) + 1
        else:
            nosec += 1
    return sorted(cnt.items(), key=lambda x: nat_key(x[0])), nosec


HOST_INS = ("OST_PipeInsulations", "OST_DuctInsulations", "OST_DuctLinings")
INHERIT = ((P_SECTION, u"номер секции"), (P_GRP, u"группирование"))    # что вложенные и изоляция берут у родителя


def inherit_text(el, name):
    """Значение параметра (экземпляр, иначе тип) текстом без пробелов по краям; число — без «.0»."""
    v = tval(el, name) if el is not None else None
    if v is None:
        return u""
    if isinstance(v, float):
        v = u"%g" % v
    return (u"%s" % v).strip()


def section_plan():
    """Что писать по всей модели (ADSK_Номер секции и ADSK_Группирование): вложенным общим семействам (любой
    вложенности) — значение верхнего родителя, изоляции труб и воздуховодов — основы. Пишется, если у родителя /
    основы значение есть, а своё пустое или другое. -> ([(элемент, параметр, значение, "parent"|"host", категория)],
    {(параметр, категория): не записать — только чтение / нет параметра}). Только чтение модели."""
    out, skip = [], {}
    sec_bound = bound_categories(P_SECTION)[0] is not None
    prms = [(n, t) for n, t in INHERIT if n != P_SECTION or sec_bound]
    cache = {}

    def src_vals(src):
        k = id_int(src.Id)
        if k not in cache:
            cache[k] = dict((n, inherit_text(src, n)) for n, t in prms)
        return cache[k]

    def check(el, src, how):
        vals = src_vals(src)
        model = safe(lambda: el.Category.CategoryType) == DB.CategoryType.Model
        cat = safe(lambda: el.Category.Name) or u"?"
        for n, t in prms:
            want = vals.get(n)
            if not want:
                continue
            p = safe(lambda: el.LookupParameter(n))
            if p is None:
                if model and n == P_SECTION:     # без ADSK_Группирование группа и так берётся у родителя
                    skip[(n, cat)] = skip.get((n, cat), 0) + 1
                continue
            if (safe(lambda: p.AsString()) or u"").strip() == want:
                continue                          # уже как у родителя (в том числе только для чтения)
            if p.IsReadOnly or p.StorageType != DB.StorageType.String:
                skip[(n, cat)] = skip.get((n, cat), 0) + 1
                continue
            out.append((el, n, want, how, cat))
    for el in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        if safe(lambda: el.SuperComponent) is None:
            continue
        t = top_parent(el)
        if t is not None:
            check(el, t, "parent")
    for bname in HOST_INS:
        b = bic(bname)
        if b is None:
            continue
        for el in DB.FilteredElementCollector(doc).OfCategory(b).WhereElementIsNotElementType():
            h = safe(lambda: doc.GetElement(el.HostElementId))
            if h is not None:
                check(el, h, "host")
    return out, skip


def section_write(plan):
    """Записать план section_plan (внутри транзакции вызывающего). -> ({(параметр, "parent"|"host"): n},
    не записалось)."""
    c, bad = {}, 0
    for el, n, want, how, cat in plan:
        r = set_val(el, n, want)
        if r == "ok":
            c[(n, how)] = c.get((n, how), 0) + 1
        elif r != "same":
            bad += 1
    return c, bad


def _inherit_counts(items):
    """[(параметр, how, n)] -> «номер секции: вложенным 6 662, изоляции 8 793; группирование: …»."""
    parts = []
    for n, t in INHERIT:
        a = sum(v for (n_, h), v in items if n_ == n and h == "parent")
        b = sum(v for (n_, h), v in items if n_ == n and h == "host")
        if a or b:
            parts.append(u"{0}: вложенным {1}, изоляции {2}".format(t, a, b))
    return u"; ".join(parts)


def section_plan_text(plan, skip):
    """Кратко для окна: что будет записано и что записать нельзя."""
    cnt = {}
    for el, n, want, how, cat in plan:
        cnt[(n, how)] = cnt.get((n, how), 0) + 1
    t = _inherit_counts(cnt.items()) or u"переносить нечего"
    if skip:
        t += u"; не записать (нет параметра или только чтение): " + u", ".join(
            u"{0} — {1}".format(k[1], v) for k, v in sorted(skip.items(), key=lambda x: -x[1])[:4])
    return t


def section_apply(d):
    """Кнопка окна «Что собираем»: номер секции и группирование — во вложенные и изоляцию, одним шагом Ctrl+Z.
    -> (записано всего, текст для окна)."""
    set_doc(d)
    plan, skip = section_plan()
    if not plan:
        return 0, u"переносить нечего: у вложенных и изоляции значения уже как у родителя"
    tg = DB.TransactionGroup(doc, u"Менеджер спецификаций: секция и группирование во вложенные")
    tg.Start()
    try:
        with Tx(u"ADSK_Номер секции и ADSK_Группирование во вложенные и изоляцию"):
            c, bad = section_write(plan)
        tg.Assimilate()
    except Exception:
        tg.RollBack()
        raise
    t = u"записано — " + (_inherit_counts(c.items()) or u"ничего")
    if bad:
        t += u"; не записалось: {0}".format(bad)
    return sum(c.values()), t


def _fallback_unit(it, fallback=True):
    """Единица элемента при пустом ADSK_Группирование (как в set_units): сокращение системы / «без системы» / u""."""
    if not it.systems:
        return D.NO_SYSTEM
    if fallback and len(set(abbr_unit(s) for s in it.systems)) == 1:
        return abbr_unit(it.systems[0])
    return u""


def apply_moves(infos, cfg, report, stats):
    """Переносы систем между группами (cfg["moves"]) — в модель: ADSK_Группирование = значение группы-цели у
    элементов этих систем (верхнего уровня; вложенные и изоляция берут его у родителя / основы — sync_sections).
    Тот же Ctrl+Z, что и сборка."""
    mp = {}
    for m in cfg.get("moves") or []:
        if m.get("sys") and m.get("from") and m.get("to") and m["from"] != m["to"]:
            mp[(m["from"], m["sys"])] = m["to"]
    if not mp:
        return
    fb = cfg.get("group_fallback", True) is not False
    n, bad = 0, {}
    for it in infos:
        if it.parent is not None or it.host is not None:
            continue
        u = inherit_text(it.el, P_GRP) or _fallback_unit(it, fb)
        for sn in it.systems:
            t = mp.get((u, sn))
            if not t:
                continue
            r = set_val(it.el, P_GRP, t)
            if r == "ok":
                n += 1
            elif r != "same":
                bad[r] = bad.get(r, 0) + 1
            break
    stats[u"ADSK_Группирование переписан (перенос систем между группами)"] = n
    if bad:
        why = {"none": u"нет параметра у экземпляра", "ro": u"только чтение", "err": u"ошибка записи"}
        report.append(u"перенос систем: ADSK_Группирование не записан — " + u", ".join(
            u"{0} — {1} эл.".format(why.get(k, k), v) for k, v in sorted(bad.items())))


def sync_sections(infos, report, stats):
    """При сборке (любой режим, тот же Ctrl+Z): ADSK_Номер секции и ADSK_Группирование вложенным — верхнего
    родителя, изоляции труб и воздуховодов — основы; по всей модели, не только категории спецификаций."""
    plan, skip = section_plan()
    if plan:
        c, bad = section_write(plan)
        for (n, how), v in sorted(c.items()):
            stats[u"{0} {1}".format(n, u"вложенным (по родителю)" if how == "parent" else
                                    u"изоляции (по трубе / воздуховоду)")] = v
        if bad:
            report.append(u"номер секции / группирование не записаны у {0} эл.".format(bad))
    for n, t in INHERIT:
        sk = [(k[1], v) for k, v in skip.items() if k[0] == n]
        if sk:
            report.append(u"{0} нельзя записать (нет параметра у категории или только чтение): {1}{2}".format(
                n, u", ".join(u"{0} — {1} эл.".format(c_, v) for c_, v in sorted(sk, key=lambda x: -x[1])),
                u" — в спецификации блока такие элементы не попадут" if n == P_SECTION else u""))


def section_folder(cfg, sec):
    """Имя коллекции листов комплекта блока: «Листы» → section_folder, {секция} — номер секции."""
    tpl = (layout_cfg(cfg).get("section_folder") or u"").strip() or u"{секция}-Спецификации"
    return tpl.replace(u"{секция}", sec) if u"{секция}" in tpl else u"{0}-{1}".format(sec, tpl)


def scope_cfg(cfg, sec):
    """Настройки сборки одного блока: свой реестр спецификаций и листов, своя коллекция; группы — общие."""
    c = dict(cfg)
    reg = (cfg.get("sec_registry") or {}).get(sec) or {}
    c["registry"] = list(reg.get("specs") or [])
    c["sheet_registry"] = list(reg.get("sheets") or [])
    lo = dict(layout_cfg(cfg))
    c["_main_folder"] = (lo.get("sheet_folder") or u"").strip() or u"ВК.С"
    lo["sheet_folder"] = section_folder(cfg, sec)
    c["layout"] = lo
    c["_sec"] = sec
    return c


def block_groups(cfg, sec, systems):
    """Группы блока: свои (cfg["sec_groups"][секция]) или копия общих — только с единицами, что есть в блоке
    (fit_groups: чужие убраны, новые — в свои группы)."""
    import copy
    own = (cfg.get("sec_groups") or {}).get(sec)
    base = copy.deepcopy(own if own else (cfg.get("groups") or []))
    return fit_groups(base, systems, cfg.get("skip_units"))


def scope_back(cfg, c, sec):
    """Реестр блока — обратно в общие настройки (сборка 1.7 не удаляет спецификаций и листов 1.6)."""
    cfg.setdefault("sec_registry", {})[sec] = {"specs": list(c.get("registry") or []),
                                               "sheets": list(c.get("sheet_registry") or [])}


def ensure_section_sheets(cfg, report):
    """Коллекция листов блока: нет — создаётся; пустая — первый лист по образцу коллекции с «Листов».
    Задаёт L.SEC_COLLECTION (новые листы — в неё, номера — внутри неё). -> True | False (не разложить)."""
    lo = layout_cfg(cfg)
    rep = []                                    # в отчёт — только после записи шага (Revit мог его откатить)
    with Tx(u"Спецификации: коллекция блока"):
        ok = _section_sheets(cfg, lo, rep)
    report.extend(rep)
    return ok


def _section_sheets(cfg, lo, report):
    folder = lo.get("sheet_folder")
    main = cfg.get("_main_folder") or u"ВК.С"
    col = L.find_collection(folder)
    if col is None:
        col = L.create_collection(folder)
        if col is None:
            report.append(u"коллекции листов есть только в Revit 2025 и новее — «{0}» не создана, "
                          u"спецификации блока не разложены".format(folder))
            return False
        report.append(u"создана коллекция листов «{0}»".format(folder))
    L.SEC_COLLECTION = col.Id
    if L.collection_sheets(col.Id):
        return True
    L.SHEET_FOLDER = main
    sample = L.get_vks_sheets()
    if not sample:                              # 0.15.0: нет образца — первый лист с нуля (Форма 5, штамп пустой)
        L.create_first_sheet(col.Id, report)
        return True
    dx = L.ft(float(lo.get("left", L.LEFT_FROM_FRAME_MM)))
    dtop = L.ft(float(lo.get("top", L.TOP_FROM_FRAME_MM)))
    L.create_sheet(L.SheetGeom(sample[0], dx, dtop), dx, dtop, report)
    return True


ZERO_KEYS = ("equip", "fix", "acc", "fit", "sprk", "flex", "peq", "dterm", "dacc", "dfit", "dins", "dlin")
ZERO_WARN_ONLY = ("dins", "dlin")   # изоляция воздуховодов: количество считает другой модуль — только предупреждение,
                                    # «Заполнить количество» её не трогает (решение пользователя 02.11.2026)


def _qty_param(el):
    p = safe(lambda: el.LookupParameter(P_QTY)) if el is not None else None
    if p is None:
        return None, None
    if p.StorageType == DB.StorageType.String:
        v = p.AsString()
        v = None if v is None or not v.strip() else v
    elif not safe(lambda: p.HasValue, False):
        v = None
    elif p.StorageType == DB.StorageType.Double:
        v = p.AsDouble()
    elif p.StorageType == DB.StorageType.Integer:
        v = p.AsInteger()
    else:
        v = safe(lambda: p.AsValueString())
    return p, v


_TQ = {}     # id типа -> (параметр, значение) — тип читается один раз


def qty_state(el):
    """ADSK_Количество так, как его посчитает спецификация: экземпляр, иначе тип.
    -> (состояние, где): "ok" | "none" (параметра нет) | "empty" (пусто) | "zero" (0); где — "inst" | "type" | None.
    Текст «» и «0» приводятся к числу."""
    p, v = _qty_param(el)
    if p is not None and v is not None and num(v) > 0:
        return "ok", "inst"
    tid = safe(lambda: id_int(el.GetTypeId()))
    if tid in _TQ:
        tp, tv = _TQ[tid]
    else:
        t = safe(lambda: doc.GetElement(el.GetTypeId()))
        tp, tv = _qty_param(t) if t is not None else (None, None)
        _TQ[tid] = (tp, tv)
    if tp is not None and tv is not None and num(tv) > 0:
        return "ok", "type"
    if p is None and tp is None:
        return "none", None
    if p is not None:
        return ("empty" if v is None else "zero"), "inst"
    return ("empty" if tv is None else "zero"), "type"


def mark_zero_qty(infos):
    """Для окна: у изделий (ZERO_KEYS) ADSK_Количество нет / пусто / 0 (экземпляр, иначе тип).
    it.zq: None | "none" | "empty" | "zero"; it.zq_where: "inst" | "type" | None."""
    n = {"none": 0, "empty": 0, "zero": 0}
    _TQ.clear()
    for it in infos:
        it.zq = None
        it.zq_where = None
        if it.key not in ZERO_KEYS:
            continue
        st, where = qty_state(it.el)
        if st != "ok":
            it.zq, it.zq_where = st, where
            n[st] += 1
    return n


ZQ_TEXT = {"none": u"нет параметра", "empty": u"пусто", "zero": u"0"}


def qty_fill_plan(infos):
    """Кнопка «Заполнить количество» — что будет записано (без записи).
    -> {"write": [Info], "skip": [(Info, причина)]}. Пишется 1 в экземпляр только там, где пусто или 0;
    ручные значения (> 0) не трогаются."""
    write, skip = [], []
    for it in infos:
        st = getattr(it, "zq", None)
        if not st:
            continue
        el = it.el
        if it.key in ZERO_WARN_ONLY:
            skip.append((it, u"изоляция — количество считает другой модуль, проверьте его"))
            continue
        if st == "none":
            skip.append((it, u"нет параметра ADSK_Количество — записать некуда"))
            continue
        if getattr(it, "zq_where", None) == "type":
            skip.append((it, u"параметр в типе: 0 / пусто — в тип кнопка не пишет"))
            continue
        gid = safe(lambda: el.GroupId)
        if gid is not None and gid != DB.ElementId.InvalidElementId:
            skip.append((it, u"элемент в группе модели"))
            continue
        p = safe(lambda: el.LookupParameter(P_QTY))
        if p is None or p.IsReadOnly:
            skip.append((it, u"параметр только для чтения"))
            continue
        if doc.IsWorkshared:
            st_ = safe(lambda: DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id))
            if st_ == DB.CheckoutStatus.OwnedByOtherUser:
                skip.append((it, u"занят другим пользователем"))
                continue
        write.append(it)
    return {"write": write, "skip": skip}


def qty_fill_apply(d, items):
    """Записать 1 шт. — одним шагом Ctrl+Z. Ошибка — модель не меняется. -> (записано, [(Info, причина)])."""
    set_doc(d)
    tg = DB.TransactionGroup(doc, u"Менеджер спецификаций: заполнить количество")
    tg.Start()
    bad, n = [], 0
    try:
        with Tx(u"Заполнить ADSK_Количество"):
            for it in items:
                p = safe(lambda: it.el.LookupParameter(P_QTY))
                if p is None or p.IsReadOnly:
                    bad.append((it, u"параметр только для чтения"))
                    continue
                cur = num(_qty_param(it.el)[1])
                if cur > 0:
                    continue                                   # уже заполнено — не трогаем
                r = set_val(it.el, P_QTY, u"1" if p.StorageType == DB.StorageType.String else 1)
                if r == "ok":
                    n += 1
                elif r != "same":
                    bad.append((it, u"не записалось ({0})".format(r)))
        tg.Assimilate()
    except Exception:
        tg.RollBack()
        raise
    _TQ.clear()
    for it in items:
        st, where = qty_state(it.el)
        it.zq, it.zq_where = (None, None) if st == "ok" else (st, where)
    return n, bad


def group_sys_title(g, amap=None):
    """Полное название систем группы для необязательной строки 12 мм: «Водопровод хозяйственно-питьевой»."""
    amap = AMAP if amap is None else amap
    out = []
    for s in g.get("systems") or []:
        if s == D.NO_SYSTEM:
            continue
        d = gost_desc(abbr_of(s, amap), SYS_KIND.get(s, "pipe")) or s
        d = d[:1].upper() + d[1:]
        if d not in out:
            out.append(d)
    return u"; ".join(out)


# ------------------------------------------------------------------
# единица группировки (0.9.4): системы (ВК) или значения ADSK_Группирование (ОВ, СВОДКА — раздел 22)
# ------------------------------------------------------------------
GROUP_BY = ["systems"]      # "systems" | "grouping" — как прочитаны единицы (set_units)
UNIT_SYS = {}               # единица -> {система: число элементов} (таблетки «системы: …» в карточке)
UNIT_FALLBACK = {}          # единица «по системе» (ADSK_Группирование пусто, одна система) -> число элементов
UNRESOLVED = []             # элементы: ADSK_Группирование пусто и систем несколько — в группы не попадут
MOVE_MAP = {}               # (единица, система) -> новое значение ADSK_Группирование (перенос на «Системах», 0.14.0)


def set_moves(moves):
    """Переносы систем между группами (cfg["moves"]: [{"sys", "from", "to"}]) — для set_units (в памяти)."""
    MOVE_MAP.clear()
    for m in moves or []:
        if m.get("sys") and m.get("from") and m.get("to") and m.get("from") != m.get("to"):
            MOVE_MAP[(m["from"], m["sys"])] = m["to"]


def grouping_value(it):
    """ADSK_Группирование элемента. Как номер секции (0.12.2): у вложенного — значение верхнего родителя, у изоляции
    труб и воздуховодов — основы; у них пусто — своё."""
    src = it.parent if it.parent is not None else getattr(it, "host", None)
    if src is not None:
        v = inherit_text(src, P_GRP)
        if v:
            return v
    return inherit_text(it.el, P_GRP)


def abbr_unit(sysname):
    """Единица «по системе» при пустом ADSK_Группирование — сокращение системы (0.9.6, решение пользователя
    30.10.2026): В 0, В 1, В 2 → «В»; ВЕ 1…16 → «ВЕ». Сокращение — из типа системы, нет — первое слово имени."""
    ab = (abbr_of(sysname, AMAP or {}) or u"").strip() or sysname
    if ab not in SYS_KIND:
        SYS_KIND[ab] = SYS_KIND.get(sysname, "pipe")      # цвет и порядок единицы — как у её систем
    return ab


def set_units(infos, group_by="systems", fallback=True, progress=None):
    """Единицы, из которых собираются группы на вкладке «Системы»:
    systems  — системы элемента (как раньше);
    grouping — значение ADSK_Группирование; пусто — сокращение системы («по системе», если fallback; у всех
               систем элемента одно сокращение); пусто и систем нет — «без системы»; пусто и сокращения
               разные — не определено (UNRESOLVED)."""
    gb = "grouping" if group_by == "grouping" else "systems"
    GROUP_BY[0] = gb
    _VALS[0] = None
    UNIT_SYS.clear()
    UNIT_FALLBACK.clear()
    del UNRESOLVED[:]
    n_ = len(infos)
    for i_, it in enumerate(infos):
        if gb == "systems":
            it.units = it.systems or [D.NO_SYSTEM]
            continue
        if progress is not None and i_ % 500 == 0:
            try:
                progress(0, i_, n_)
            except Exception:
                pass
        if it.grp is None:
            it.grp = grouping_value(it)
        v = it.grp
        if v:
            it.units = [v]
        elif not it.systems:
            it.units = [D.NO_SYSTEM]
        elif fallback and len(set(abbr_unit(s) for s in it.systems)) == 1:
            u_ = abbr_unit(it.systems[0])
            it.units = [u_]
            UNIT_FALLBACK[u_] = UNIT_FALLBACK.get(u_, 0) + 1
        else:
            it.units = []
            if it.key != "gen":
                UNRESOLVED.append(it)
            continue
        if MOVE_MAP:
            for sn in it.systems:
                t_ = MOVE_MAP.get((it.units[0], sn))
                if t_:
                    it.units = [t_]
                    break
        d = UNIT_SYS.setdefault(it.units[0], {})
        for sn in it.systems:
            d[sn] = d.get(sn, 0) + 1
    _VALS[0] = set(it.grp for it in infos if it.grp) if gb == "grouping" else set()
    return gb


def grouping_stats(infos, fallback=True):
    """Для окна «Раздел проекта»: (элементов, с ADSK_Группирование, [значения], не определится). Состояние
    единиц не меняет; значения кэшируются в it.grp."""
    tot = filled = unres = 0
    vals = set()
    for it in infos:
        if it.key == "gen":
            continue
        tot += 1
        if it.grp is None:
            it.grp = grouping_value(it)
        if it.grp:
            filled += 1
            vals.add(it.grp)
        elif (it.systems and not fallback) or len(set(abbr_unit(s) for s in it.systems)) > 1:
            unres += 1
    return tot, filled, sorted(vals, key=nat_key), unres


def units_of(it):
    """Единицы элемента для групп (без set_units — его системы)."""
    u = getattr(it, "units", None)
    if GROUP_BY[0] == "grouping":
        return u or []
    return it.systems or [D.NO_SYSTEM]


def unresolved_text(limit=8):
    """«не определено: N эл. — …» для окна и отчёта ('' — таких нет)."""
    if not UNRESOLVED:
        return u""
    by = {}
    for it in UNRESOLVED:
        k = u", ".join(it.systems)
        by[k] = by.get(k, 0) + 1
    parts = [u"{0} — {1}".format(k, n) for k, n in sorted(by.items(), key=lambda x: -x[1])[:limit]]
    return u"ADSK_Группирование пусто, сокращения систем разные: {0} эл. ({1}{2}) — заполните ADSK_Группирование".format(
        len(UNRESOLVED), u"; ".join(parts), u"; …" if len(by) > limit else u"")


def found_systems(infos, amap):
    """Единицы для вкладки «Системы»: [(имя, число, сокращение, описание)]. В режиме ADSK_Группирование
    сначала значения (сокращение и описание пустые), потом «по системе», в конце «без системы»."""
    cnt = {}
    for it in infos:
        if it.key == "gen":
            continue
        for s in units_of(it):
            cnt[s] = cnt.get(s, 0) + 1
    if GROUP_BY[0] == "grouping":
        def k_(n):
            if n == D.NO_SYSTEM:
                return (2, ())
            if n in UNIT_FALLBACK and n not in UNIT_SYS_VALUES():
                return (1, sys_sort_key(n, amap))
            return (0, nat_key(n))
        names = sorted(cnt.keys(), key=k_)
        out = []
        for n in names:
            if n != D.NO_SYSTEM and n in UNIT_FALLBACK and n not in UNIT_SYS_VALUES():
                ab = abbr_of(n, amap)
                out.append((n, cnt[n], ab, gost_desc(ab, SYS_KIND.get(n, "pipe"))))
            else:
                out.append((n, cnt[n], u"", u""))
        return out
    names = sorted(cnt.keys(), key=lambda n: sys_sort_key(n, amap))
    return [(n, cnt[n], abbr_of(n, amap) if n != D.NO_SYSTEM else u"",
             gost_desc(abbr_of(n, amap), SYS_KIND.get(n, "pipe")) if n != D.NO_SYSTEM else u"")
            for n in names]


_VALS = [None]


def UNIT_SYS_VALUES():
    """Значения ADSK_Группирование, встреченные в модели (кэш на текущий set_units)."""
    return _VALS[0] if _VALS[0] is not None else set()


def is_fallback_unit(name):
    return GROUP_BY[0] == "grouping" and name in UNIT_FALLBACK and name not in UNIT_SYS_VALUES()


def default_groups(systems, skip=None):
    """По сокращению; одинаковые сокращения трубопроводов и вентиляции (В1 водопровод / В1 вытяжка)
    — разные группы. В режиме ADSK_Группирование — группа на каждое значение и на каждое сокращение «по системе»
    (в ней несколько систем — заголовки по ИмяСистемы). skip — исключённые единицы (skip_units), в группы не идут."""
    skip = set(skip or [])
    systems = [s for s in systems if s[0] not in skip]
    if GROUP_BY[0] == "grouping":
        out = []
        for name, cnt, ab, desc in systems:
            g = {"name": name, "systems": [name], "split": None, "header": False}
            if is_fallback_unit(name) and len(UNIT_SYS.get(name) or {}) > 1:
                g["split"], g["header"] = P_SYS, True
            out.append(g)
        return out
    groups, by = [], {}
    kinds = {}
    for name, cnt, ab, desc in systems:
        kinds.setdefault(ab or u"Прочее", set()).add(SYS_KIND.get(name, "pipe"))
    for name, cnt, ab, desc in systems:
        base = ab or u"Прочее"
        kind = SYS_KIND.get(name, "pipe")
        k = (base, kind)
        if k not in by:
            nm = base + (u" (ОВ)" if kind == "duct" and len(kinds[base]) > 1 else u"")
            by[k] = {"name": nm, "systems": [], "split": None, "header": False}
            groups.append(by[k])
        by[k]["systems"].append(name)
    for g in groups:
        if len(g["systems"]) > 1:
            g["split"] = P_SYS
            g["header"] = True
    return groups


# ------------------------------------------------------------------
# порядок: материал, тип, диаметр
# ------------------------------------------------------------------
_WORD = u"A-Za-zА-Яа-яЁё"


def kw_pos(text, kw):
    if not kw or not text:
        return -1
    if len(kw) <= 3 and kw.upper() == kw and re.match(u"^[A-ZА-ЯЁ0-9\\-]+$", kw):
        m = re.search(u"(?<![{0}]){1}(?![{0}])".format(_WORD, re.escape(kw)), text, re.U)
        return m.start() if m else -1
    return text.lower().find(kw.lower())


def first_match(text, entries):
    """Порядок списка — приоритет (первая подходящая)."""
    for i, e in enumerate(entries):
        for kw in e.get("keys", []):
            if kw_pos(text, kw) >= 0:
                return i
    return -1


def earliest_match(text, entries):
    """Кто раньше встречается в тексте."""
    best, bi = None, -1
    for i, e in enumerate(entries):
        for kw in e.get("keys", []):
            p = kw_pos(text, kw)
            if p >= 0 and (best is None or p < best):
                best, bi = p, i
    return bi


PART_TYPE_MAP = {u"Отвод": u"отвод", u"Тройник": u"тройник", u"Крестовина": u"тройник", u"Переход": u"переход",
                 u"Заглушка": u"заглушк"}


FT_SEP = u"\u241f"       # «семейство␟тип» — привязка отдельного типа (главнее привязки семейства)


def ftype_key(fam, typ):
    return u"{0}{1}{2}".format(fam or u"", FT_SEP, typ or u"")


def _bound_index(it, entries):
    """Строка списка, куда перетащен тип (главнее) или семейство элемента; -1 — нет."""
    k = ftype_key(it.fam, it.typ)
    for i, e in enumerate(entries):
        if k in (e.get("ftypes") or []):
            return i
    for i, e in enumerate(entries):
        if it.fam in (e.get("fams") or []):
            return i
    return -1


def classify(it, order):
    o = order.get(it.key) or {}
    mats = o.get("materials") or []
    types = o.get("types") or []
    text = it.name or u""
    alt = u"{0} {1}".format(it.fam, it.typ)
    if it.key in D.INS_KEYS:
        # изоляция: типы изоляции перетаскиваются в строки (fams = имена типов); старые настройки — имя строки
        mi = -1
        for i, m in enumerate(mats):
            if it.typ in (m.get("fams") or []):
                mi = i
                break
        if mi < 0:
            names = [m.get("name") for m in mats]
            mi = names.index(it.typ) if it.typ in names else -1
        it.mat = mi if mi >= 0 else len(mats)
    else:
        mi = _bound_index(it, mats)                # перетащенное на материал — главнее признаков
        if mi < 0:
            mi = earliest_match(text, mats)
        if mi < 0:
            mi = earliest_match(alt, mats)
        it.mat = mi if mi >= 0 else len(mats)
    ti = _bound_index(it, types)
    if ti < 0 and it.key == "fit" and it.part in PART_TYPE_MAP:
        kw = PART_TYPE_MAP[it.part]
        for i, t in enumerate(types):
            if any(k.lower().startswith(kw) for k in t.get("keys", [])):
                ti = i
                break
    if ti < 0:
        ti = first_match(text, types)
    if ti < 0:
        ti = first_match(alt, types)
    it.tp = ti if ti >= 0 else len(types)


def default_order(cfg):
    """Готовые списки шага 3 для раздела проекта (cfg["discipline"]); раздела нет или «скоро» — набор ВК."""
    return getattr(D, "ORDER_BY_DISC", {}).get((cfg or {}).get("discipline")) or D.ORDER


def order_set_for(cfg, key):
    """Копия набора раздела для одной категории (кнопка «Набор раздела» на шаге 3)."""
    import copy
    return copy.deepcopy(default_order(cfg).get(key) or {"inner": "type", "materials": [], "types": []})


def apply_disc_order(cfg):
    """После выбора / смены раздела: категории, подставленные по умолчанию (_order_auto) и с тех пор не
    изменённые, — набором нового раздела. Сохранённое в проекте и правленное в окне не трогается.
    -> число заменённых категорий."""
    import copy
    order = cfg.get("order")
    auto = cfg.get("_order_auto") or {}
    if not isinstance(order, dict) or not auto:
        return 0
    src = default_order(cfg)
    n = 0
    for k in list(auto.keys()):
        if k not in src or order.get(k) != auto[k]:
            continue
        if order[k] != src[k]:
            n += 1
        order[k] = copy.deepcopy(src[k])
        auto[k] = copy.deepcopy(src[k])
    return n


def order_on(cfg, key=None):
    """Шаг 3 включён (для категории key): сортировка по готовым спискам; выключен — «по имени»."""
    if not cfg.get("order_on", D.ORDER_ON):
        return key is not None and key in (cfg.get("order_cats_on") or [])
    return key is None or key not in (cfg.get("order_off") or [])


def sort_param(cfg):
    return (cfg.get("sort_param") or D.SORT_PARAM).strip() or D.SORT_PARAM


def kit_param(cfg):
    """Параметр «материал × 100 + тип»; пусто — не писать (тогда порядок только по рангу)."""
    v = cfg.get("kit_param", D.KIT_PARAM)
    return (v or u"").strip()


SCHEDULE_GROUP_PARAMS = (P_MAIN, P_SYS, P_GRP)
SYS_ROWS = (P_MAIN, P_SYS)          # строки прежних настроек «по системе» — теперь сортировка по ИмяСистемы скрытая


def norm(v):
    if v is None:
        return (1, u"")
    if isinstance(v, (int, float)):
        return (0, float(v))
    return (1, (u"%s" % v).strip().lower())


def sort_value(it, f, inner):
    param = f["param"]
    if param == P_KIT:
        if getattr(it, "by_name", False):
            return (0, 0.0)
        return (0, float(it.mat * 100 + (0 if inner == "diam" else it.tp)))
    if param == P_SORT:
        return (0, round(it.diam or 0.0, 1) * 1000 + (0 if getattr(it, "by_name", False) or inner != "diam" else it.tp))
    v = field_value(it.el, f)
    if getattr(it, "by_name", False) and isinstance(v, type(u"")):
        return (2, nat_tuple(v))                       # «по имени»: числа в тексте — числом (Ø20 перед Ø110)
    return norm(v)


def nat_tuple(s):
    return tuple((0, int(t), u"") if t.isdigit() else (1, 0, t.lower()) for t in re.split(u"(\\d+)", s or u"") if t)


def sort_rows_for(cfg, key):
    s = cfg.get("sort") or {}
    return s.get(key) or s.get("common") or D.SORT_FIELDS


def sys_sort(cfg):
    """0.16.0: ИмяСистемы скрытым полем сортировки — только в ВК (группа = системы). В ОВ (группы по
    ADSK_Группирование, в группе десятки систем) оно дробило таблицу на куски по системам без заголовков."""
    return (cfg or {}).get("group_by") != "grouping"


REVIT_SORT_MAX = 4          # уровней сортировки в свойствах спецификации Revit


def schedule_fields(rows, split, split_header, by_sys=True):
    """Поля сортировки спецификации Revit (не больше REVIT_SORT_MAX): [«Делить по»] + ИмяСистемы (скрыто; только
    ВК, by_sys) + ADSK_Группирование с заголовком (если стоит первым) + 0.18.0: дальше — включённые строки окна
    «Сортировка» по порядку («Материал и тип» = ADSK_Позиция_Комплект, «Диаметр» = ADSK_Позиция_Сортировка — ранг,
    ADSK_Наименование, ADSK_Марка…). ADSK_Группирование без заголовка в Revit не ставится. Что не влезло в 4 поля —
    учтено в ранге (ADSK_Позиция_Сортировка)."""
    out = []
    if split:
        out.append((P_SYS if split == P_MAIN else split, bool(split_header)))
    if by_sys and P_SYS not in [x[0] for x in out]:
        out.append((P_SYS, False))
    lead = True
    for r in rows:
        if not r.get("on"):
            continue
        prm = r["param"]
        if prm in SYS_ROWS:
            continue
        if prm == P_GRP:          # ОВ (by_sys=False): группа и есть ADSK_Группирование — в сортировке не нужен
            if by_sys and lead and r.get("header") and prm not in [x[0] for x in out]:
                out.append((prm, True))
            continue
        lead = False
        if prm in [x[0] for x in out]:
            continue
        out.append((prm, False))
    if not [x for x in out if x[0] not in (P_SYS, P_GRP) and x[0] != split]:
        out.append((P_SORT, False))          # строк окна нет — хотя бы ранг
    return out[:REVIT_SORT_MAX]


def sort_desc(rows):
    """Параметры строк окна «по убыванию»."""
    return set(r["param"] for r in rows or [] if r.get("on") and not r.get("asc", True))


def inner_sort_fields(cfg, key):
    """Поля, по которым кнопка сама считает ранг строк категории. Шаг 3 выключен — «по имени»."""
    if not order_on(cfg, key):
        return [dict(r) for r in D.SORT_BY_NAME]
    rows = [r for r in sort_rows_for(cfg, key) if r.get("on") and r["param"] not in SYS_ROWS]
    lead = 0
    for r in rows:
        if r["param"] == P_GRP:
            lead += 1
        else:
            break
    return rows[lead:]


KIT_KEYS = ("equip", "fix", "acc", "sprk")


def compute_order(infos, cfg, report):
    order = cfg.get("order") or default_order(cfg)
    kit_order = cfg.setdefault("kit_order", {})
    byid = dict((i.id, i) for i in infos)
    for it in infos:
        classify(it, order)                      # и при выключенном шаге: номер по системе (насосы) — по типу
        it.by_name = not order_on(cfg, it.key)
    # дети комплекта (вложенные той же категории, родитель в спецификации). Только оборудование, приборы и
    # арматура: вложенные фитинги/трубы/изоляция считаются вместе с такими же отдельными (одна строка на имя)
    kids = {}
    for it in infos:
        p = byid.get(it.parent_id) if it.parent_id is not None else None
        if (p is not None and p.key == it.key and it.key in KIT_KEYS and not p.hidden and not it.hidden):
            kids.setdefault(p.id, []).append(it)
    cross = {}
    for it in infos:
        p = byid.get(it.parent_id) if it.parent_id is not None else None
        if p is not None and p.key != it.key and not it.hidden and it.key not in ("ins",):
            cross[(p.fam, it.fam, it.key)] = cross.get((p.fam, it.fam, it.key), 0) + 1
    for (pf, cf, k), n in sorted(cross.items()):
        report.append(u"вложенное другой категории (идёт в свою спецификацию): «{0}» в «{1}» — {2} шт.".format(cf, pf, n))
    # порядок детей в комплекте: из настроек, иначе из старого ADSK_Позиция_Комплект (0.1, 0.2 …), иначе по имени
    for pid, lst in kids.items():
        p = byid[pid]
        known = kit_order.get(p.fam)
        if not known:
            tmp = []
            for c in lst:
                v = pval(c.el, P_KIT)
                tmp.append((v if (v is not None and 0 < v < 1) else 9, c.name))
            known = []
            for v, n in sorted(set(tmp)):
                if n not in known:
                    known.append(n)
            kit_order[p.fam] = known
        for c in lst:
            if c.name not in known:
                known.append(c.name)
    # ключи: порядок внутри (система и ADSK_Группирование — поля спецификации, остальное — ранг)
    tuples = {}
    top = []
    for it in infos:
        p = byid.get(it.parent_id) if it.parent_id is not None else None
        in_kit = p is not None and p.id in kids and it in kids[p.id]
        inner = (order.get(it.key) or {}).get("inner", "type")
        it.kit = 0 if it.by_name else it.mat * 100 + (0 if inner == "diam" else it.tp)
        if not in_kit:
            top.append(it)
    bykey = {}
    for it in top:
        bykey.setdefault(it.key, []).append(it)
    rank_of = {}
    for k, lst in bykey.items():
        fields = inner_sort_fields(cfg, k)
        inner = (order.get(k) or {}).get("inner", "type")
        desc = [not f.get("asc", True) for f in fields] + [False, False, False]
        # одна строка спецификации = одно наименование/марка/код в группе: её значение по полю — минимум
        # (по убыванию — максимум) из её элементов, чтобы строка не разваливалась на несколько
        rowvals, rid_of = {}, {}
        for it in lst:
            vals = [sort_value(it, f, inner) for f in fields]
            ties = (norm(it.name), norm(tval(it.el, u"ADSK_Марка")), norm(tval(it.el, u"ADSK_Код изделия")))
            rid = (it.group or u"", ties)
            rid_of[it.id] = rid
            cur = rowvals.get(rid)
            if cur is None:
                rowvals[rid] = [vals, ties]
            else:
                for i, v in enumerate(vals):
                    if (v > cur[0][i]) if desc[i] else (v < cur[0][i]):
                        cur[0][i] = v
        keys = {}
        for it in lst:
            vals, ties = rowvals[rid_of[it.id]]
            keys[it.id] = tuple(vals) + ties
        uniq = sorted(set(keys.values()))
        idx = list(range(len(uniq)))
        for i in reversed(range(len(desc))):
            idx.sort(key=lambda j, i=i: uniq[j][i], reverse=desc[i])
        pos = dict((uniq[j], n + 1) for n, j in enumerate(idx))
        for it in lst:
            rank_of[it.id] = pos[keys[it.id]]
    # 0.19.0: вид родителя = группа + категория + семейство + типоразмер («SOLE_Радиатор стальной панельный_H :
    # CV 33-200»). Вложенные той же категории идут один раз — после последней строки своего вида (все размеры
    # радиатора, затем его кронштейны общим количеством), а не после каждой строки родителя.
    kind_last = {}
    for it in top:
        kk = (it.group or u"", it.key, it.fam, it.typ)
        r = rank_of.get(it.id, 0)
        if r > kind_last.get(kk, -1):
            kind_last[kk] = r
    for it in infos:
        p = byid.get(it.parent_id) if it.parent_id is not None else None
        in_kit = p is not None and p.id in kids and it in kids[p.id]
        if in_kit:
            kn = kit_order.get(p.fam) or []
            ci = kn.index(it.name) + 1 if it.name in kn else 999
            kk = (p.group or u"", p.key, p.fam, p.typ)
            tuples[it.id] = (kind_last.get(kk, rank_of.get(p.id, 0)), ci, it.name)
            it.kit = p.kit
        else:
            tuples[it.id] = (rank_of.get(it.id, 0), 0, u"")
    for k in set(i.key for i in infos):
        lst = [i for i in infos if i.key == k]
        uniq = sorted(set(tuples[i.id] for i in lst))
        rank = dict((t, n + 1) for n, t in enumerate(uniq))
        for it in lst:
            it.sortv = rank[tuples[it.id]]
    return kids


# ------------------------------------------------------------------
# изоляция (логика Dynamo ADSK: наружный диаметр, длина на фитингах)
# ------------------------------------------------------------------
INS_RE = re.compile(u"^(.*?)(для)\\s*(ø[^,]*)?(,.*)?$", re.S)


def fmt_num(x):
    s = (u"%.2f" % x).rstrip(u"0").rstrip(u".")
    return s


def ins_name(base, od):
    base = base or u""
    m = INS_RE.match(base)
    if m:
        prefix, rest = m.group(1), m.group(4) or u""
    else:
        prefix, rest = base.rstrip() + u" ", u""
    return u"{0}для ø{1}{2}".format(prefix, fmt_num(od), rest)


def pipe_od(p):
    return safe(lambda: p.get_Parameter(DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER).AsDouble() * FT, 0.0)


def is_pipe(el):
    return el is not None and el.Category is not None and id_int(el.Category.Id) == int(DB.BuiltInCategory.OST_PipeCurves)


def connected_pipe_od(host):
    best = 0.0
    for c in connectors(host):
        try:
            for r in c.AllRefs:
                o = r.Owner
                if is_pipe(o):
                    best = max(best, pipe_od(o))
        except Exception:
            pass
    return best


def fitting_len_mm(host):
    cs = connectors(host)
    pts = []
    for c in cs:
        try:
            pts.append((c.Origin, c.CoordinateSystem.BasisZ))
        except Exception:
            pass
    if not pts:
        return 0.0
    loc = safe(lambda: host.Location.Point)
    if len(pts) == 2:
        (o1, d1), (o2, d2) = pts
        chord = o1.DistanceTo(o2)
        part = part_type(host)
        if part == u"Отвод":
            ang = d1.AngleTo(d2)                 # между внешними направлениями
            theta = math.pi - ang                 # угол поворота
            if theta > 1e-3 and chord > 1e-9:
                r = chord / (2.0 * math.sin(theta / 2.0))
                return r * theta * FT
        return chord * FT
    if loc is None:
        x = sum(p[0].X for p in pts) / len(pts)
        y = sum(p[0].Y for p in pts) / len(pts)
        z = sum(p[0].Z for p in pts) / len(pts)
        loc = DB.XYZ(x, y, z)
    return sum(p[0].DistanceTo(loc) for p in pts) * FT


def process_insulation(infos, report, stats):
    ins = [i for i in infos if i.key == "ins"]
    pipe_factor = {}
    plan = []
    for it in ins:
        el = it.el
        h = safe(lambda: doc.GetElement(el.HostElementId))
        if h is None:
            continue
        if is_pipe(h):
            od = pipe_od(h)
            new = ins_name(it.name, od) if od else it.name
            length_m = safe(lambda: el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() * FT / 1000.0, 0.0)
            q = num(pval(el, P_QTY))
            if q <= 0:
                q = length_m
                plan.append((it, new, q))
            else:
                plan.append((it, new, None))
            if length_m > 0 and q:
                f = pipe_factor.setdefault((new, it.unit), [0.0, 0.0])
                f[0] += q
                f[1] += length_m
        else:
            od = connected_pipe_od(h) or conn_diam(h)
            new = ins_name(it.name.split(u"-ø")[0] if it.name else it.name, od) if od else it.name
            lm = fitting_len_mm(h) / 1000.0
            plan.append((it, new, (u"fit", lm, od)))
    renamed = qset = 0
    for it, new, q in plan:
        if new and new != it.name:
            if set_val(it.el, P_NAME, new) == "ok":
                renamed += 1
                it.name = new
        val = None
        if isinstance(q, tuple):
            lm, od = q[1], q[2]
            f = pipe_factor.get((it.name, it.unit))
            if f and f[1] > 0:
                k = f[0] / f[1]
            elif u"м²" in it.unit or u"м2" in it.unit:
                t = safe(lambda: it.el.Thickness * FT, 0.0) or 0.0
                k = math.pi * (od + 2 * t) / 1000.0
            else:
                k = 1.0
            val = round(lm * k, 3)
        elif q is not None:
            val = round(q, 3)
        if val is not None and set_val(it.el, P_QTY, val) == "ok":
            qset += 1
    stats["изоляция: переименовано"] = renamed
    stats["изоляция: записано количество"] = qset


# ------------------------------------------------------------------
# количество
# ------------------------------------------------------------------
def fill_quantities(infos, stats, report=None, cats=None):
    """Количество не придумывается: штучным с пустым/нулевым ADSK_Количество (экземпляр, иначе тип) — только
    предупреждение (по выбранным категориям cats, если заданы). Трубам без количества — длина, м."""
    nl = 0
    zero = {}
    _TQ.clear()
    for it in infos:
        if it.key in ZERO_KEYS:
            if cats is not None and it.key not in cats:
                continue
            st, where = qty_state(it.el)
            if st != "ok":
                k = (it.key, it.name or it.fam, st)
                zero[k] = zero.get(k, 0) + 1
        elif it.key == "pipe":
            q = num(pval(it.el, P_QTY))
            if q <= 0:
                lm = safe(lambda: it.el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() * FT / 1000.0, 0.0)
                if lm and set_val(it.el, P_QTY, round(lm, 3)) == "ok":
                    nl += 1
    stats[u"количество труб (м) записано"] = nl
    if zero:
        stats[u"изделий без ADSK_Количество (не дописано)"] = sum(zero.values())
        if report is not None:
            title = dict((k, t) for k, b, t, o in D.CATS)
            items = sorted(zero.items())
            report.append(u"ADSK_Количество не заполнено — исправьте в модели или кнопкой «Заполнить количество» "
                          u"(вкладка «Что специфицируем»): " + u"; ".join(
                              u"{0}: «{1}» — {2} эл. ({3})".format(title.get(k, k), n, c, ZQ_TEXT.get(st, st))
                              for (k, n, st), c in items[:12]) + (u" …" if len(items) > 12 else u""))


# ------------------------------------------------------------------
# гибы (труба в категории «Соединительные детали») → в количество трубы
# ------------------------------------------------------------------
BEND_SCHEMA_GUID = "3f7c2a91-5d0e-4b6a-9c84-2e1f6d3b7a55"
OLD_BEND_SCHEMA_GUID = "6b0f6d8e-2d4b-4c55-9a51-5b5f1c7a9e31"   # прибавки версии 08.10 — только вычитаются
_BEND_SCHEMA = None


def _bend_schema():
    """Хранилище на трубе: сколько метров гибов прибавлено (повторный запуск вычитает, не задваивает;
    Ctrl+Z откатывает и его)."""
    global _BEND_SCHEMA
    if _BEND_SCHEMA is not None:
        return _BEND_SCHEMA
    from System import Guid, Double
    from Autodesk.Revit.DB.ExtensibleStorage import Schema, SchemaBuilder, AccessLevel
    g = Guid(BEND_SCHEMA_GUID)
    sc = Schema.Lookup(g)
    if sc is None:
        sb = SchemaBuilder(g)
        sb.SetReadAccessLevel(AccessLevel.Public)
        sb.SetWriteAccessLevel(AccessLevel.Public)
        sb.SetVendorId("SPECMGR")
        sb.SetSchemaName("SpecManagerBendAdded")
        fb = sb.AddSimpleField("AddedM", Double)
        safe(lambda: fb.SetSpec(DB.SpecTypeId.Number))
        sc = sb.Finish()
    _BEND_SCHEMA = sc
    return sc


def _old_bend_schema():
    try:
        from System import Guid
        from Autodesk.Revit.DB.ExtensibleStorage import Schema
        return Schema.Lookup(Guid(OLD_BEND_SCHEMA_GUID))
    except Exception:
        return None


def _bend_get(el, sc):
    from System import Double
    try:
        ent = el.GetEntity(sc)
        if ent is None or not ent.IsValid():
            return 0.0
        return float(ent.Get[Double]("AddedM", DB.UnitTypeId.General))
    except Exception:
        return 0.0


def _bend_set(el, sc, val):
    from System import Double
    from Autodesk.Revit.DB.ExtensibleStorage import Entity
    if val <= 0:
        safe(lambda: el.DeleteEntity(sc))
        return
    ent = Entity(sc)
    ent.Set[Double]("AddedM", float(val), DB.UnitTypeId.General)
    el.SetEntity(ent)


def _norm_name(s):
    return u" ".join((s or u"").lower().replace(u"ё", u"е").split())


def is_bend(it, pipe_names):
    if it.key != "fit":
        return False
    n = _norm_name(it.name)
    if not n:
        return False
    if n in pipe_names:
        return True
    return any(n.startswith(_norm_name(k)) for k in D.BEND_NAME_STARTS)


def merge_bends(infos, report, stats):
    """Детали-«трубы» (гибы, отводы из трубы): ADSK_Количество → в трубу той же группы с тем же наименованием
    (иначе тот же Ø и основная система). Сама деталь из спецификации деталей убирается. После assign_groups,
    в транзакции. Прежние прибавки сначала вычитаются."""
    pipes = [i for i in infos if i.key == "pipe"]
    try:
        sc = _bend_schema()
    except Exception as ex:
        report.append(u"гибы: не создалось хранилище ({0}) — гибы не перенесены в трубы".format(ex))
        return
    old = _old_bend_schema()
    for p in pipes:
        for s_ in [x for x in (sc, old) if x is not None]:
            prev = _bend_get(p.el, s_)
            if prev > 0:
                q = num(pval(p.el, P_QTY))
                set_val(p.el, P_QTY, round(max(0.0, q - prev), 3))
                safe(lambda: p.el.DeleteEntity(s_))
    if not D.BEND_MERGE:
        return
    pipe_names = set(_norm_name(p.name) for p in pipes if p.name)
    by_name, by_diam = {}, {}
    for p in pipes:
        if not p.group or p.hidden:
            continue
        by_name.setdefault((p.group, _norm_name(p.name)), []).append(p)
        by_diam.setdefault((p.group, p.main, round(p.diam or 0, 0)), []).append(p)
    add, moved, lost = {}, 0, {}
    best = {}                            # самая длинная труба списка кандидатов — один раз на список
    for it in infos:
        if not it.group or it.hidden or not is_bend(it, pipe_names):
            continue
        q = num(pval(it.el, P_QTY))
        if q <= 0:
            q = fitting_len_mm(it.el) / 1000.0
        cands = by_name.get((it.group, _norm_name(it.name))) or by_diam.get((it.group, it.main, round(it.diam or 0, 0)))
        it.hidden = True                 # из спецификации деталей — в любом случае
        it.group, it.main = None, u""
        if not cands or q <= 0:
            lost[it.name] = lost.get(it.name, 0) + 1
            continue
        tgt = best.get(id(cands))
        if tgt is None:
            tgt = max(cands, key=lambda p: safe(lambda: p.el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble(), 0.0))
            best[id(cands)] = tgt
        add[tgt.id] = (tgt, add.get(tgt.id, (tgt, 0.0))[1] + q)
        moved += 1
    for tgt, q in add.values():
        cur = num(pval(tgt.el, P_QTY))
        if set_val(tgt.el, P_QTY, round(cur + q, 3)) in ("ok", "same"):
            _bend_set(tgt.el, sc, round(q, 3))
    stats[u"гибы перенесены в трубы (шт.)"] = moved
    if add:
        report.append(u"гибы: {0} шт. перенесены в трубы ({1:g} м) и убраны из соединительных деталей".format(
            moved, round(sum(q for t, q in add.values()), 2)))
    if lost:
        report.append(u"гибы без подходящей трубы (убраны из деталей, в трубы не добавлены): " +
                      u"; ".join(u"«{0}» — {1}".format(k, v) for k, v in sorted(lost.items())[:8]))


# ------------------------------------------------------------------
# параметры ADSK_Система_* в проекте
# ------------------------------------------------------------------
def bound_categories(name):
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        if it.Key.Name == name:
            return it.Key, it.Current
    return None, None


def spec_category_set():
    cs = doc.Application.Create.NewCategorySet()
    for key, bname, title, order in active_cats():
        b = bic(bname)
        if b is None:
            continue
        c = safe(lambda: DB.Category.GetCategory(doc, b))
        if c is not None and c.AllowsBoundParameters:
            cs.Insert(c)
    return cs


def ensure_params(report):
    """ADSK_Система_Обозначение — экземпляр, категории спецификаций (ADSK_Система_Имя больше не нужен).
    ИмяСистемы — параметр проекта (как Bim2B); его кнопка не добавляет: нет — предупреждение."""
    if bound_categories(P_SYS)[0] is None:
        report.append(u"в проекте нет параметра «ИмяСистемы» — сортировка по системе не работает; добавьте параметр "
                      u"проекта (текст, экземпляр) для категорий спецификаций")
    need = []
    for name in (P_GROUP,):
        d, b = bound_categories(name)
        if d is None:
            need.append(name)
        else:
            cs = spec_category_set()
            missing = [c for c in cs if not b.Categories.Contains(c)]
            if missing:
                for c in missing:
                    b.Categories.Insert(c)
                doc.ParameterBindings.ReInsert(d, b)
                report.append(u"параметр {0}: добавлены категории {1}".format(name, u", ".join(c.Name for c in missing)))
    if not need:
        return
    app = doc.Application
    old = app.SharedParametersFilename
    path = os.path.join(HERE, u"ADSK_ФОП_системы.txt")
    try:
        app.SharedParametersFilename = path
        f = app.OpenSharedParameterFile()
        if f is None:
            raise Exception(u"не открылся файл общих параметров " + path)
        for name in need:
            dfn = None
            for g in f.Groups:
                for x in g.Definitions:
                    if x.Name == name:
                        dfn = x
            if dfn is None:
                raise Exception(u"нет {0} в {1}".format(name, path))
            b = doc.Application.Create.NewInstanceBinding(spec_category_set())
            grp = safe(lambda: DB.GroupTypeId.Mechanical)
            ok = doc.ParameterBindings.Insert(dfn, b, grp) if grp is not None else doc.ParameterBindings.Insert(dfn, b)
            report.append(u"добавлен параметр проекта {0} ({1})".format(name, u"ok" if ok else u"не добавился"))
            spe = DB.SharedParameterElement.Lookup(doc, dfn.GUID)
            if spe is not None:
                safe(lambda: spe.GetDefinition().SetAllowVaryBetweenGroups(doc, True))
    finally:
        try:
            app.SharedParametersFilename = old or u""
        except Exception:
            pass


# ------------------------------------------------------------------
# группы систем
# ------------------------------------------------------------------
def is_hidden(it, hidden):
    if it.key in (hidden.get("cats") or []):
        return True
    for k, f in hidden.get("fams") or []:
        if k == it.key and f == it.fam:
            return True
    for k, f, n in hidden.get("names") or []:
        if k == it.key and f == it.fam and n == it.name:
            return True
    return False


def default_hidden(infos):
    names = sorted(set((i.key, i.fam, i.name) for i in infos if i.name == SKIP or (i.key != "ins" and not i.name.strip())))
    return {"cats": list(D.HIDDEN_CATS), "fams": [], "names": [list(x) for x in names]}


def assign_groups(infos, groups, hidden, stats):
    order = {}
    for gi, g in enumerate(groups):
        for s in g.get("systems") or []:
            order.setdefault(s, gi)
    w = 0
    nog = 0
    for it in infos:
        it.hidden = is_hidden(it, hidden)
        best = None
        for s in units_of(it):
            gi = order.get(s)
            if gi is not None and (best is None or gi < best[0]):
                best = (gi, s)
        if it.hidden or best is None:
            it.group, it.main = None, u""
            if best is None and not it.hidden and (GROUP_BY[0] != "grouping" or it.units):
                nog += 1
        else:
            it.group = groups[best[0]]["name"]
            if GROUP_BY[0] == "grouping":      # основная система — своя первая (группа — по ADSK_Группирование)
                it.main = it.systems[0] if it.systems else u""
            else:
                it.main = best[1] if best[1] != D.NO_SYSTEM else u""
    stats["элементов вне групп (не выбраны или исключены)"] = nog
    if GROUP_BY[0] == "grouping" and UNRESOLVED:
        stats["элементов не определено (ADSK_Группирование пусто, сокращения систем разные)"] = len(UNRESOLVED)
    return w


def row_value(it, prm):
    if prm in SYS_ROWS:
        return it.sysraw
    if prm == P_SORT:
        return it.sortv
    if prm == P_KIT:
        return getattr(it, "kit", 0)
    v = tval(it.el, prm)
    return (u"%s" % v).strip() if v is not None else u""


def num(v):
    try:
        return float(v)
    except Exception:
        try:
            return float((u"%s" % v).replace(u",", u".").split()[0])
        except Exception:
            return 0.0


def _row_sig(it, flds=None):
    """Ключ строки для «скрыть строку»: группа, категория, наименование, марка, код, единица — не зависит от
    критериев сортировки (они меняются между запусками)."""
    vals = [it.group or u"", it.key, it.name or u"", u"%s" % (tval(it.el, u"ADSK_Марка") or u""),
            u"%s" % (tval(it.el, u"ADSK_Код изделия") or u""), it.unit or u""]
    return u"\u241f".join(vals)


def qty_rows(infos, cfg, qty=None):
    """Строки спецификаций (как у Revit): {(группа, категория, поля…): [сумма, [элементы], ключ]}."""
    qty = qty or (lambda it: num(tval(it.el, P_QTY)))
    gmap = dict((g["name"], g) for g in cfg["groups"])
    rows = {}
    for it in infos:
        if not it.group or it.hidden or it.key == "gen":
            continue
        g = gmap.get(it.group) or {}
        flds = schedule_fields(sort_rows_for(cfg, it.key), g.get("split"), g.get("header"), sys_sort(cfg))
        k = (it.group, it.key) + tuple(row_value(it, prm) for prm, h in flds if prm != P_GRP)
        r = rows.get(k)
        if r is None:
            r = rows[k] = [0.0, [], _row_sig(it)]
        r[0] += qty(it)
        r[1].append(it)
    return rows


def qty_min(cfg):
    try:
        v = float(cfg.get("qty_min", D.QTY_MIN))
    except Exception:
        v = D.QTY_MIN
    return v if v >= 0 else D.QTY_MIN


def small_rows_preview(infos, cfg):
    """Для окна «Строки < порога»: тот же расчёт, что при сборке, по текущим значениям модели. Ничего не пишет.
    Трубам без количества — длина (как сделает сборка)."""
    import copy
    c = copy.deepcopy(cfg)
    qmin = qty_min(c)
    assign_groups(infos, c["groups"], c.get("hidden") or {}, {})
    compute_order(infos, c, [])

    def q(it):
        v = num(tval(it.el, P_QTY))
        if v > 0:
            return v
        if it.key == "pipe":
            return safe(lambda: it.el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() * FT / 1000.0, 0.0)
        return v
    title = dict((k, t) for k, b, t, o in D.CATS)
    out = []
    for k, (tot, lst, sig) in qty_rows(infos, c, q).items():
        if zero_auto(k[1], tot):
            continue                         # 0.21.0: нулевые мерные скрываются сами — в окне их нет
        if tot < qmin - 1e-9:
            it = lst[0]
            out.append({"sig": sig, "group": k[0], "cat": title.get(k[1], k[1]), "name": it.name or it.fam,
                        "sys": it.sysraw or u"",
                        "qty": round(tot, 4), "unit": it.unit or (u"м" if it.key == "pipe" else u""), "n": len(lst)})
    gi = dict((g["name"], i) for i, g in enumerate(c["groups"]))
    out.sort(key=lambda r: (gi.get(r["group"], 999), r["cat"], -r["qty"], r["name"]))
    return out


ZERO_AUTO_KEYS = ("pipe", "flex", "ins", "duct", "fduct", "dins", "dlin")   # мерные (м, м²): количество — из
                                    # ADSK_Количество / длины, а не «Число»; штучные с 0 так не скрываются (0.21.0)


def zero_auto(key, tot):
    """Строка мерной категории с суммой ровно 0 — скрывается сама (решение пользователя 02.11.2026)."""
    return key in ZERO_AUTO_KEYS and abs(tot) < 1e-9


def drop_zero_rows(infos, cfg, stats, report):
    """Строки спецификации с суммой ADSK_Количество меньше порога («<») сами не скрываются: скрываются только
    отмеченные в окне «Строки < порога» (cfg["qty_hide"]). Остальные — в отчёт одной строкой."""
    qmin = qty_min(cfg)
    hide = set(cfg.get("qty_hide") or [])
    n_rows = n_el = 0
    shown = []
    small_ids = set()
    zeros = []
    for k, (tot, lst, sig) in qty_rows(infos, cfg).items():
        if zero_auto(k[1], tot):
            zeros.append(u"«{0}» ({1} эл., группа {2})".format(lst[0].name or lst[0].fam, len(lst), k[0]))
            for it in lst:
                it.group, it.main = None, u""
            continue
        if tot < qmin - 1e-9:
            if sig not in hide:
                shown.append(u"«{0}» = {1:g} (группа {2})".format(lst[0].name or lst[0].fam, round(tot, 4), k[0]))
                small_ids.update(id(x) for x in lst)
                continue
            n_rows += 1
            n_el += len(lst)
            for it in lst:
                it.group, it.main = None, u""
    if zeros:
        report.append(u"скрыты строки с количеством 0 (м, м²) — проверьте количество в модели: " +
                      u"; ".join(sorted(zeros)[:10]) + (u" …" if len(zeros) > 10 else u""))
    stats[u"строк с количеством 0 скрыто"] = len(zeros)
    if n_rows:
        report.append(u"скрыто по вашему выбору строк с количеством < {0:g}: {1} ({2} эл.)".format(qmin, n_rows, n_el))
    stats[u"строк < порога скрыто (отмечено)"] = n_rows
    if shown:
        report.append(u"строки с количеством < {0:g} оставлены ({1}) — скрыть можно в окне «Строки < порога»: ".format(
            qmin, len(shown)) + u"; ".join(sorted(shown)[:10]) + (u" …" if len(shown) > 10 else u""))
    rmin = float(getattr(D, "ROW_MIN", 1.0))
    low = []
    for k, (tot, lst, sig) in qty_rows(infos, cfg).items():
        if lst[0].group and tot < rmin - 1e-9 and id(lst[0]) not in small_ids:
            low.append(u"«{0}» = {1:g} {2} (группа {3})".format(lst[0].name or lst[0].fam, round(tot, 3),
                                                              lst[0].unit, k[0]))
    if low:
        report.append(u"строки с количеством меньше {0:g} — проверьте: ".format(rmin) + u"; ".join(sorted(low)[:15]) +
                      (u" …" if len(low) > 15 else u""))
        stats[u"строк с количеством < {0:g}".format(rmin)] = len(low)


def _set_rank(el, name, v):
    """Ранг сортировки: в числовой параметр — число, в текстовый — с нулями слева (чтобы 10 шло после 9)."""
    p = safe(lambda: el.LookupParameter(name))
    if p is None:
        return "none"
    if p.StorageType == DB.StorageType.String:
        return set_val(el, name, u"" if v < 0 else u"%06d" % int(v))
    return set_val(el, name, float(v))


def write_element_keys(infos, stats, cfg=None, report=None):
    """ИмяСистемы, группа (ADSK_Система_Обозначение), ранг сортировки и «материал × 100 + тип»."""
    cfg = cfg or {}
    sp, kp = sort_param(cfg), kit_param(cfg)
    c = {"ИмяСистемы": 0, "группа": 0, "сортировка": 0}
    miss = {}
    ro = {}
    for it in infos:
        el = it.el
        if set_val(el, P_SYS, it.sysraw) == "ok":
            c["ИмяСистемы"] += 1
        if it.key == "gen":
            continue
        g = it.group or u""
        if set_val(el, P_GROUP, g) == "ok":
            c["группа"] += 1
        if not it.group and (pval(el, P_POS) or u""):
            if set_val(el, P_POS, u"") == "ok":
                c["позиция очищена (не в спецификации)"] = c.get("позиция очищена (не в спецификации)", 0) + 1
        sv = it.sortv if it.group else -1
        r3 = _set_rank(el, sp, sv)
        if r3 == "none" and it.group:
            miss[it.key] = miss.get(it.key, 0) + 1
        if r3 == "ro" and it.group:
            ro[it.fam or it.key] = ro.get(it.fam or it.key, 0) + 1
        r4 = _set_rank(el, kp, it.kit if it.group else -1) if kp else "same"
        if "ok" in (r3, r4):
            c["сортировка"] += 1
    for k, v in c.items():
        stats[u"записано: " + k] = v
    if ro and report is not None:
        report.append(u"«{0}» только для чтения (формула в семействе) — порядок строк этих семейств не записан, "
                      u"уберите формулу: ".format(sp) + u"; ".join(
                          u"{0} ({1} эл.)".format(f, n) for f, n in sorted(ro.items(), key=lambda x: -x[1])))
    if miss and report is not None:
        title = dict((k, t) for k, b, t, o in D.CATS)
        report.append(u"нет параметра сортировки «{0}» — порядок строк задаёт Revit: ".format(sp) + u", ".join(
            u"{0} ({1} эл.)".format(title.get(k, k), n) for k, n in sorted(miss.items())))


def missing_sort_params(cfg, fields=None):
    """Для окна (жёлтым на «Сортировке»): категории, у которых нет параметра сортировки / комплекта / ИмяСистемы.
    fields — SFIELDS (поля, которые Revit даёт в спецификацию категории). -> {параметр: [категории]}."""
    fields = SFIELDS if fields is None else fields
    out = {}
    if not fields:
        return out
    present = set(fields.keys())
    for prm in [x for x in (sort_param(cfg), kit_param(cfg), P_SYS, P_GROUP) if x]:
        for key in present:
            names = set(f["name"] for f in fields.get(key) or []) | set(f["param"] for f in fields.get(key) or [])
            if prm not in names:
                out.setdefault(prm, []).append(key)
    return out


# ------------------------------------------------------------------
# дополнительные материалы (покраска, крепёж, прочее): одна таблица на связку групп
# ------------------------------------------------------------------
P_KEYNAME = DB.BuiltInParameter.REF_TABLE_ELEM_NAME
MAT_FIELDS = ("id", "kind", "name", "mark", "code", "maker", "unit", "mass", "base", "norm", "layers", "reserve",
              "bind", "example")


def materials_path():
    """Личный справочник: %APPDATA%\\Spec_Manager\\materials.json (не в шаблоне и не в настройках проекта)."""
    root = os.environ.get("APPDATA") or os.path.expanduser(u"~")
    folder = os.path.join(root, u"Spec_Manager")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.join(folder, u"materials.json")


def mat_norm(m):
    """Строка справочника со всеми полями (старые и неполные — дополняются)."""
    out = {"id": u"", "kind": "paint", "name": u"", "mark": u"", "code": u"", "maker": u"", "unit": u"м²",
           "mass": u"", "base": "pipe_out", "norm": 1.0, "layers": 1, "reserve": 0.0, "bind": [], "example": False}
    for k in MAT_FIELDS:
        if k in (m or {}):
            out[k] = m[k]
    try:
        out["norm"] = float(out["norm"] or 0)
    except Exception:
        out["norm"] = 0.0
    try:
        out["layers"] = max(1, int(out["layers"] or 1))
    except Exception:
        out["layers"] = 1
    try:
        out["reserve"] = float(out["reserve"] or 0)
    except Exception:
        out["reserve"] = 0.0
    if not isinstance(out["bind"], list):
        out["bind"] = [x.strip() for x in (u"%s" % out["bind"]).split(u",") if x.strip()]
    if not out["id"]:
        out["id"] = u"m%d" % int(time.time() * 1000)
    return out


def materials_std():
    import copy
    return [mat_norm(m) for m in copy.deepcopy(D.MATERIALS_STD)]


def migrate_layers(cfg):
    """Слои покраски прежних настроек проекта (cfg["paint"]["layers"]) -> строки справочника."""
    pc = cfg.get("paint") if isinstance(cfg.get("paint"), dict) else {}
    out = []
    res = float(pc.get("reserve") or 0)
    for n, l in enumerate(pc.get("layers") or []):
        unit = l.get("unit") or u"м²"
        surf = l.get("surface") or "out"
        m = {"id": u"old%d" % n, "kind": "paint",
             "name": l.get("name") or u"", "mark": l.get("mark") or u"", "unit": unit,
             "base": "pipe_in" if surf == "in" else "pipe_out",
             "norm": 1.0 if unit == u"м²" else float(l.get("rate") or 0), "layers": 1, "reserve": res,
             "bind": [], "example": False}
        out.append(mat_norm(m))
    return out


def load_materials(cfg=None):
    """-> строки справочника. Нет файла — стандартный набор (+ слои покраски прежних настроек проекта)."""
    path = materials_path()
    if os.path.isfile(path):
        try:
            data = _read_json(path)
            items = data.get("items") if isinstance(data, dict) else data
            return [mat_norm(m) for m in items or []]
        except Exception:
            pass
    items = materials_std()
    if cfg is not None:
        have = set((m["name"], m["unit"], m["base"]) for m in items)
        for m in migrate_layers(cfg):
            if (m["name"], m["unit"], m["base"]) not in have:
                items.append(m)
    return items


def save_materials(items):
    return _write_json({"version": 1, "items": [mat_norm(m) for m in items]}, materials_path())


def export_materials_xlsx(items, path):
    """Экспорт справочника в XLSX (простая книга без внешних библиотек)."""
    import zipfile
    from xml.sax.saxutils import escape
    bases = dict((k, t) for k, t, u in D.MAT_BASES)
    kinds = dict(D.MAT_KINDS)
    head = [u"Вид", u"Наименование", u"Марка / ГОСТ", u"Код", u"Завод", u"Ед.", u"Масса", u"Основание",
            u"Норма", u"Слоёв", u"Запас, %", u"Привязка", u"Норма — пример"]
    rows = [head]
    for m in items:
        m = mat_norm(m)
        rows.append([kinds.get(m["kind"], m["kind"]), m["name"], m["mark"], m["code"], m["maker"], m["unit"],
                     m["mass"], bases.get(m["base"], m["base"]), m["norm"], m["layers"], m["reserve"],
                     u", ".join(m["bind"]), u"да" if m["example"] else u""])

    def col(i):
        s_ = u""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s_ = u"ABCDEFGHIJKLMNOPQRSTUVWXYZ"[r] + s_
        return s_
    xr = []
    for ri, r in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(r):
            ref = u"%s%d" % (col(ci), ri)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(u'<c r="%s"><v>%s</v></c>' % (ref, repr(float(v))))
            else:
                cells.append(u'<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(u"%s" % v)))
        xr.append(u'<row r="%d">%s</row>' % (ri, u"".join(cells)))
    sheet = (u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             u'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             u'<sheetData>%s</sheetData></worksheet>') % u"".join(xr)
    files = {
        "[Content_Types].xml": u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Материалы" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": u'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    try:
        for name, txt in files.items():
            z.writestr(name, txt.encode("utf-8"))
    finally:
        z.close()
    return path


def link_sets(groups):
    """Связки: подряд идущие группы с одним id связки -> [[индексы]]; группа без связки — своя."""
    out = []
    for i, g in enumerate(groups):
        lk = g.get("link")
        if out and lk and groups[out[-1][-1]].get("link") == lk:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def link_label(groups, idxs):
    names = [groups[i]["name"] for i in idxs]
    if len(names) <= 2:
        return u", ".join(names)
    return u"{0}–{1}".format(names[0], names[-1])


def _pipe_paint(it):
    """Наружный и внутренний Ø (мм), длина (м) — один раз на трубу."""
    d = getattr(it, "_paint", None)
    if d is not None:
        return d
    el = it.el
    od = pipe_od(el) or it.diam or 0.0
    idm = safe(lambda: el.get_Parameter(DB.BuiltInParameter.RBS_PIPE_INNER_DIAM_PARAM).AsDouble() * FT, 0.0) or 0.0
    lm = safe(lambda: el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() * FT / 1000.0, 0.0) or 0.0
    d = {"od": od, "id": idm or od, "len": lm}
    it._paint = d
    return d


def _duct_area(it):
    """Площадь воздуховода, м² (его собственный параметр Revit)."""
    a = getattr(it, "_area", None)
    if a is None:
        a = safe(lambda: it.el.get_Parameter(DB.BuiltInParameter.RBS_CURVE_SURFACE_AREA).AsDouble() * FT * FT / 1e6, 0.0) or 0.0
        it._area = a
    return a


def _bound_names(it, order):
    o = order.get(it.key) or {}
    names = []
    mats = o.get("materials") or []
    types = o.get("types") or []
    if 0 <= getattr(it, "mat", -1) < len(mats):
        names.append(mats[it.mat].get("name") or u"")
    if 0 <= getattr(it, "tp", -1) < len(types):
        names.append(types[it.tp].get("name") or u"")
    return names


def mat_base(m, pipes, ducts, order):
    """База расчёта строки по трубам / воздуховодам связки -> (количество базы, число элементов)."""
    base = m.get("base") or "pipe_out"
    bind = [b.lower() for b in m.get("bind") or []]
    lst = ducts if base.startswith("duct") else pipes
    tot, n = 0.0, 0
    for it in lst:
        if bind:
            have = [x.lower() for x in _bound_names(it, order)]
            if not any(b in have for b in bind):
                continue
        if base.startswith("duct"):
            v = _duct_area(it)
        else:
            d = _pipe_paint(it)
            if base == "pipe_len":
                v = d["len"]
            elif base == "pipe_in":
                v = math.pi * d["id"] / 1000.0 * d["len"]
            else:
                v = math.pi * d["od"] / 1000.0 * d["len"]
        if v > 0:
            tot += v
            n += 1
    return tot, n


def mat_note(m):
    parts = []
    if m["layers"] > 1:
        parts.append(u"{0} слоя".format(m["layers"]) if m["layers"] < 5 else u"{0} слоёв".format(m["layers"]))
    if m["reserve"]:
        parts.append(u"запас {0:g} %".format(m["reserve"]))
    return u", ".join(parts)


def mat_rows(infos, cfg, items, run_ids, group_of=None):
    """{кортеж индексов групп связки: [строки]} по отмеченным строкам справочника.
    group_of(it) -> имя группы (для окна); по умолчанию it.group (после assign_groups)."""
    out = {}
    run = set(run_ids or [])
    items = [mat_norm(m) for m in items or [] if m.get("id") in run]
    if not items:
        return out
    order = cfg.get("order") or default_order(cfg)
    groups = cfg.get("groups") or []
    gi = dict((g["name"], i) for i, g in enumerate(groups))
    pipes, ducts = {}, {}
    for it in infos:
        if it.key not in ("pipe", "duct"):
            continue
        g = group_of(it) if group_of is not None else (None if it.hidden else it.group)
        if g in gi:
            (pipes if it.key == "pipe" else ducts).setdefault(gi[g], []).append(it)
    digits = int(cfg.get("mat_digits", D.MAT_DIGITS))
    for idxs in link_sets(groups):
        ps = [x for i in idxs for x in pipes.get(i, [])]
        ds = [x for i in idxs for x in ducts.get(i, [])]
        rows = []
        for m in items:
            b, n = mat_base(m, ps, ds, order)
            if b <= 0:
                continue
            q = b * m["norm"] * m["layers"] * (1.0 + m["reserve"] / 100.0)
            if q <= 0:
                continue
            rows.append({"id": m["id"], "name": m["name"], "mark": m["mark"], "code": m["code"], "maker": m["maker"],
                         "unit": m["unit"], "mass": m["mass"], "qty": round(q, digits), "note": mat_note(m),
                         "base": round(b, 2), "n": n, "example": bool(m["example"])})
        if rows:
            out[tuple(idxs)] = rows
    return out


def mat_preview(infos, cfg, items, run_ids):
    """Для окна: то же, что посчитает кнопка, без записи. -> [(подпись связки, строки)]."""
    import copy
    c = dict(cfg)
    c["_mat_run"] = list(run_ids or [])
    groups = cfg.get("groups") or []
    res = _mat_preview_raw(infos, c, items)
    return [(link_label(groups, list(k)), v) for k, v in sorted(res.items())]


def find_paint_sample():
    """Прежняя ключевая спецификация «О_Материалы» (необязательна): её ручные строки добавляются к своей связке."""
    best = None
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.IsTemplate or not safe(lambda: vs.Definition.IsKeySchedule, False):
            continue
        nm = (vs.Name or u"").strip()
        if nm in D.PAINT_SAMPLE:
            return vs
        if best is None and any(nm.startswith(x) for x in D.PAINT_SAMPLE):
            best = vs
    return best


def key_rows(vs):
    """Строки ключевой спецификации (элементы-ключи) по порядку имени ключа."""
    els = safe(lambda: list(DB.FilteredElementCollector(doc, vs.Id).ToElements()), []) or []
    els = [e for e in els if not isinstance(e, DB.ElementType)]
    return sorted(els, key=lambda e: nat_key(safe(lambda: e.get_Parameter(P_KEYNAME).AsString()) or u""))


def _field_list(d):
    return [d.GetField(i) for i in range(d.GetFieldCount())]


FIELD_PROPS = ("ColumnHeading", "HeadingOrientation", "HorizontalAlignment", "GridColumnWidth", "SheetColumnWidth")
VIEW_PROPS = ("TitleTextTypeId", "HeaderTextTypeId", "BodyTextTypeId", "HasStripedRows")


def _copy_props(src, dst, names):
    for n in names:
        try:
            v = getattr(src, n)
            if getattr(dst, n) != v:
                setattr(dst, n, v)
        except Exception:
            pass


def manual_mat_rows(sample, names):
    """Ручные строки «О_Материалы» групп names (ADSK_Система_Обозначение = имя группы) -> [строки]."""
    if sample is None:
        return []
    fnames = [safe(lambda: f.GetName()) or u"" for f in _field_list(sample.Definition)]
    fm = {}
    for k, cands in D.PAINT_FIELDS.items():
        for c in cands:
            if c in fnames:
                fm[k] = c
                break
    gcol = fm.get("group")
    out = []
    for el in key_rows(sample):
        g = (pval(el, gcol) or u"").strip() if gcol else u""
        if not g or g not in names:
            continue
        row = {"manual": True}
        for k in ("name", "mark", "code", "maker", "unit", "mass", "note"):
            v = pval(el, fm[k]) if k in fm else None
            row[k] = u"" if v is None else (u"%g" % v if isinstance(v, float) else u"%s" % v)
        q = pval(el, fm["qty"]) if "qty" in fm else None
        row["qty"] = num(q) if q not in (None, u"") else u""
        out.append(row)
    return out


def _thin_line_style():
    try:
        cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
        for sc in cat.SubCategories:
            nm = (sc.Name or u"").strip(u"<> ").lower()
            if nm in (u"тонкие линии", u"thin lines"):
                return sc.GetGraphicsStyle(DB.GraphicsStyleType.Projection).Id
    except Exception:
        pass
    return None


def _grid_style(base, line_id, halign=None):
    """Стиль ячейки «Заголовка» с рамкой со всех сторон (как сетка спецификации)."""
    st = DB.TableCellStyle(base) if base is not None else DB.TableCellStyle()
    opt = safe(lambda: st.GetCellStyleOverrideOptions()) or DB.TableCellStyleOverrideOptions()
    if line_id is not None:
        for nm in ("BorderTopLineStyle", "BorderBottomLineStyle", "BorderLeftLineStyle", "BorderRightLineStyle"):
            safe(lambda: setattr(st, nm, line_id))
        for nm in ("BorderTopLineStyle", "BorderBottomLineStyle", "BorderLeftLineStyle", "BorderRightLineStyle"):
            safe(lambda: setattr(opt, nm, True))
    if halign is not None:
        safe(lambda: setattr(st, "FontHorizontalAlignment", halign))
        safe(lambda: setattr(opt, "HorizontalAlignment", True))
    safe(lambda: st.SetCellStyleOverrideOptions(opt))
    return st


MAT_QTY_FIELDS = (u"Длина", u"Length", u"Число", u"Count", u"ADSK_Количество")


def _mat_columns(src):
    """Видимые столбцы образца: [(поле, ключ столбца или None)]."""
    d = src.Definition
    vis = [f for f in _field_list(d) if not safe(lambda: f.IsHidden, False)]
    out, used = [], set()
    for f in vis:
        nm = safe(lambda: f.GetName()) or u""
        head = (safe(lambda: f.ColumnHeading) or nm).lower()
        key = None
        for k, fields, words in D.MAT_COLUMNS:
            if k not in used and nm in fields:
                key = k
                break
        if key is None and "qty" not in used and (nm in MAT_QTY_FIELDS or safe(
                lambda: f.FieldType == DB.ScheduleFieldType.Count, False)):
            key = "qty"                 # 0.17.0: у труб графа количества — «Длина» (было: количество не выводилось)
        if key is None:
            for k, fields, words in D.MAT_COLUMNS:
                if k not in used and any(w in head for w in words):
                    key = k
                    break
        if key:
            used.add(key)
        out.append((f, key))
    return out


MAT_KEYS = [k for k, f_, w_ in D.MAT_COLUMNS]       # графы таблицы материалов по порядку (ГОСТ 21.601, форма 1)


def find_mat_template():
    """Шаблон таблицы материалов пользователя: спецификация «Комплекты мебели», имя «О_…» со словом «материал»
    (не ключевая). Нет — None (таблица строится сама)."""
    b = bic(D.PAINT_CATEGORY)
    if b is None:
        return None
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.IsTemplate or safe(lambda: vs.Definition.IsKeySchedule, False):
            continue
        nm = (vs.Name or u"").strip()
        if not (nm.startswith(u"О_") or nm.startswith(u"O_")) or u"материал" not in nm.lower():
            continue
        if id_int(vs.Definition.CategoryId) == int(b):
            return vs
    return None


MAT_LEFT = ("name",)        # графы таблицы материалов с выравниванием влево
MAT_ROW_FONT_MM = 2.5       # шрифт строк материалов, мм (решение 12.10.2026: название 3,5, строки 2,5)


def mat_rows_font(vs, src, rows_at, notes):
    """0.15.1: строки материалов стоят в «Заголовке» и брали его шрифт (3,5 мм) — каждой ячейке этих строк шрифт
    MAT_ROW_FONT_MM; выравнивание и рамки ячейки не меняются. Перевод мм -> TextSize — по телу src (спецификация
    связки), иначе по самой таблице."""
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or not rows_at:
        return
    k, ok = text_size_k(src) if src is not None else (None, False)
    if not ok:
        k, ok = text_size_k(vs)
    if not ok:
        notes.append(u"шрифт строк материалов: единицы не сверены по телу таблицы, записан в пунктах")
    size = MAT_ROW_FONT_MM * k
    c0 = hd.FirstColumnNumber
    err = None
    for r in rows_at:
        for c in range(hd.NumberOfColumns):
            try:
                base = safe(lambda: hd.GetTableCellStyle(r, c0 + c))
                st = DB.TableCellStyle(base) if base is not None else DB.TableCellStyle()
                opt = safe(lambda: st.GetCellStyleOverrideOptions()) or DB.TableCellStyleOverrideOptions()
                st.TextSize = size
                opt.FontSize = True
                st.SetCellStyleOverrideOptions(opt)
                hd.SetCellStyle(r, c0 + c, st)
            except Exception as ex:
                err = err or ex
    if err is not None:
        notes.append(u"шрифт строк материалов записался не полностью: {0}".format(err))


def _left_style(base):
    """Копия стиля ячейки с выравниванием текста влево."""
    st = DB.TableCellStyle(base) if base is not None else DB.TableCellStyle()
    opt = safe(lambda: st.GetCellStyleOverrideOptions()) or DB.TableCellStyleOverrideOptions()
    safe(lambda: setattr(st, "FontHorizontalAlignment", DB.HorizontalAlignmentStyle.Left))
    safe(lambda: setattr(opt, "HorizontalAlignment", True))
    safe(lambda: st.SetCellStyleOverrideOptions(opt))
    return st


def _unmerge(hd, r, c):
    """Ячейка «Заголовка» — отдельно (новая строка наследует объединение строки названия)."""
    mc = safe(lambda: hd.GetMergedCell(r, c))
    if mc is not None and (mc.Left != mc.Right or mc.Top != mc.Bottom):
        safe(lambda: hd.SetMergedCell(r, c, DB.TableMergedCell(r, c, r, c)))


def _fill_mat_header(vs, rows, notes, row_h=None, styles=None, keys=None):
    """Строки материалов в разделе «Заголовок» под строкой названия: число строк = числу материалов, каждая ячейка
    разъединена, графы по keys (по умолчанию MAT_KEYS — порядок ГОСТ). Стиль и высота — с первой строки под
    названием (шаблон) или styles/row_h.
    -> (строки заголовка с материалами, столбец позиции)."""
    hd = vs.GetTableData().GetSectionData(DB.SectionType.Header)
    r_title, c0, ncol = hd.FirstRowNumber, hd.FirstColumnNumber, hd.NumberOfColumns
    keys = list(keys or MAT_KEYS)
    if hd.NumberOfRows > 1:
        r1 = r_title + 1
        styles = [safe(lambda: hd.GetTableCellStyle(r1, c0 + c)) for c in range(ncol)]
        row_h = safe(lambda: hd.GetRowHeight(r1)) or row_h
    while hd.NumberOfRows - 1 > len(rows):
        hd.RemoveRow(hd.LastRowNumber)
    while hd.NumberOfRows - 1 < len(rows):
        r = hd.LastRowNumber + 1
        hd.InsertRow(r)
    rows_at = []
    for k, row in enumerate(rows):
        r = r_title + 1 + k
        if row_h:
            safe(lambda: hd.SetRowHeight(r, row_h))
        for c in range(ncol):
            _unmerge(hd, r, c0 + c)
            key = keys[c] if c < len(keys) else None
            st = styles[c] if styles and c < len(styles) else None
            if key in MAT_LEFT:                              # наименование — слева (замечание пользователя)
                st = _left_style(st if st is not None else safe(lambda: hd.GetTableCellStyle(r, c0 + c)))
            if st is not None:
                safe(lambda: hd.SetCellStyle(r, c0 + c, st))
            txt = _mat_cell(row, key)
            try:
                hd.SetCellText(r, c0 + c, txt)
            except Exception as ex:
                notes.append(u"текст в ячейку не записался: {0}".format(ex))
        rows_at.append(r)
    if ncol < len([k for k in keys if k]):
        notes.append(u"в таблице материалов {0} граф вместо {1} — часть граф не выведена".format(ncol, len(keys)))
    pos = keys.index("pos") if "pos" in keys and keys.index("pos") < ncol else None
    return rows_at, (c0 + pos) if pos is not None else None


def _mat_hide_all(vs, notes):
    """Тело таблицы — пустое: фильтр по текстовому полю, которого нет ни у одного элемента."""
    d = vs.Definition
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        try:
            d.AddFilter(DB.ScheduleFilter(f.FieldId, DB.ScheduleFilterType.Equal, u"~нет строк~"))
            return True
        except Exception:
            continue
    for x in d.GetSchedulableFields():               # у поля шаблона («Тип») текстового фильтра нет — скрытое поле
        if x.FieldType != DB.ScheduleFieldType.Instance or (safe(lambda: x.GetName(doc)) or u"") not in (
                u"Комментарии", u"Comments", u"Марка", u"Mark"):
            continue
        try:
            f = d.AddField(x)
            d.AddFilter(DB.ScheduleFilter(f.FieldId, DB.ScheduleFilterType.Equal, u"~нет строк~"))
            f.IsHidden = True
            return True
        except Exception as ex:
            notes.append(u"фильтр по «{0}»: {1}".format(safe(lambda: x.GetName(doc)), ex))
            continue
    notes.append(u"фильтр «нет строк» не задался — если в модели есть «Комплекты мебели», они попадут в таблицу")
    return False


def create_mat_schedule(src, name, rows, notes, tpl=None):
    """Таблица материалов: копия шаблона пользователя tpl («О_…материал…», «Комплекты мебели») или, без шаблона,
    спецификация «Комплекты мебели» с одним полем и 9 графами в «Заголовке» (ширины — как у граф src, спецификации
    трубопроводов связки). Строки материалов — текстом под строкой названия, без строки шапки граф.
    -> (vs, [ряд строки в заголовке], столбец позиции)."""
    if tpl is not None:
        vs = doc.GetElement(tpl.Duplicate(DB.ViewDuplicateOption.Duplicate))
        d = vs.Definition
        if d.GetFilterCount() == 0:
            _mat_hide_all(vs, notes)
        rows_at, pos_col = _fill_mat_header(vs, rows, notes)
        return vs, rows_at, pos_col
    b = bic(D.PAINT_CATEGORY)
    vs = DB.ViewSchedule.CreateSchedule(doc, DB.ElementId(b))
    d = vs.Definition
    mc = _mat_columns(src)
    cols = [f for f, key in mc]
    keys = [key for f, key in mc] or MAT_KEYS
    widths = [safe(lambda: f.SheetColumnWidth) or L.ft(20.0) for f in cols] or [L.ft(395.0)]
    one = None
    for x in d.GetSchedulableFields():
        if x.FieldType == DB.ScheduleFieldType.Instance and (safe(lambda: x.GetName(doc)) or u"") in (
                u"Комментарии", u"Comments", u"Марка", u"Mark"):
            one = x
            break
    if one is None:
        one = next((x for x in d.GetSchedulableFields() if x.FieldType == DB.ScheduleFieldType.Instance), None)
    if one is not None:
        f = d.AddField(one)
        safe(lambda: setattr(f, "SheetColumnWidth", sum(widths)))
        safe(lambda: setattr(f, "ColumnHeading", u"Позиция"))
        _mat_hide_all(vs, notes)
    safe(lambda: setattr(d, "ShowHeaders", False))
    safe(lambda: setattr(d, "ShowGrandTotal", False))
    safe(lambda: setattr(d, "IsItemized", True))
    safe(lambda: setattr(d, "ShowTitle", True))
    _copy_props(src, vs, VIEW_PROPS)
    hd = vs.GetTableData().GetSectionData(DB.SectionType.Header)
    hs = src.GetTableData().GetSectionData(DB.SectionType.Header)
    bs = src.GetTableData().GetSectionData(DB.SectionType.Body)
    c0 = hd.FirstColumnNumber
    while hd.NumberOfColumns < len(widths):              # графы «Заголовка» не зависят от полей тела
        hd.InsertColumn(hd.LastColumnNumber + 1)
    for c, w in enumerate(widths):
        safe(lambda: hd.SetColumnWidth(c0 + c, w))
    r_title = hd.FirstRowNumber
    safe(lambda: hd.SetRowHeight(r_title, hs.GetRowHeight(hs.FirstRowNumber)))
    if hd.NumberOfColumns > 1:
        safe(lambda: hd.MergeCells(DB.TableMergedCell(r_title, c0, r_title, hd.LastColumnNumber)))
    head_style = safe(lambda: bs.GetTableCellStyle(bs.FirstRowNumber, bs.FirstColumnNumber))
    body_style = safe(lambda: bs.GetTableCellStyle(bs.FirstRowNumber + 1, bs.FirstColumnNumber)) or head_style
    data_h = L.ft(L.ROW_MM) if L.ROW_MM else safe(lambda: bs.GetRowHeight(bs.FirstRowNumber + 1))
    line = _thin_line_style()
    styles = []
    for c, f in enumerate(cols or [None] * len(widths)):
        ha = safe(lambda: f.HorizontalAlignment) if f is not None else None
        hal = {DB.ScheduleHorizontalAlignment.Left: DB.HorizontalAlignmentStyle.Left,
               DB.ScheduleHorizontalAlignment.Right: DB.HorizontalAlignmentStyle.Right}.get(
            ha, DB.HorizontalAlignmentStyle.Center) if ha is not None else None
        styles.append(_grid_style(body_style, line, hal))
    rows_at, pos_col = _fill_mat_header(vs, rows, notes, data_h, styles, keys)
    return vs, rows_at, pos_col


def _mat_cell(row, key):
    if not key or key == "pos":
        return u""
    v = row.get(key)
    if v is None or v == u"":
        return u""
    if key == "qty" and isinstance(v, (int, float)):
        return (u"%g" % v).replace(u".", u",")
    return u"%s" % v


def make_mat_specs(cfg, mats, specs, report):
    """Таблицы материалов по связкам (внутри транзакции): после последней спецификации связки. -> [Spec]."""
    groups = cfg.get("groups") or []
    sample = safe(find_paint_sample)
    tpl = safe(find_mat_template)
    if tpl is not None:
        report.append(u"материалы: таблица по шаблону «{0}»".format(tpl.Name))
    out = []
    examples = set()
    for idxs in link_sets(groups):
        names = [groups[i]["name"] for i in idxs]
        rows = list(mats.get(tuple(idxs)) or [])
        rows += manual_mat_rows(sample, names)
        if not rows:
            continue
        mine = [sp for sp in specs if sp.group["name"] in names]
        src = None
        for nm in reversed(names):
            src = next((sp.vs for sp in mine if sp.group["name"] == nm and sp.key == "pipe"), None)
            if src is not None:
                break
        if src is None and mine:
            src = mine[-1].vs
        label = link_label(groups, idxs)
        if src is None:
            report.append(u"материалы связки {0}: нет спецификаций связки — таблица не создана".format(label))
            continue
        last = groups[idxs[-1]]
        sp = Spec(last, "mat", D.MAT_TITLE, src)
        sp.label = label
        sp.items = []
        sp.whole = True
        try:
            sp.vs, sp.rows_at, sp.pos_col = create_mat_schedule(src, label, rows, sp.notes, tpl)
            mat_rows_font(sp.vs, src, sp.rows_at, sp.notes)
            set_val(sp.vs, P_PURPOSE, D.SPEC_PURPOSE.format(label))
        except Exception as ex:
            report.append(u"материалы связки {0}: таблица не создана — {1}".format(label, ex))
            if sp.vs is not None:
                safe(lambda: doc.Delete(sp.vs.Id))
            continue
        sp.rows = rows
        sp.count = len(rows)
        man = sum(1 for r in rows if r.get("manual"))
        if man:
            sp.notes.append(u"ручных строк из «{0}»: {1}".format(sample.Name, man))
        examples.update(r["name"] for r in rows if r.get("example"))
        out.append(sp)
    if examples:
        report.append(u"материалы: нормы расхода — примеры, уточните по паспорту / проекту: " +
                      u"; ".join(sorted(examples)))
    return out


def fill_mat_positions(sp, values):
    """Номера позиций — текстом в столбец «Поз.» строк таблицы материалов."""
    if getattr(sp, "pos_col", None) is None:
        sp.notes.append(u"нет столбца позиции — номера не записаны")
        return
    hd = sp.vs.GetTableData().GetSectionData(DB.SectionType.Header)
    for r, v in zip(sp.rows_at, values):
        safe(lambda: hd.SetCellText(r, sp.pos_col, v))


# ------------------------------------------------------------------
# настройки по умолчанию + сохранённые
# ------------------------------------------------------------------
def fit_groups(groups, systems, skip=None):
    """Группы из настроек — под единицы модели: чужие убрать, пустые группы убрать, новые — в свои группы.
    skip — исключённые единицы (skip_units): из групп убираются и сами не возвращаются."""
    skip = set(skip or [])
    names = [s[0] for s in systems if s[0] not in skip]
    groups = groups or []
    if not groups:
        return default_groups(systems, skip)
    used = set()
    for g in groups:
        g["systems"] = [s for s in g.get("systems", []) if s in names]
        used.update(g["systems"])
    groups = [g for g in groups if g["systems"]]
    rest = [s for s in systems if s[0] not in used and s[0] not in skip]
    if rest:
        by_name = dict((g["name"], g) for g in groups)
        for ng in default_groups(rest, skip):      # новое — в группу с тем же именем, если она есть (имя = фильтр)
            if ng["name"] in by_name:
                by_name[ng["name"]]["systems"].extend(ng["systems"])
            else:
                groups.append(ng)
                by_name[ng["name"]] = ng
    return groups


def regroup(infos, cfg, progress=None):
    """Единицы группировки по cfg["group_by"] / ["group_fallback"] (после выбора раздела проекта) -> список
    единиц для вкладки «Системы». Группы прежнего режима откладываются в cfg["groups_by"] и возвращаются при
    обратной смене (ВК ↔ ОВ не теряет настроенные группы)."""
    import copy
    gb = "grouping" if cfg.get("group_by") == "grouping" else "systems"
    prev = cfg.get("units_gb") or "systems"
    set_moves(cfg.get("moves"))
    set_units(infos, gb, cfg.get("group_fallback", True) is not False, progress)
    units = found_systems(infos, AMAP)
    if prev != gb:
        stash = cfg.setdefault("groups_by", {})
        stash[prev] = cfg.get("groups") or []
        cfg["groups"] = copy.deepcopy(stash.get(gb) or [])
    cfg["units_gb"] = gb
    cfg["groups"] = fit_groups(cfg.get("groups"), units, cfg.get("skip_units"))
    return units


def full_cfg(saved, systems, infos):
    import copy
    cfg = copy.deepcopy(saved or {})
    cfg.setdefault("skip_units", [])
    cfg["groups"] = fit_groups(cfg.get("groups"), systems, cfg["skip_units"])
    cfg["units_gb"] = GROUP_BY[0]
    if "hidden" not in cfg:
        cfg["hidden"] = default_hidden(infos)
    order = cfg.get("order") or {}
    # недостающие категории — из набора раздела (ВК / ОВ); сохранённые в проекте не трогаются. Подставленное
    # запоминается в _order_auto: раздел выберут позже (новый проект) — apply_disc_order заменит только его
    auto = {}
    for k, v in default_order(cfg).items():
        if k not in order:
            order[k] = copy.deepcopy(v)
            auto[k] = copy.deepcopy(v)
    cfg["_order_auto"] = auto
    # изоляция: типы изоляции из модели — в «Не распределено» на вкладке 3, перетаскиваются в строки
    eq = order.get("equip") or {}
    if not any("sysnum" in t for t in eq.get("types") or []):
        for t in eq.get("types") or []:          # старые настройки: насосы — по признаку «насос»
            if any(k.lower() in D.PUMP_KEYS for k in t.get("keys") or []):
                t["sysnum"] = True
    cfg["order"] = order
    cfg.setdefault("order_on", D.ORDER_ON)
    cfg.setdefault("order_off", [])
    cfg.setdefault("order_cats_on", [])
    if not cfg.get("sort"):
        cfg["sort"] = {"common": copy.deepcopy(D.SORT_FIELDS)}
    migrate_cfg(cfg)
    pos = cfg.setdefault("pos", {})
    if cfg.get("group_by") == "grouping" and not cfg.get("_pos020"):
        pos["mode"] = "group_prefix"     # ОВ: позиция с номером группы (СВОДКА, раздел про профиль ОВ; 0.20.0)
        cfg["_pos020"] = True
    pos["mode"] = pos_mode(cfg)
    pos.setdefault("sysnum_fmt", D.SYSNUM_FMT)
    cfg.setdefault("qty_min", D.QTY_MIN)
    cfg.setdefault("qty_hide", [])
    cfg.setdefault("kit_order", {})
    cfg.setdefault("registry", [])
    cfg.setdefault("sort_param", D.SORT_PARAM)
    cfg.setdefault("kit_param", D.KIT_PARAM)
    layout_cfg(cfg)
    return cfg


def migrate_cfg(cfg):
    """Настройки версий до 0.4.0: ADSK_Система_Имя → ИмяСистемы (скрытая сортировка), «Начиная с номера» →
    режим с префиксом, «оставить строку ≤ порога» → «скрыть строку < порога» (по умолчанию ничего не скрыто)."""
    for g in cfg.get("groups") or []:
        if g.get("split") == P_MAIN:
            g["split"] = P_SYS
    srt = cfg.get("sort") or {}
    for k in list(srt.keys()):
        rows = [r for r in srt[k] or [] if r.get("param") not in SYS_ROWS]
        srt[k] = rows
    import copy
    if not srt.get("common"):
        srt["common"] = copy.deepcopy(D.SORT_FIELDS)
    if not cfg.get("_sort018"):
        # 0.18.0: строки окна идут в Revit; черновики категорий, сохранённые без правок, — на базовый набор
        # (Комплект → Сортировка → Наименование → Марка → Код). Изменённые пользователем не трогаются.
        for k, old in (getattr(D, "SORT_DRAFTS_OLD", None) or {}).items():
            rows = srt.get(k)
            if rows and tuple(r.get("param") for r in rows if r.get("on")) == tuple(old) and k in D.SORT_DRAFTS:
                srt[k] = copy.deepcopy(D.SORT_DRAFTS[k])
        cfg["_sort018"] = True
    lo = cfg.get("layout")
    if isinstance(lo, dict) and lo.get("num_mode") == "from":
        lo["num_mode"] = "prefix"
    cfg.pop("qty_keep", None)
    if isinstance(lo, dict) and lo.get("sys_row_mm") == 12.0 and not cfg.get("_sys8"):
        lo["sys_row_mm"] = 8.0            # решение 10.10: строка названия системы — 8 мм
        cfg["_sys8"] = True


def layout_cfg(cfg):
    import copy
    lo = cfg.get("layout")
    if not isinstance(lo, dict):
        lo = copy.deepcopy(D.LAYOUT)
        cfg["layout"] = lo
    for k, v in D.LAYOUT.items():
        lo.setdefault(k, v)
    return lo


# ------------------------------------------------------------------
# шаблоны настроек (для типовых зданий / других проектов)
# ------------------------------------------------------------------
PRESET_KEYS = ("groups", "hidden", "order", "order_on", "order_off", "order_cats_on", "sort", "sort_param",
               "kit_param", "pos", "qty_min", "kit_order", "delete_empty_sheets", "layout",
               "mode", "sections", "sec_assign", "main_types", "skip_units")


def presets_dir():
    folder = os.path.join(EXT_ROOT, u"_presets")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def _fname(name):
    return re.sub(u"[\\\\/:*?\"<>|]+", u"_", (name or u"").strip()) or u"шаблон"


def _read_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _write_json(obj, path):
    txt = json.dumps(obj, ensure_ascii=False, indent=1)
    if not isinstance(txt, type(u"")):
        txt = txt.decode("utf-8")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    return path


def list_presets():
    """[(имя, путь, для новых проектов)]"""
    out = []
    folder = presets_dir()
    for fn in sorted(os.listdir(folder), key=lambda x: x.lower()):
        if not fn.lower().endswith(u".json"):
            continue
        path = os.path.join(folder, fn)
        try:
            pr = _read_json(path)
        except Exception:
            continue
        out.append((pr.get("name") or fn[:-5], path, bool(pr.get("for_new"))))
    return out


def preset_path(name):
    for n, path, fn in list_presets():
        if n == name:
            return path
    return os.path.join(presets_dir(), _fname(name) + u".json")


def make_preset(cfg, name, for_new=False):
    import copy
    import datetime
    return {"name": name, "version": 1, "for_new": bool(for_new),
            "saved": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": safe(lambda: doc.Title) or u"",
            "settings": dict((k, copy.deepcopy(cfg[k])) for k in PRESET_KEYS if k in cfg)}


def save_preset(cfg, name, for_new=False):
    path = preset_path(name)
    if for_new:
        set_preset_for_new(None)
    return _write_json(make_preset(cfg, name, for_new), path)


def load_preset(name_or_path):
    path = name_or_path if os.path.isfile(name_or_path) else preset_path(name_or_path)
    pr = _read_json(path)
    if "settings" not in pr:                       # файл настроек проекта — тоже годится
        pr = {"name": os.path.splitext(os.path.basename(path))[0], "settings":
              dict((k, pr[k]) for k in PRESET_KEYS if k in pr)}
    return pr


def delete_preset(name):
    path = preset_path(name)
    if os.path.isfile(path):
        os.remove(path)


def set_preset_for_new(name):
    """Отметить шаблон «для новых проектов» (None — снять со всех)."""
    for n, path, fn in list_presets():
        want = (n == name)
        if fn != want:
            pr = _read_json(path)
            pr["for_new"] = want
            _write_json(pr, path)


def export_preset(name, path):
    return _write_json(load_preset(name), path)


def import_preset(path):
    pr = load_preset(path)
    name = pr.get("name") or os.path.splitext(os.path.basename(path))[0]
    base, k = name, 2
    while os.path.isfile(preset_path(name)) and os.path.normcase(preset_path(name)) != os.path.normcase(path):
        name = u"{0} ({1})".format(base, k)
        k += 1
    pr["name"] = name
    pr["for_new"] = False
    _write_json(pr, preset_path(name))
    return name


def apply_preset(cur, pr, systems, infos):
    """Настройки шаблона + список созданного этим проектом (чтобы прежние спецификации удалились)."""
    import copy
    new = copy.deepcopy(pr.get("settings") or {})
    for k in ("registry", "sheet_registry"):
        if k in cur:
            new[k] = copy.deepcopy(cur[k])
    new["_preset"] = pr.get("name") or u""
    return full_cfg(new, systems, infos)


def default_preset():
    for n, path, fn in list_presets():
        if fn:
            try:
                return load_preset(path)
            except Exception:
                return None
    return None


def load_timing(d):
    """Замеры прошлых запусков (для оценки «осталось ≈»): {"read": [...], "build": [...]}."""
    try:
        set_doc(d)
        return (load_cfg() or {}).get("timing") or {}
    except Exception:
        return {}


def prepare(d, progress=None):
    """Для окон: элементы, системы, настройки. progress(этап, i, n) — окно хода работы (READ_STAGES)."""
    global SFIELDS, AMAP
    _timing_start(progress)
    set_doc(d)
    _p(0)
    detect_categories()
    amap = system_abbr_map()
    AMAP = amap
    _p(1)
    infos = collect(lambda i, n: _p(1, i, n))
    _p(2)
    safe(lambda: mark_zero_qty(infos))
    saved = load_cfg()
    # единицы групп — как в прошлый раз (ОВ — по ADSK_Группирование); раздел проекта может сменить их (regroup)
    sv = saved or {}
    set_moves(sv.get("moves"))
    set_units(infos, sv.get("units_gb") or sv.get("group_by") or "systems", sv.get("group_fallback", True) is not False)
    systems = found_systems(infos, amap)
    if not saved:                                   # проект без настроек — шаблон «для новых проектов»
        pr = safe(default_preset)
        if pr:
            cfg = apply_preset({}, pr, systems, infos)
            cfg["_preset_auto"] = True
        else:
            cfg = full_cfg(saved, systems, infos)
    else:
        cfg = full_cfg(saved, systems, infos)
    _p(3)
    SFIELDS = safe(schedulable_fields, {}) or {}
    cfg["_read_times"] = _timing_stop(len(READ_STAGES))
    return infos, systems, cfg, amap


# ------------------------------------------------------------------
# спецификации
# ------------------------------------------------------------------
def field_name(d, fid):
    f = safe(lambda: d.GetField(fid))
    return safe(lambda: f.GetName()) if f is not None else None


def find_field(d, name):
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        if safe(lambda: f.GetName()) == name:
            return f
    return None


def add_field(d, name, hidden=True):
    for sf in d.GetSchedulableFields():
        if safe(lambda: sf.GetName(doc)) == name:
            f = d.AddField(sf)
            f.IsHidden = hidden
            return f
    return None


def ensure_field(d, name):
    return find_field(d, name) or add_field(d, name)


# служебные поля систем: в форме ГОСТ 21.601 таких граф нет — в спецификации только скрытыми (сортировка, фильтр)
SERVICE_FIELDS = (u"Тип системы", u"Имя системы", P_SYS, P_GROUP, P_MAIN, u"Классификация систем")


CENTER_WORDS = (u"масса",)     # графы по центру (решение пользователя 11.10.2026: «Масса 1 ед., кг»)


def center_fields(vs):
    """Графы «Масса…» — выравнивание по центру. -> число изменённых."""
    d = vs.Definition
    n = 0
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        nm = (safe(lambda: f.GetName()) or u"").lower()
        head = (safe(lambda: f.ColumnHeading) or u"").lower()
        if f.IsHidden or not any(w in nm or w in head for w in CENTER_WORDS):
            continue
        if safe(lambda: f.HorizontalAlignment) != DB.ScheduleHorizontalAlignment.Center:
            try:
                f.HorizontalAlignment = DB.ScheduleHorizontalAlignment.Center
                n += 1
            except Exception:
                pass            # не записалось — остаётся как в шаблоне
    return n


COLUMN_MM = {P_NAME: 130.0}    # ширина графы на листе, мм (ГОСТ 21.601, форма 1: «Наименование…» — 130 мм;
                               # в шаблоне было 129,3813 — замечание пользователя 11.10.2026)


def fix_column_widths(vs):
    """Ширины граф по COLUMN_MM. Пишется ширина столбца тела (GetSectionData(Body).SetColumnWidth — она общая для
    «Заголовка» и тела), сверка — по GridColumnWidth видимого поля; если уже равны — ничего не пишется.
    -> число изменённых."""
    d = vs.Definition
    bs = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Body))
    if bs is None:
        return 0
    n = col = 0
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        if safe(lambda: f.IsHidden, False):
            continue
        k, col = col, col + 1                # номер видимой графы = номер столбца тела
        w = COLUMN_MM.get(safe(lambda: f.GetName()) or u"")
        if not w:
            continue
        cur = safe(lambda: f.GridColumnWidth)
        if cur is not None and abs(L.mm(cur) - w) < 0.01:
            continue
        try:
            bs.SetColumnWidth(bs.FirstColumnNumber + k, L.ft(w))
            n += 1
        except Exception:
            pass                # не записалось — остаётся как в шаблоне
    return n


def hide_service_fields(vs):
    """Скрыть видимые служебные поля систем (лишний столбец «Тип системы» в конце трубопроводов). -> [имена]."""
    d = vs.Definition
    out = []
    for i in range(d.GetFieldCount()):
        f = d.GetField(i)
        nm = safe(lambda: f.GetName()) or u""
        if nm in SERVICE_FIELDS and not f.IsHidden:
            try:
                f.IsHidden = True
                out.append(nm)
            except Exception:
                pass            # не скрылось — столбец останется виден, сборку не прерываем
    return out


TPL_SKIP_WORDS = (u"характеристик", u"секци")   # «О_Характеристика систем», «О_Секции радиаторов», «… СК» —
                                                # не спецификации категории (0.16.0: оборудование бралось из них)


def _tpl_rank(name, title):
    """Насколько имя шаблона подходит категории: 0 — «О_<категория>», 1 — «О_<категория> …», 2 — другое имя,
    9 — служебное («Характеристика систем», «… СК», «Секции…»)."""
    n = (name or u"").strip()[2:].strip().lower()
    t = (title or u"").strip().lower()
    if n == t:
        return 0
    if any(w in n for w in TPL_SKIP_WORDS) or n.endswith(u" ск") or u" ск " in n:
        return 9
    if n.startswith(t):
        return 1
    return 2


def find_templates():
    ids = {}
    titles = {}
    for key, bname, title, order in D.CATS:
        b = bic(bname)
        if b is not None:
            ids[int(b)] = key
            titles[key] = title
    out, spare = {}, {}
    best = {}
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.IsTemplate or L.is_revision_sched(vs):
            continue
        if safe(lambda: vs.Definition.IsKeySchedule, False):      # ключевые (напр. «О_Материалы») — не образцы
            continue
        if not (vs.Name.startswith(u"О_") or vs.Name.startswith(u"O_")):
            continue
        k = ids.get(id_int(vs.Definition.CategoryId))
        if not k:
            continue
        purpose = (pval(vs, P_PURPOSE) or u"").strip()
        if purpose in D.TEMPLATE_PURPOSES:
            tier = 0
        elif not purpose:
            tier = 1                         # «О_…» без ADSK_Назначение вида — если другого шаблона нет
        else:
            continue
        r = (tier, _tpl_rank(vs.Name, titles.get(k)), vs.Name)
        if k not in best or r < best[k][0]:
            best[k] = (r, vs)
    for k, (r, vs) in best.items():
        out[k] = vs
    return out


BLOCK_SPEC_RE = re.compile(u"^(.+?)-\\d+\\.")


def drop_block_leftovers(sec):
    """Прежние спецификации блока, которых нет в списке сборки (сборка оборвалась, список потерян): имя «<блок>-N.…»,
    ADSK_Назначение вида — как у созданных кнопкой («Спецификация …»), не на листах. Внутри транзакции. -> сколько."""
    pre = D.SPEC_PURPOSE.split(u"{")[0]
    placed = set(id_int(x.ScheduleId) for x in DB.FilteredElementCollector(doc).OfClass(DB.ScheduleSheetInstance))
    n = 0
    for vs in list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule)):
        if vs.IsTemplate or id_int(vs.Id) in placed:
            continue
        m = BLOCK_SPEC_RE.match(vs.Name or u"")
        if not m or m.group(1) != sec:
            continue
        if not (pval(vs, P_PURPOSE) or u"").startswith(pre):
            continue
        try:
            doc.Delete(vs.Id)
            n += 1
        except Exception:
            pass                        # не удалилась — останется, как раньше
    return n


def _schedulable(d, name):
    for sf in d.GetSchedulableFields():
        if safe(lambda: sf.GetName(doc)) == name and sf.FieldType == DB.ScheduleFieldType.Instance:
            return sf
    for sf in d.GetSchedulableFields():
        if safe(lambda: sf.GetName(doc)) == name:
            return sf
    return None


def create_template(key, report):
    """Шаблона категории в проекте нет — «О_ВК_<категория>» по ГОСТ 21.601 (форма 1) с полями ADSK.
    Остаётся в проекте (ADSK_Назначение вида = Трубопроводы) — его можно поправить, кнопка возьмёт его в
    следующий раз. Вызывается внутри транзакции."""
    c = cat_def(key)
    b = bic(c[1]) if c else None
    if b is None:
        return None
    vs = DB.ViewSchedule.CreateSchedule(doc, DB.ElementId(b))
    d = vs.Definition
    miss = []
    for prm, head, w in D.TEMPLATE_FIELDS:
        sf = _schedulable(d, prm)
        if sf is None:
            miss.append(prm)
            continue
        f = d.AddField(sf)
        if w:
            safe(lambda: setattr(f, "ColumnHeading", head))
            safe(lambda: setattr(f, "SheetColumnWidth", L.ft(float(w))))
        else:
            f.IsHidden = True
        if prm == P_QTY:
            safe(lambda: setattr(f, "DisplayType", DB.ScheduleFieldDisplayType.Totals))
    safe(lambda: setattr(d, "IsItemized", False))
    safe(lambda: setattr(d, "ShowGrandTotal", False))
    safe(lambda: setattr(d, "ShowTitle", True))
    safe(lambda: setattr(d, "ShowHeaders", True))
    existing = set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule))
    name, k = D.TEMPLATE_PREFIX + c[2], 2
    while name in existing:
        name = u"{0}{1} ({2})".format(D.TEMPLATE_PREFIX, c[2], k)
        k += 1
    vs.Name = name
    set_val(vs, P_PURPOSE, D.TEMPLATE_PURPOSE)
    L.set_title(vs, c[2])
    report.append(u"нет шаблона для «{0}» — создан «{1}» (ГОСТ 21.601, форма 1){2}".format(
        c[2], name, u"; нет полей: " + u", ".join(miss) if miss else u""))
    return vs


MANAGED_FILTERS = (P_SYS, u"Имя системы", P_GROUP, P_MAIN, P_QTY, u"Длина", u"Классификация систем", P_SECTION)
MAX_FILTERS = 8         # Revit 2025.4: не больше 8 фильтров у спецификации (проверено 30.10.2026)


def set_filters(vs, group, qmin, sec=None):
    """Фильтры спецификации: группа (ADSK_Система_Обозначение), блок (ADSK_Номер секции — сборка по блокам),
    «!Не учитывать». -> True | "nofield" (нет поля секции) | "full" (уже 8 фильтров)."""
    d = vs.Definition
    i = d.GetFilterCount() - 1
    while i >= 0:
        if field_name(d, d.GetFilter(i).FieldId) in MANAGED_FILTERS:
            d.RemoveFilter(i)
        i -= 1
    fg = ensure_field(d, P_GROUP)
    if fg is None:
        raise Exception(u"нет поля {0} в «{1}»".format(P_GROUP, vs.Name))
    d.AddFilter(DB.ScheduleFilter(fg.FieldId, DB.ScheduleFilterType.Equal, group))
    if sec:
        fs = ensure_field(d, P_SECTION)
        if fs is None:
            return "nofield"
        if d.GetFilterCount() >= MAX_FILTERS:
            return "full"
        d.AddFilter(DB.ScheduleFilter(fs.FieldId, DB.ScheduleFilterType.Equal, sec))
    fn = find_field(d, P_NAME)
    if fn is not None:
        has = False
        for j in range(d.GetFilterCount()):
            f = d.GetFilter(j)
            if field_name(d, f.FieldId) == P_NAME and (safe(lambda: f.GetStringValue()) or u"") == SKIP:
                has = True
        if not has and d.GetFilterCount() < MAX_FILTERS:
            d.AddFilter(DB.ScheduleFilter(fn.FieldId, DB.ScheduleFilterType.NotEqual, SKIP))
    return True


def set_sort(vs, rows, split, split_header, notes, sortp=None, missing=None, by_sys=True, kitp=None):
    """Сортировка спецификации. Маркер P_SORT — параметр ранга из настроек (sortp). Нет поля ИмяСистемы —
    без примечания у спецификации (одной строкой в отчёте: missing)."""
    d = vs.Definition
    d.ClearSortGroupFields()
    desc = sort_desc(rows)
    for prm, hdr in schedule_fields(rows, split, split_header, by_sys):
        down = prm in desc
        if prm == P_SORT and sortp:
            prm = sortp
        elif prm == P_KIT and kitp is not None:
            if not kitp:
                continue                     # «материал × 100 + тип» не пишется — по нему не сортировать
            prm = kitp
        f = ensure_field(d, prm)
        if f is None:
            if missing is not None:
                missing.setdefault(prm, []).append(vs.Name)
            else:
                notes.append(u"нет поля «{0}» — в сортировке пропущено".format(prm))
            continue
        sg = DB.ScheduleSortGroupField(f.FieldId, DB.ScheduleSortOrder.Descending if down else
                                       DB.ScheduleSortOrder.Ascending)
        sg.ShowHeader = hdr
        d.AddSortGroupField(sg)


def header_off_if_single(vs, infos_in, split_on, notes):
    """Подзаголовок группы только если значений больше одного; ADSK_Группирование без заголовка,
    если в нём то же имя системы, что и в заголовке деления (иначе две одинаковые строки)."""
    d = vs.Definition
    for i in reversed(range(d.GetSortGroupFieldCount())):
        sg = d.GetSortGroupField(i)
        nm = field_name(d, sg.FieldId)
        if nm == P_GRP and not sg.ShowHeader:
            d.RemoveSortGroupField(i)        # без заголовка поле только дробит строки с одинаковым наименованием
            continue
        if not sg.ShowHeader:
            continue
        vals = set((tval(it.el, nm) or u"") for it in infos_in)
        off = len(vals) <= 1
        if not off and nm == P_GRP and split_on:
            dup = sum(1 for it in infos_in if it.main and (tval(it.el, P_GRP) or u"").strip() == it.main)
            if dup:
                off = True
                notes.append(HDR_OFF)
        if off:
            if nm == P_GRP:
                d.RemoveSortGroupField(i)
            else:
                sg.ShowHeader = False
                d.SetSortGroupField(i, sg)


HDR_OFF = u"__hdr_off__"      # пометка: заголовок ADSK_Группирование выключен (в отчёте — одной строкой)


class Spec(object):
    def __init__(self, group, key, title, tpl):
        self.group = group
        self.key = key
        self.title = title
        self.tpl = tpl
        self.vs = None
        self.n = 0
        self.count = 0
        self.notes = []
        self.label = None
        self.whole = False

    @property
    def name(self):
        return u"{0}.{1} {2}".format(self.n, self.title, self.label or self.group["name"])


def make_specs(infos, cfg, report, mats=None):
    templates = find_templates()
    tried = set()
    present = {}
    for it in infos:
        if it.group and not it.hidden:
            present.setdefault((it.group, it.key), []).append(it)
    specs = []
    for g in cfg["groups"]:
        for key, bname, title, order in sorted(D.CATS, key=lambda c: c[3]):
            lst = present.get((g["name"], key))
            if not lst:
                continue
            tpl = templates.get(key)
            if tpl is None and key not in tried:
                tried.add(key)
                try:
                    with Tx(u"Спецификации: шаблон «{0}»".format(title)):
                        tpl = create_template(key, report)
                except Exception as ex:
                    report.append(u"шаблон для «{0}» не создался: {1}".format(title, ex))
                    tpl = None
                if tpl is not None:
                    templates[key] = tpl
            if tpl is None:
                report.append(u"нет шаблона спецификации для «{0}» (ADSK_Назначение вида = {1}) — {2} эл. группы {3} пропущены".format(
                    title, D.TEMPLATE_PURPOSE, len(lst), g["name"]))
                continue
            sp = Spec(g, key, title, tpl)
            sp.items = lst
            specs.append(sp)
    # старые созданные этой кнопкой — удалить
    with Tx(u"Спецификации: удалить прежние"):
        for uid in cfg.get("registry") or []:
            el = safe(lambda: doc.GetElement(uid))
            if el is None:
                continue
            if (el.Name or u"").startswith((u"О_", u"O_")):      # шаблоны пользователя «О_…» не удаляются
                continue
            try:
                doc.Delete(el.Id)
            except Exception as ex:
                try:
                    el.Name = u"Спецификация_старая_{0}".format(id_int(el.Id))
                except Exception:
                    pass
                report.append(u"не удалилась прежняя «{0}»: {1}".format(el.Name, ex))
        cfg["registry"] = []
        if cfg.get("_sec"):
            n_old = drop_block_leftovers(cfg["_sec"])
            if n_old:
                report.append(u"удалены прежние спецификации блока {0} не из списка сборки (не на листах): "
                              u"{1}".format(cfg["_sec"], n_old))
    qmin = qty_min(cfg)
    sortp = sort_param(cfg)
    missing = {}
    hidden_cols = {}
    drops = []
    with Tx(u"Спецификации: создать"):
        for k, sp in enumerate(specs):
            _p(3, k + 1, len(specs))
            sp.vs = doc.GetElement(sp.tpl.Duplicate(DB.ViewDuplicateOption.Duplicate))
            set_val(sp.vs, P_PURPOSE, D.SPEC_PURPOSE.format(sp.group["name"]))
            ok = set_filters(sp.vs, sp.group["name"], qmin, cfg.get("_sec"))
            if ok is not True:
                drops.append((sp, ok))
                continue
            set_sort(sp.vs, sort_rows_for(cfg, sp.key), sp.group.get("split"), sp.group.get("header"), sp.notes,
                     sortp, missing, sys_sort(cfg), kit_param(cfg))
            for nm in hide_service_fields(sp.vs):
                hidden_cols.setdefault(nm, set()).add(sp.title)
            center_fields(sp.vs)
            fix_column_widths(sp.vs)
        for sp, why in drops:                # блок: без фильтра секции таблица показала бы все блоки — не создаём
            report.append(u"«{0} {1}»: {2} — не создана".format(sp.title, sp.group["name"], (
                u"нет поля {0} (параметр не назначен категории)".format(P_SECTION) if why == "nofield" else
                u"у шаблона уже {0} фильтров, фильтр блока не добавить".format(MAX_FILTERS))))
            doc.Delete(sp.vs.Id)
            specs.remove(sp)
        doc.Regenerate()
        for sp in list(specs):
            sp.count = len(safe(lambda: list(DB.FilteredElementCollector(doc, sp.vs.Id).WhereElementIsNotElementType().ToElementIds()), []))
            if sp.count == 0:
                report.append(u"«{0} {1}»: после фильтров пусто — не создана".format(sp.title, sp.group["name"]))
                doc.Delete(sp.vs.Id)
                specs.remove(sp)
                continue
            header_off_if_single(sp.vs, sp.items, bool(sp.group.get("split")) and bool(sp.group.get("header")), sp.notes)
    for nm, titles in sorted(hidden_cols.items()):
        report.append(u"скрыт столбец «{0}» (в форме ГОСТ его нет): {1}".format(nm, u", ".join(sorted(titles))))
    for prm, names in sorted(missing.items()):
        report.append(u"нет поля «{0}» в спецификациях ({1}) — по нему не сортируется: {2}".format(
            prm, len(names), u", ".join(sorted(set(names))[:6]) + (u" …" if len(set(names)) > 6 else u"")))
    # дополнительные материалы — последней таблицей каждой связки
    mspecs = []
    if mats is not None:                     # и без отмеченных строк: ручные строки «О_Материалы» старых проектов
        try:
            with Tx(u"Спецификации: материалы"):
                mspecs = make_mat_specs(cfg, mats, specs, report)
        except Exception as ex:
            mspecs = []
            report.append(u"материалы: не вышло — {0}".format(ex))
    if mspecs:
        gi = dict((g["name"], i) for i, g in enumerate(cfg["groups"]))
        allp = ([(gi.get(sp.group["name"], 999), 0, k, sp) for k, sp in enumerate(specs)] +
                [(gi.get(sp.group["name"], 999), 1, k, sp) for k, sp in enumerate(mspecs)])
        specs = [x[3] for x in sorted(allp, key=lambda x: x[:3])]
    pre = u"{0}-".format(cfg["_sec"]) if cfg.get("_sec") else u""     # «1.6-1.Арматура трубопроводов В1»
    ov = not sys_sort(cfg)          # ОВ: название — категория, над первой таблицей группы — строка группы (0.17.0)
    with Tx(u"Спецификации: имена и заголовки"):
        existing = dict((v.Name, v) for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule))
        for n, sp in enumerate(specs, 1):
            sp.n = n
            sp.vs.Name = u"tmp_spec_{0}".format(id_int(sp.vs.Id))   # «~» Revit в именах запрещает
        for sp in specs:
            full = pre + sp.name
            old = existing.get(full)
            if old is not None and old.Id != sp.vs.Id:
                k = 1
                while True:
                    cand = u"{0} (старая{1})".format(full, u"" if k == 1 else u" " + str(k))
                    if cand not in existing:
                        break
                    k += 1
                old.Name = cand
                existing[cand] = old
                report.append(u"старая спецификация «{0}» переименована в «{1}»".format(full, cand))
            sp.vs.Name = full
            why = L.set_title(sp.vs, sp.title if ov else sp.name)
            if why:
                sp.notes.append(why)
            cfg["registry"].append(sp.vs.UniqueId)
        lo = layout_cfg(cfg)
        seen = set()
        for sp in specs:
            if sp.key != "mat":       # таблица материалов: строки материалов в «Заголовке» — не шапка, не трогать
                drop_col_head(sp.vs, sp.notes)
            title_row_height(sp.vs, float(lo.get("title_mm") or 0), sp.notes)
            row_style(sp.vs, None, lo.get("title_font"), lo.get("title_bold", True), lo.get("title_align"),
                      sp.notes, u"названия спецификации")
            g = sp.group
            if ov:
                ov_titles(sp, sp.key != "mat" and g["name"] not in seen, lo)
            if sp.key == "mat" or g["name"] in seen:
                continue
            seen.add(g["name"])
            if not ov and g.get("sys_row"):
                text = (g.get("sys_text") or u"").strip() or group_sys_title(g)
                note = (g.get("sys_note") or u"").strip()
                if note:
                    text = u"{0}. {1}".format(text.rstrip(u". "), note) if text else note
                add_sys_row(sp.vs, text, float(lo.get("sys_row_mm") or 8.0), sp.notes, lo)
    off = [sp.name for sp in specs if HDR_OFF in sp.notes]
    for sp in specs:
        sp.notes = [x for x in sp.notes if x != HDR_OFF]
    if off:
        report.append(u"заголовок ADSK_Группирование выключен (в нём имена систем): " + u", ".join(off))
    return specs


def ov_group_text(g):
    """Строка группы ОВ: свой текст «Строки названия системы» группы, иначе имя группы с заглавной («Вентиляция»)."""
    t = (g.get("sys_text") or u"").strip() if g.get("sys_row") else u""
    if not t:
        t = (g.get("name") or u"").strip()
        t = t[:1].upper() + t[1:]
    return t


def ov_titles(sp, first, lo):
    """ОВ (0.17.0): название таблицы — категория («Воздухораспределители»), без номера и имени группы; над первой
    таблицей группы — строка группы («Вентиляция»). Шаблон со своей строкой категории под названием («О_Оборудование»:
    «Отопление» / «Оборудование»): у первой таблицы группы его строка названия становится строкой группы, у
    остальных строка-дубль категории убирается."""
    hd, rc = L.header_cell(sp.vs)
    if hd is None:
        return
    r0, c0 = rc
    sub = False
    if sp.key != "mat" and hd.NumberOfRows > 1:
        t1 = safe(lambda: hd.GetCellText(r0 + 1, c0)) or u""
        sub = norm(t1) == norm(sp.title)
    gt = ov_group_text(sp.group)
    if sub:
        if first:
            why = L.set_title(sp.vs, gt)
            if why:
                sp.notes.append(why)
        else:
            try:
                hd.RemoveRow(r0 + 1)
            except Exception as ex:
                sp.notes.append(u"строка «{0}» шаблона не убралась: {1}".format(sp.title, ex))
    elif first and gt:
        lo2 = dict(lo or {})
        lo2["sys_pos"] = "above"
        add_sys_row(sp.vs, gt, float((lo or {}).get("sys_row_mm") or 8.0), sp.notes, lo2)


def title_row_height(vs, h_mm, notes):
    """Высота строки названия спецификации (раздел «Заголовок»), мм. 0 — как в шаблоне."""
    if h_mm <= 0:
        return
    hd, rc = L.header_cell(vs)
    if hd is None:
        return
    try:
        hd.SetRowHeight(rc[0], L.ft(h_mm))
    except Exception as ex:
        notes.append(u"высота заголовка {0:g} мм не записалась: {1}".format(h_mm, ex))


def add_sys_row(vs, text, h_mm, notes, lo=None):
    """Строка полного названия системы (раздел «Заголовок»), во всю ширину: над названием спецификации или под ним
    (lo["sys_pos"]); шрифт, полужирный и выравнивание — из lo (окно «Листы», блок «Строки таблицы»)."""
    lo = lo or {}
    hd, rc = L.header_cell(vs)
    if hd is None or not text:
        return
    r0 = rc[0]
    below = lo.get("sys_pos") == "below"
    r = r0 + 1 if below else r0
    if below and safe(lambda: hd.CanInsertRow(r), True) is False:
        notes.append(u"строку названия системы нельзя поставить под названием — поставлена над ним")
        below, r = False, r0
    try:
        hd.InsertRow(r)
        c0 = hd.FirstColumnNumber
        c1 = c0 + hd.NumberOfColumns - 1
        if c1 > c0:
            mc = DB.TableMergedCell(r, c0, r, c1)
            safe(lambda: hd.MergeCells(mc))
        src = r0 if below else r0 + 1                  # стиль — со строки названия
        st = safe(lambda: hd.GetTableCellStyle(src, c0))
        if st is not None:
            safe(lambda: hd.SetCellStyle(r, c0, st))
        hd.SetCellText(r, c0, text)
        hd.SetRowHeight(r, L.ft(h_mm))
        L.EXTRA_TITLE_MM[id_int(vs.Id)] = h_mm
    except Exception as ex:
        notes.append(u"строка названия системы не добавилась: {0}".format(ex))
        return
    row_style(vs, r, lo.get("sys_font"), lo.get("sys_bold"), lo.get("sys_align"), notes, u"названия системы")


# Шапки граф в спецификациях нет (решение пользователя 02.11.2026): «Поз. | Наименование | …» уже есть на листе.
COL_HEAD_WORDS = (u"поз", u"наимен")


def drop_col_head(vs, notes):
    """Убирает шапку граф: выключает «Показывать заголовки» тела и удаляет строки «Заголовка» ниже названия, в которых
    есть «Поз.» или «Наименование» (строка шапки шаблона «О_…»). Название (первая строка) не трогается."""
    d = vs.Definition
    if safe(lambda: d.ShowHeaders, False):
        try:
            d.ShowHeaders = False
        except Exception as ex:
            notes.append(u"шапка граф в теле не выключилась: {0}".format(ex))
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or hd.NumberOfRows < 2:
        return
    c0, n = hd.FirstColumnNumber, hd.NumberOfColumns
    for r in range(hd.LastRowNumber, hd.FirstRowNumber, -1):
        txt = u" ".join([(safe(lambda: hd.GetCellText(r, c0 + c)) or u"") for c in range(n)]).lower()
        if not any(w in txt for w in COL_HEAD_WORDS):
            continue
        try:
            hd.RemoveRow(r)
        except Exception as ex:
            notes.append(u"строка шапки граф не удалилась: {0}".format(ex))


ALIGN_STYLE = {"left": "Left", "center": "Center", "right": "Right"}
PT_MM = 0.3528              # 1 пункт, мм — запасной перевод размера шрифта ячейки
TS_WARNED = set()           # предупреждение «единицы не сверены» — один раз за сборку на строку


TS_PER_MM = 96.0 / 25.4     # TableCellStyle.TextSize — пиксели 96 dpi: 2,5 мм = 9,449; 3,5 мм = 13,228 (проверено
                            # в 421-1-ОВ 02.11.2026 откатом). Сверка по ячейке тела давала неверный множитель.


def text_size_k(vs):
    """Сколько единиц TableCellStyle.TextSize на 1 мм шрифта -> (k, сверено). 0.17.0: постоянный TS_PER_MM."""
    return TS_PER_MM, True


def _text_size_k_old(vs):
    """Прежняя сверка по ячейке тела (0.11.0) — не используется: ячейка тела могла нести не тот размер."""
    try:
        tt = doc.GetElement(vs.BodyTextTypeId)
        h = tt.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).AsDouble()
        bs = vs.GetTableData().GetSectionData(DB.SectionType.Body)
        ts = float(bs.GetTableCellStyle(bs.FirstRowNumber, bs.FirstColumnNumber).TextSize)
        if h > 0 and ts > 0:
            return ts / L.mm(h), True
    except Exception:
        pass
    return 1.0 / PT_MM, False


def row_style(vs, r, font_mm, bold, align, notes, what):
    """Шрифт (мм), полужирный и выравнивание строки r раздела «Заголовок» (None — первая строка, название).
    Стиль каждой ячейки строки — копия её же стиля с переопределением этих трёх свойств (рамки не меняются)."""
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or hd.NumberOfRows < 1:
        return
    if r is None:
        r = hd.FirstRowNumber
    c0 = hd.FirstColumnNumber
    size = None
    try:
        if font_mm and float(font_mm) > 0:
            k, ok = text_size_k(vs)
            size = float(font_mm) * k
            if not ok and what not in TS_WARNED:
                TS_WARNED.add(what)
                notes.append(u"шрифт {0}: единицы не сверены по телу таблицы, записан в пунктах".format(what))
    except Exception:
        size = None
    ha = getattr(DB.HorizontalAlignmentStyle, ALIGN_STYLE.get(align or "center", "Center"))
    err = None
    for c in range(hd.NumberOfColumns):
        try:
            base = safe(lambda: hd.GetTableCellStyle(r, c0 + c))
            st = DB.TableCellStyle(base) if base is not None else DB.TableCellStyle()
            opt = safe(lambda: st.GetCellStyleOverrideOptions()) or DB.TableCellStyleOverrideOptions()
            st.FontHorizontalAlignment = ha
            opt.HorizontalAlignment = True
            st.IsFontBold = bool(bold)
            opt.Bold = True
            if size:
                st.TextSize = size
                opt.FontSize = True
            st.SetCellStyleOverrideOptions(opt)
            hd.SetCellStyle(r, c0 + c, st)
        except Exception as ex:
            err = err or ex
    if err is not None:
        notes.append(u"оформление строки {0} записалось не полностью: {1}".format(what, err))


# ------------------------------------------------------------------
# позиции
# ------------------------------------------------------------------
_NUMERATOR = None


def load_numerator():
    """Разбор строк спецификаций — свой модуль vks_numerator.py (кнопка «Нумерация ВК.С» не нужна)."""
    global _NUMERATOR
    if _NUMERATOR is None:
        _NUMERATOR = imp.load_source("spec_manager_numerator", os.path.join(HERE, u"vks_numerator.py"))
    _NUMERATOR.doc = doc
    return _NUMERATOR


def sysnum_for(cfg, abbr):
    """Свой формат и начальный номер насосов для типа системы (вкладка «Материалы и типы» → Оборудование)."""
    pos = cfg.get("pos") or {}
    o = (pos.get("sysnum_by") or {}).get(abbr) or {}
    fmt = (o.get("fmt") or u"").strip() or pos.get("sysnum_fmt") or D.SYSNUM_FMT
    try:
        start = max(1, int(o.get("start") or 1))
    except Exception:
        start = 1
    return fmt, start


def sysnum_systems(infos, cfg, amap=None):
    """Типы систем (сокращения), в которых есть насосы «номер по системе»."""
    return sorted(set(x[4] for x in sysnum_preview(infos, cfg, amap, raw=True)), key=abbr_key)


def sysnum_label(abbr, n, fmt=None):
    """Номер оборудования «по системе»: {сист}.{n} → «В1.1.1»."""
    f = fmt or D.SYSNUM_FMT
    try:
        return f.replace(u"{сист}", abbr or u"").replace(u"{n}", u"%d" % n)
    except Exception:
        return u"{0}.{1}".format(abbr, n)


def is_sysnum(it, order):
    if it is None or it.key != "equip" or it.parent_id is not None:
        return False
    types = ((order or {}).get("equip") or {}).get("types") or []
    return 0 <= it.tp < len(types) and bool(types[it.tp].get("sysnum"))


def pos_mode(cfg):
    m = (cfg.get("pos") or {}).get("mode", "group")
    return "group" if m == "group_dot" else m


def _sys_gi(groups):
    m = {}
    for gi, g in enumerate(groups):
        for sname in g.get("systems") or []:
            m.setdefault(sname, gi)
    return m


def _main_of(it, sgi):
    best = None
    for sname in units_of(it):
        gi = sgi.get(sname)
        if gi is not None and (best is None or gi < best[0]):
            best = (gi, sname)
    if best is not None and GROUP_BY[0] == "grouping":
        best = (best[0], it.systems[0] if it.systems else D.NO_SYSTEM)
    return best


def sysnum_preview(infos, cfg, amap=None, raw=False):
    """Для окна: как будут пронумерованы «по системе» (насосы): [(номер, наименование, система, шт.)]."""
    amap = amap if amap is not None else AMAP
    order = cfg.get("order") or default_order(cfg)
    fmt = (cfg.get("pos") or {}).get("sysnum_fmt") or D.SYSNUM_FMT
    hidden = cfg.get("hidden") or {}
    groups = cfg.get("groups") or []
    sgi = _sys_gi(groups)
    rows = {}
    for it in infos:
        if it.key != "equip" or it.parent_id is not None:
            continue
        classify(it, order)
        if not is_sysnum(it, order) or is_hidden(it, hidden):
            continue
        best = _main_of(it, sgi)
        if best is None:
            continue
        gi, main = best
        ab = abbr_of(main, amap) if main != D.NO_SYSTEM else groups[gi]["name"]
        k = (gi, main, it.tp, it.name, u"%s" % (tval(it.el, u"ADSK_Марка") or u""),
             u"%s" % (tval(it.el, u"ADSK_Код изделия") or u""))
        r = rows.setdefault(k, [ab, 0])
        r[1] += 1
    # порядок как в спецификации: группа → основная система → тип → наименование (марка, код — отдельные строки)
    # одинаковые насосы на разных системах группы — одна позиция
    out, cnt, seen = [], {}, {}
    for k in sorted(rows, key=lambda x: (x[0], nat_key(x[1]), x[2], nat_key(x[3]), x[4], x[5])):
        ab = rows[k][0]
        pk = (k[0], _norm_name(k[3]), k[4], k[5])
        if pk in seen:
            o = seen[pk]
            out[o] = (out[o][0], out[o][1], out[o][2] + u", " + k[1], out[o][3] + rows[k][1], out[o][4])
            continue
        cnt[ab] = cnt.get(ab, 0) + 1
        seen[pk] = len(out)
        f_, st_ = sysnum_for(cfg, ab)
        out.append((sysnum_label(ab, st_ + cnt[ab] - 1, f_), k[3], k[1], rows[k][1], ab))
    return out if raw else [x[:4] for x in out]


def spec_preview(infos, cfg, mat_items=None):
    """Для окна: какие спецификации получатся (номер, категория, группа, индекс группы) — без учёта пустых после
    фильтров. Таблица материалов — после последней группы связки."""
    hidden = cfg.get("hidden") or {}
    groups = cfg.get("groups") or []
    sgi = _sys_gi(groups)
    present = set()
    for it in infos:
        if it.key == "gen" or is_hidden(it, hidden):
            continue
        best = _main_of(it, sgi)
        if best is not None:
            present.add((best[0], it.key))
    mats = {}
    if mat_items and cfg.get("_mat_run"):
        res = safe(lambda: _mat_preview_raw(infos, cfg, mat_items), {}) or {}
        mats = dict((k[-1], (link_label(groups, list(k)), v)) for k, v in res.items())
    out = []
    for gi, g in enumerate(groups):
        for key, bname, title, o in sorted(D.CATS, key=lambda c: c[3]):
            if (gi, key) in present:
                out.append((len(out) + 1, title, g["name"], gi))
        if gi in mats:
            out.append((len(out) + 1, D.MAT_TITLE, mats[gi][0], gi))
    return out


def _mat_preview_raw(infos, cfg, items):
    hidden = cfg.get("hidden") or {}
    groups = cfg.get("groups") or []
    sgi = _sys_gi(groups)
    for it in infos:
        if it.key in ("pipe", "duct"):
            classify(it, cfg.get("order") or default_order(cfg))

    def group_of(it):
        if is_hidden(it, hidden):
            return None
        best = _main_of(it, sgi)
        return groups[best[0]]["name"] if best is not None else None
    return mat_rows(infos, cfg, items, cfg.get("_mat_run") or [], group_of)


POS_STATS = {"rows": 0, "written": 0}    # для окна хода работы: позиций в спецификациях / записано


def number_positions(specs, infos, cfg, amap, report, problems):
    POS_STATS["rows"] = POS_STATS["written"] = 0
    num = load_numerator()
    byid = dict((i.id, i) for i in infos)
    mode = pos_mode(cfg)
    order = cfg.get("order") or default_order(cfg)
    pumps = {}
    values = {}
    counters = {}
    by_type = {}            # позиция — параметр типа: в строке стоит id типа, а не экземпляра
    for i in infos:
        by_type.setdefault(id_int(i.el.GetTypeId()), i)
    pump_pos = {}           # одинаковый насос в группе — один номер
    mat_vals = []
    gnum = dict((g["name"], i + 1) for i, g in enumerate(cfg.get("groups") or []))   # 0.20.0: номер группы

    def label(sp_, c_):
        if mode == "spec_dot":
            return u"{0}.{1}".format(sp_.n, c_)
        if mode == "group_prefix":
            return u"{0}.{1}".format(gnum.get(sp_.group["name"], 0), c_)
        return u"{0}".format(c_)
    for k, sp in enumerate(specs):
        _p(4, k + 1, len(specs))
        if sp.key == "mat":
            ck = sp.n if mode == "spec_dot" else (u"*" if mode == "all" else sp.group["name"])
            vals = []
            for r_ in getattr(sp, "rows", None) or []:
                counters[ck] = counters.get(ck, 0) + 1
                c = counters[ck]
                vals.append(label(sp, c))
            mat_vals.append((sp, vals))
            continue
        rows, targets, notes = num.map_rows(sp.vs)
        sp.notes.extend(notes)
        gname = sp.group["name"]
        if mode == "spec_dot":
            counter_key = sp.n
        elif mode == "all":
            counter_key = u"*"
        else:
            counter_key = gname
        last_parent, sub = None, 0
        for row in rows:
            ids = [t for t in row if t is not None]
            its = [byid.get(t) or by_type.get(t) for t in ids if (byid.get(t) or by_type.get(t)) is not None]
            if not ids:
                continue
            first = its[0] if its else None
            is_child = bool(its) and all(i.parent_id is not None and byid.get(i.parent_id) is not None and
                                         byid[i.parent_id].key == i.key for i in its)
            is_pump = sp.key == "equip" and is_sysnum(first, order)
            if is_pump:
                # одинаковые насосы (наименование, марка, код) в группе — одна позиция, даже на разных системах
                pk = (gname, _norm_name(first.name), u"%s" % (tval(first.el, u"ADSK_Марка") or u""),
                      u"%s" % (tval(first.el, u"ADSK_Код изделия") or u""))
                if pk in pump_pos:
                    value = pump_pos[pk]
                else:
                    ab = abbr_of(first.main, amap) if first.main else gname
                    pumps[ab] = pumps.get(ab, 0) + 1
                    f_, st_ = sysnum_for(cfg, ab)
                    value = sysnum_label(ab, st_ + pumps[ab] - 1, f_)
                    pump_pos[pk] = value
                last_parent, sub = value, 0
            elif is_child and sp.key == "equip" and last_parent is not None:
                sub += 1
                value = u"{0}.{1}".format(last_parent, sub)
            else:
                counters[counter_key] = counters.get(counter_key, 0) + 1
                c = counters[counter_key]
                value = label(sp, c)
                if not is_child:
                    last_parent, sub = value, 0
            POS_STATS["rows"] += 1                   # строка спецификации получила позицию
            for t in ids:
                if t in values and values[t][1] != value:
                    why = u"в двух строках: {0} и {1}".format(values[t][1], value)
                    te = doc.GetElement(targets[t])
                    if isinstance(te, DB.ElementType):
                        fam = safe(lambda: te.FamilyName) or u""
                        why += u" — ADSK_Позиция у «{0}: {1}» параметр типа, разные строки получают один номер".format(
                            fam, safe(lambda: te.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()) or u"")
                    problems.append((t, why))
                    continue
                values[t] = (targets[t], value)
    n = kept = 0
    POS_STATS["written"] = 0
    keep = layout_cfg(cfg).get("pos_update") == "keep"
    with Tx(u"Спецификации: позиции"):
        for t, (eid, value) in values.items():
            el = doc.GetElement(eid)
            if keep and el is not None and (u"%s" % (pval(el, P_POS) or u"")).strip():
                kept += 1                                  # «сохранить номера»: заполненные не трогаем
                continue
            r = set_val(el, P_POS, value) if el is not None else "none"
            if r == "ok":
                n += 1
            elif r in ("ro", "err", "none"):
                problems.append((t, u"позиция не записалась ({0})".format(r)))
        for sp, vals in mat_vals:
            fill_mat_positions(sp, vals)
            POS_STATS["rows"] += len(vals)
    if kept:
        report.append(u"позиции: сохранены прежние номера у {0} элементов (новым — по порядку); перенумеровать — "
                      u"вкладка «Листы»".format(kept))
    POS_STATS["written"] = n
    return n


# ------------------------------------------------------------------
# листы
# ------------------------------------------------------------------
def sheet_is_empty(sh):
    for v in DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.Viewport):
        return False
    for ssi in DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.ScheduleSheetInstance):
        vs = doc.GetElement(ssi.ScheduleId)
        if vs is not None and not L.is_revision_sched(vs):
            return False
    return True


def _num_split(num):
    m = re.match(u"^(.*?)(\\d+)(\\D*)$", num or u"")
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


def _num_rule(lo, others):
    """Правило номеров листов комплекта. others — {номер: (имя, заглушка)} остальных листов проекта.
    -> (start, step, fmt, текст) | (None, None, None, причина)."""
    mode = lo.get("num_mode", "keep")
    prefix = lo.get("num_prefix") or u""
    suffix = lo.get("num_suffix") or u""
    try:
        step = max(1, int(lo.get("num_step", 1) or 1))
    except Exception:
        step = 1
    if mode == "continue":
        last = None
        for n in sorted(others.keys(), key=nat_key):
            if not others[n][1] and _num_split(n):
                last = n
        if last is not None:
            base, k0, tail = _num_split(last)
            return (k0 + 1, 1, (lambda k, b=base, t=tail: u"{0}{1}{2}".format(b, k, t)),
                    u"продолжение после «{0}»".format(last))
        return 1, 1, (lambda k: u"%d" % k), u""
    if mode in ("prefix", "from"):
        try:
            start = max(1, int(lo.get("num_start", 1) or 1))
        except Exception:
            start = 1
        if not prefix and not suffix and start == 1:
            return None, None, None, u"нужен префикс или суффикс: номера 1, 2, 3 уже могут быть у листов РП"
        return start, step, (lambda k: u"{0}{1}{2}".format(prefix, k, suffix)), u""
    return None, None, None, u""


def _num_plan(count, start, step, fmt, taken):
    want, busy, k = [], [], start
    for i in range(count):
        while fmt(k) in taken:
            busy.append(fmt(k))
            k += step
        want.append(fmt(k))
        k += step
    return want, busy


def number_sheets(sheets, lo, report, sec=None):
    """Нумерация листов комплекта по вкладке «Листы» (sheets — по порядку раскладки). sec — блок: номера внутри
    его коллекции; «Продолжить после листов РП» — после листов коллекций «<секция>-…» этой секции."""
    mode = lo.get("num_mode", "keep")
    if mode == "keep" or not sheets:
        return
    ids = set(id_int(s.Id) for s in sheets)
    others = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if id_int(s.Id) not in ids]
    rule_from = others
    if sec:
        cols = L._collection_names()
        mine = L.sheet_collection_name(sheets[0], cols).lower()
        pref = (sec + u"-").lower()
        rule_from = [s for s in others if L.sheet_collection_name(s, cols).lower().startswith(pref)]
        others = [s for s in others if L.sheet_collection_name(s, cols).lower() == mine]
    taken = dict((s.SheetNumber, s) for s in others)
    start, step, fmt, msg = _num_rule(lo, dict((s.SheetNumber, (s.Name or u"", bool(s.IsPlaceholder)))
                                               for s in rule_from))
    if fmt is None:
        if msg:
            report.append(u"листы: {0} — номера не менялись".format(msg))
        return
    want, busy = _num_plan(len(sheets), start, step, fmt, taken)
    if busy:
        report.append(u"листы комплекта: номера заняты другими листами, пропущены: " + u", ".join(
            u"{0} («{1}»)".format(b, taken[b].Name) for b in busy[:8]))
    pairs = list(zip(sheets, want))
    if not all(s_.SheetNumber == n for s_, n in pairs):
        for s_, n in pairs:                           # сначала временные — чтобы листы не мешали друг другу
            if s_.SheetNumber != n:
                s_.SheetNumber = u"__tmp_{0}".format(id_int(s_.Id))
        for s_, n in pairs:
            if s_.SheetNumber != n:
                s_.SheetNumber = n
        report.append(u"листы комплекта пронумерованы: {0} … {1}{2}".format(
            want[0], want[-1], u" ({0})".format(msg) if msg else u""))
    if lo.get("num_stamp_on"):
        pname = (lo.get("num_stamp_param") or u"").strip()
        miss = 0
        for i, s_ in enumerate(sheets, 1):
            if not (_set_stamp(s_, pname, i) or _set_stamp(L.sheet_titleblock(s_), pname, i)):
                miss += 1
        if miss:
            report.append(u"номер в штампе: нет параметра «{0}» (или только чтение) на {1} листах".format(pname, miss))


COUNT_WORDS = (u"лист",)


def find_count_params(el_list):
    """Параметры штампа для числа листов: флаг Да/Нет и число (текст / целое) со словом «лист» в имени.
    -> (флаг, число) — имена или u""."""
    yn, nums = [], []
    for el in el_list:
        if el is None:
            continue
        for p in safe(lambda: list(el.Parameters), []) or []:
            if p.IsReadOnly:
                continue
            nm = safe(lambda: p.Definition.Name) or u""
            low = nm.lower()
            if not any(w in low for w in COUNT_WORDS) or u"номер" in low or u"имя" in low:
                continue
            dt = safe(lambda: p.Definition.GetDataType())
            if dt is not None and safe(lambda: dt == DB.SpecTypeId.Boolean.YesNo, False):
                yn.append(nm)
            elif p.StorageType in (DB.StorageType.String, DB.StorageType.Integer):
                nums.append(nm)

    def best(lst):
        for w in (u"количество листов", u"листов", u"кол"):
            for n in lst:
                if w in n.lower():
                    return n
        return lst[0] if lst else u""
    return best(yn), best(nums)


def write_sheet_count(sheets, lo, report):
    """В штамп каждого листа комплекта — число листов комплекта (не проекта) или своё итоговое число:
    сначала включается флаг Да/Нет, затем пишется число. Параметры ищутся сами."""
    if not sheets:
        return
    tb0 = L.sheet_titleblock(sheets[0])
    flag, pname = find_count_params([sheets[0], tb0])
    n = len(sheets)
    if lo.get("count_own"):
        try:
            n = max(1, int(lo.get("count_value") or n))
        except Exception:
            pass
    if not pname:
        report.append(u"число листов в штамп: у листа и штампа нет параметра числа листов (со словом «лист») — не записано")
        return
    miss_f = miss_n = 0
    for sh in sheets:
        tb = L.sheet_titleblock(sh)
        if flag and not (_set_stamp(sh, flag, 1) or _set_stamp(tb, flag, 1)):
            miss_f += 1
        if not (_set_stamp(sh, pname, n) or _set_stamp(tb, pname, n)):
            miss_n += 1
    report.append(u"число листов в штампе («{0}»{1}): {2} — на {3} листах".format(
        pname, u", флаг «{0}»".format(flag) if flag else u"", n, len(sheets) - miss_n))
    if miss_f:
        report.append(u"число листов: флаг «{0}» не записался на {1} листах".format(flag, miss_f))


def stamp_params(folder):
    """Для окна: найденные параметры числа листов у первого листа комплекта -> (флаг, число)."""
    L.SHEET_FOLDER = folder or u"ВК.С"
    sheets = safe(L.get_vks_sheets, []) or []
    if not sheets:
        return u"", u""
    return find_count_params([sheets[0], L.sheet_titleblock(sheets[0])])


def sheet_snapshot(folder):
    """Для окна: номера листов комплекта и остальных листов проекта (одно чтение)."""
    L.SHEET_FOLDER = folder or u"ВК.С"
    mine = safe(L.get_vks_sheets, []) or []
    ids = set(id_int(s.Id) for s in mine)
    others = {}
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        if id_int(s.Id) not in ids:
            others[s.SheetNumber] = (s.Name or u"", bool(s.IsPlaceholder))
    return {"mine": [s.SheetNumber for s in mine], "others": others}


def plan_sheet_numbers(lo, snap, count=None):
    """Без записи: какие номера получат листы комплекта и какие заняты. -> (номера, занятые, пояснение)."""
    mode = lo.get("num_mode", "keep")
    mine = list(snap.get("mine") or [])
    others = snap.get("others") or {}
    count = count if count is not None else max(1, len(mine))
    if mode == "keep":
        return mine, [], u""
    start, step, fmt, msg = _num_rule(lo, others)
    if fmt is None:
        return [], [], msg
    want, busy = _num_plan(count, start, step, fmt, others)
    return want, [u"{0} («{1}»)".format(b, others[b][0]) for b in busy], u""


def _set_stamp(el, pname, i):
    p = safe(lambda: el.LookupParameter(pname)) if el is not None and pname else None
    if p is None or p.IsReadOnly:
        return False
    try:
        st = p.StorageType
        if st == DB.StorageType.String:
            p.Set(u"%d" % i)
        elif st == DB.StorageType.Integer:
            p.Set(int(i))
        elif st == DB.StorageType.Double:
            p.Set(float(i))
        else:
            return False
        return True
    except Exception:
        return False


def row_mm(lo):
    """Высота строк по настройке: 5 / 8 / своя / None — как в шаблоне."""
    m = lo.get("row_mode", "5")
    if m == "tpl":
        return None
    if m == "8":
        return 8.0
    if m == "custom":
        try:
            v = float(lo.get("row_mm") or 0)
        except Exception:
            v = 0.0
        return v if v > 0 else None
    return 5.0


def do_layout(specs, report, cfg=None):
    """Раскладка на листы комплекта. Блок (cfg["_sec"]) — сначала его коллекция (создать / первый лист)."""
    cfg = cfg if cfg is not None else {}
    _p(5)                                       # время коллекции и листов — в этап «Листы», не в «Позиции»
    L.SEC_COLLECTION = None
    try:
        if cfg.get("_sec") and not ensure_section_sheets(cfg, report):
            return None
        return _do_layout(specs, report, cfg)
    finally:
        L.SEC_COLLECTION = None


def _new_collection(folder, report):
    """0.15.0, сборка «На весь объект»: листов комплекта нет — коллекция листов создаётся (если её нет), в ней первый
    лист без образца (Форма 5, штамп пустой). -> [лист] или [] (Revit без коллекций листов)."""
    rep = []                                    # в отчёт — только после записи шага (Revit мог его откатить)
    with Tx(u"Спецификации: коллекция листов"):
        col = L.find_collection(folder)
        if col is None:
            col = L.create_collection(folder)
            if col is None:
                return []
            rep.append(u"создана коллекция листов «{0}»".format(folder))
        L.create_first_sheet(col.Id, rep)
    report.extend(rep)
    return L.get_vks_sheets()


def _do_layout(specs, report, cfg):
    lo = layout_cfg(cfg)
    L.SHEET_FOLDER = (lo.get("sheet_folder") or u"").strip() or u"ВК.С"
    L.ROW_MM = row_mm(lo)
    L._ROW_STATE["warned"] = False
    sheets = L.get_vks_sheets()
    before = set(s.UniqueId for s in sheets)
    if not sheets and not cfg.get("_sec"):
        sheets = _new_collection(L.SHEET_FOLDER, report)
    if not sheets:
        report.append(u"нет листов «{0}» — спецификации не разложены".format(L.SHEET_FOLDER))
        return None
    managed = set(id_int(sp.vs.Id) for sp in specs)
    L.MIN_GROUP_ROWS = max(1, int(lo.get("min_rows", 4)))
    laps = Laps()                                   # подэтапы листов — одной строкой в отчёт
    with Tx(u"Спецификации: листы"):
        dx = L.ft(float(lo.get("left", L.LEFT_FROM_FRAME_MM)))         # от рамки слева (по умолчанию 20 мм)
        dtop = L.ft(float(lo.get("top", L.TOP_FROM_FRAME_MM)))         # от верха рамки (по умолчанию 37 мм)
        for k, sh in enumerate(sheets):
            L.normalize_sheet(sh, k == 0, report)
        removed = []
        for sh in sheets:
            for ssi in list(DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.ScheduleSheetInstance)):
                vs = doc.GetElement(ssi.ScheduleId)
                if vs is None or L.is_revision_sched(vs):
                    continue
                if id_int(vs.Id) not in managed and vs.Name not in removed:
                    removed.append(vs.Name)
                doc.Delete(ssi.Id)
        if removed:
            report.append(u"сняты с листов «{0}» (в проекте остались): ".format(L.SHEET_FOLDER) + u"; ".join(removed))
        doc.Regenerate()
        laps.lap(u"подготовка листов")
        lay = L.Layout(sheets, dx, dtop, report)
        prev = None
        prev_link = None
        lay.group_start = None
        for k, sp in enumerate(specs):
            _p(5, k + 1, len(specs))
            first = sp.group["name"] != prev
            link = sp.group.get("link")
            if sp.group.get("sec"):
                # разделы: раздел / таблица с нового листа — по флажкам, иначе подряд с отступом
                if prev is not None and first:
                    if sp.group.get("new_sheet", True) or getattr(sp, "new_sheet", False):
                        lay.new_sheet()
                    else:
                        lay.gap(float(lo.get("group_gap", 0) or 0))
                elif prev is not None:
                    if getattr(sp, "new_sheet", False):
                        lay.new_sheet()
                    else:
                        lay.gap(float(lo.get("spec_gap", 0) or 0))
            elif prev is not None and first and link and link == prev_link:
                lay.gap(float(lo.get("group_gap", 0) or 0))     # связка: та же страница, пока есть место
            elif prev is not None and first:
                lay.new_group(lo)
            elif prev is not None:
                lay.gap(float(lo.get("spec_gap", 0) or 0))
            if first:
                lay.group_start = None
            n0 = len(lay.placements)
            try:
                if getattr(sp, "whole", False):
                    lay.put_whole(sp.vs)               # таблица материалов: «Заголовок» Revit не делит
                else:
                    lay.put(sp.vs)
            except Exception as ex:
                sp.notes.append(u"не разложена: {0}".format(ex))
            if lay.group_start is None:
                lay.mark_group_start(n0)
            prev = sp.group["name"]
            prev_link = link
        laps.lap(u"размещение и разрывы")
        reg = cfg.setdefault("sheet_registry", [])
        for g in lay.geoms:
            if g.sheet.UniqueId not in before and g.sheet.UniqueId not in reg:
                reg.append(g.sheet.UniqueId)
        keep_empty, deleted = [], []
        for k, g in enumerate(lay.geoms):
            if k in lay.used:
                continue
            sh = g.sheet
            if sheet_is_empty(sh) and (sh.UniqueId in reg or cfg.get("delete_empty_sheets")):
                num_, uid_ = sh.SheetNumber, sh.UniqueId
                try:
                    doc.Delete(sh.Id)
                except Exception:
                    keep_empty.append(num_)
                    continue
                deleted.append(num_)
                if uid_ in reg:
                    reg.remove(uid_)
            else:
                keep_empty.append(sh.SheetNumber)
        lay.geoms = [g for g in lay.geoms if g.sheet.IsValidObject]
        lay.new_count = len([g for g in lay.geoms if g.sheet.UniqueId not in before])   # для окна хода работы
        laps.lap(u"пустые листы")
        sub = DB.SubTransaction(doc)
        sub.Start()
        try:
            number_sheets([g.sheet for g in lay.geoms], lo, report, cfg.get("_sec"))
            sub.Commit()
        except Exception as ex:
            sub.RollBack()
            report.append(u"нумерация листов не вышла, номера оставлены как были: {0}".format(ex))
        laps.lap(u"нумерация")
        if lo.get("count_on"):
            write_sheet_count([g.sheet for g in lay.geoms], lo, report)
            laps.lap(u"число листов в штамп")
        if L.ROW_MM:
            tot, ok = L.row_height_summary([g.sheet for g in lay.geoms], managed)
            report.append(u"высота строк {0:g} мм: задана у {1} частей таблиц{2}".format(
                float(L.ROW_MM), ok, u" из {0}".format(tot) if ok < tot else u""))
            laps.lap(u"проверка высот")
        lo["last_need"] = len([k for k in lay.used])
        lo["last_sig"] = layout_sig(cfg)
        est = cfg.pop("_est_sheets", None)
        report.append(u"листов комплекта занято: {0}{1}".format(
            lo["last_need"], u" (оценка до сборки была ≈ {0})".format(est) if est else u""))
        if deleted:
            report.append(u"удалены пустые листы: " + u", ".join(deleted))
        if keep_empty:
            report.append(u"листы без спецификаций: {0} — удалите, если не нужны".format(u", ".join(keep_empty)))
        report.append(u"листы по подэтапам, с: " + laps.text())
    return lay


# ------------------------------------------------------------------
# оценка числа листов до сборки (для окна «Листы»): без транзакций, по уже прочитанным данным
# ------------------------------------------------------------------
# запасные значения — ТОЛЬКО если шаблон «О_…» не прочитан (иначе всё берётся из шаблона: template_metrics)
EST_FALLBACK_HDR_MM = (8.0, 15.0)   # строки «Заголовка»: «верх», «низ» (шапка граф)
EST_FRAME_MM = 297.0     # высота штампа А3, если листов комплекта нет
SIG_GROUP_KEYS = ("name", "systems", "link", "sys_row", "split", "header")
SIG_LAYOUT_SKIP = ("last_need", "last_sig", "count_on", "count_flag", "count_param", "count_own", "count_value",
                   "num_mode", "num_start", "num_step", "num_prefix", "num_suffix", "num_stamp_on", "num_stamp_param",
                   "pos_update")


def _sig_hash(obj):
    s = json.dumps(obj, sort_keys=True)
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return u"%08x" % h


def layout_sig(cfg, rows_only=False):
    """Подпись настроек, от которых зависит число листов. rows_only — только то, что меняет строки спецификаций
    (кэш строк в окне); иначе ещё и поля «Листов». Сборка пишет её в layout.last_sig рядом с last_need."""
    groups = [dict((k, g.get(k)) for k in SIG_GROUP_KEYS) for g in cfg.get("groups") or []]
    obj = {"groups": groups, "hidden": cfg.get("hidden") or {}, "qty_hide": sorted(cfg.get("qty_hide") or []),
           "qty_min": cfg.get("qty_min"), "sort": cfg.get("sort") or {}}
    if rows_only:
        obj["mat_run"] = sorted(cfg.get("_mat_run") or [])
    else:
        lo = cfg.get("layout") or {}
        obj["layout"] = dict((k, v) for k, v in lo.items() if k not in SIG_LAYOUT_SKIP)
    return _sig_hash(obj)


EST_CHAR_K = 0.6         # средняя ширина буквы = высота шрифта × коэффициент сжатия × EST_CHAR_K
EST_LINE_K = 1.45        # шаг строк текста в ячейке = высота шрифта × EST_LINE_K
EST_PAD_MM = 1.0         # поля ячейки сверху/снизу и слева/справа, мм
EST_TEXT_MM = 2.5        # шрифт тела, если в шаблоне не прочитать


def template_metrics():
    """Для оценки листов (только чтение, один раз за запуск): по шаблонам «О_…» -> {категория: {
    "cols": [(поле, ширина мм)] — видимые графы; "hdr": [высоты строк «Заголовка», мм] — все, по одной;
    "body_head": шапка граф в теле (если «Показывать заголовки»), мм, иначе 0; "row": базовая высота строки тела, мм
    (авто по шрифту) или None; "text": шрифт тела, мм; "wk": сжатие; "sort": [(поле, ShowHeader, ShowFooter,
    ShowBlankLine)] — поля сортировки шаблона (сборка задаёт свои — set_sort)}}."""
    out = {}
    for key, vs in (find_templates() or {}).items():
        m = {"cols": [], "hdr": [], "body_head": 0.0, "row": None, "text": EST_TEXT_MM, "wk": 1.0, "sort": []}
        tt = safe(lambda: doc.GetElement(vs.BodyTextTypeId))
        if tt is not None:
            h = safe(lambda: tt.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).AsDouble())
            w = safe(lambda: tt.get_Parameter(DB.BuiltInParameter.TEXT_WIDTH_SCALE).AsDouble())
            if h:
                m["text"] = L.mm(h)
            if w:
                m["wk"] = w
        d = vs.Definition
        for f in _field_list(d):
            if safe(lambda: f.IsHidden, True):
                continue
            w = safe(lambda: f.GridColumnWidth) or safe(lambda: f.SheetColumnWidth)
            m["cols"].append((safe(lambda: f.GetName()) or u"", L.mm(w) if w else 0.0))
        if not m["cols"]:
            m["cols"] = [(u"", w) for w in getattr(D, "COLUMN_WIDTHS_MM", [])]
        for i in range(safe(lambda: d.GetSortGroupFieldCount(), 0) or 0):
            sg = d.GetSortGroupField(i)
            m["sort"].append((field_name(d, sg.FieldId), bool(sg.ShowHeader), bool(sg.ShowFooter),
                              bool(sg.ShowBlankLine)))
        m["hdr"] = [x for x in L.header_rows_mm(vs) if x > 0]
        m["body_head"] = L.body_head_mm(vs)
        bs = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Body))
        if bs is not None:
            r = bs.FirstRowNumber + (1 if m["body_head"] > 0 else 0)
            if r <= bs.LastRowNumber:
                h = safe(lambda: bs.GetRowHeight(r))
                m["row"] = L.mm(h) if h else None
        out[key] = m
    return out


def text_lines(text, width_mm, text_mm, wk=1.0):
    """Сколько строк займёт текст в графе шириной width_mm (перенос по словам, как Revit)."""
    text = (u"%s" % (text or u"")).strip()
    if not text or width_mm <= 0:
        return 1
    cw = max(0.3, text_mm * wk * EST_CHAR_K)
    per = max(1, int((width_mm - 2 * EST_PAD_MM) / cw))
    lines, cur = 1, 0
    for w in text.split():
        n = len(w)
        if cur and cur + 1 + n <= per:
            cur += 1 + n
            continue
        if cur:
            lines += 1                     # слово не влезло — новая строка
        while n > per:                     # слово длиннее графы — рвётся
            n -= per
            lines += 1
        cur = n
    return lines


def row_height(it, cols, base_mm, text_mm, wk=1.0):
    """Высота строки с переносом: максимум по графам, где у элемента есть текст."""
    nl = 1
    for nm, w in cols:
        if not nm or w <= 0:
            continue
        v = tval(it.el, nm)
        if v is None or isinstance(v, (int, float)):
            continue
        nl = max(nl, text_lines(v, w, text_mm, wk))
    if nl <= 1:
        return base_mm
    return max(base_mm, nl * text_mm * EST_LINE_K + EST_PAD_MM)


def estimate_specs(infos, cfg, mat_items=None, metrics=None):
    """Будущие спецификации в порядке сборки (без Revit-транзакций; меняет только служебные поля Info, как
    small_rows_preview): [{"group", "gi", "key", "whole", "rows": [(высота по шаблону мм, 'grp' | 'data')],
    "hdr": [строки «Заголовка» шаблона, мм], "body_head": мм}].
    Строки тела: данные после скрытых «< порога» и гибов (они уходят в трубы) + заголовки групп — строка на каждое
    уникальное сочетание значений полей с ShowHeader, включая пустое (Revit, замер 14.10.2026), вложенные — на
    каждое сочетание; + строка на группу при ShowFooter и при ShowBlankLine. Какие поля с заголовком — как их
    оставит сборка (set_sort, header_off_if_single). Высоты строк здесь — базовые из шаблона с переносом текста;
    заданная на «Листах» высота (она одна на все строки тела) подставляется в estimate_sheets."""
    import copy
    c = copy.deepcopy(cfg)
    lo = layout_cfg(c)
    metrics = metrics or {}
    groups = c.get("groups") or []
    assign_groups(infos, groups, c.get("hidden") or {}, {})
    compute_order(infos, c, [])
    pipe_names = set(_norm_name(i.name) for i in infos if i.key == "pipe" and i.name)
    qmin = qty_min(c)
    hide = set(c.get("qty_hide") or [])

    def q(it):
        v = num(tval(it.el, P_QTY))
        if v > 0 or it.key != "pipe":
            return v
        return safe(lambda: it.el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble() * FT / 1000.0, 0.0)
    live = [it for it in infos if it.group and not it.hidden and it.key != "gen" and
            not (D.BEND_MERGE and is_bend(it, pipe_names))]
    drop = set()
    for k, (tot, lst, sig) in qty_rows(live, c, q).items():
        if zero_auto(k[1], tot) or (tot < qmin - 1e-9 and sig in hide):
            drop.update(id(x) for x in lst)
    gmap = dict((g["name"], g) for g in groups)
    by = {}
    for it in live:
        if id(it) not in drop:
            by.setdefault((it.group, it.key), []).append(it)

    def sk(v):
        return (0, v, ()) if isinstance(v, (int, float)) else (1, 0, nat_tuple(u"%s" % v))
    specs = []
    for gi, g in enumerate(groups):
        for key, bname, title, o in sorted(D.CATS, key=lambda x: x[3]):
            lst = by.get((g["name"], key))
            if not lst:
                continue
            flds = schedule_fields(sort_rows_for(c, key), g.get("split"), g.get("header"), sys_sort(c))
            flds = [(p, h) for p, h in flds if not (p == P_GRP and not h)]
            vals = [tuple((tval(it.el, p) or u"") if p == P_GRP else row_value(it, p) for p, h in flds) for it in lst]
            split_on = bool(g.get("split")) and bool(g.get("header"))
            hdr = []
            for j, (p, h) in enumerate(flds):
                if not h:
                    continue
                # как header_off_if_single: одно значение (в т. ч. пустое) — заголовок выключается сборкой;
                # ADSK_Группирование с теми же именами систем, что в заголовке деления, — тоже
                if len(set((tval(it.el, p) or u"") for it in lst)) <= 1:
                    continue
                if p == P_GRP and split_on and any(it.main and (tval(it.el, P_GRP) or u"").strip() == it.main
                                                   for it in lst):
                    continue
                hdr.append(j)
            # ShowFooter / ShowBlankLine: set_sort их не включает (False) — строки не добавляются; если включить,
            # учесть здесь: (заголовок, подвал, пустая строка) по уровню j
            foot = dict((j, (False, False)) for j in hdr)
            m = metrics.get(key) or {}
            rbase = m.get("row") or (m.get("text") or EST_TEXT_MM) * EST_LINE_K + EST_PAD_MM
            first_it = {}
            for v, it in zip(vals, lst):
                first_it.setdefault(v, it)
            rows, prev = [], None

            def close(level, rows=rows):
                for j in reversed([x for x in hdr if x >= level]):
                    f_, b_ = foot[j]
                    if f_:
                        rows.append((rbase, "data"))
                    if b_:
                        rows.append((rbase, "grp"))
            for v in sorted(first_it, key=lambda v: tuple(sk(x) for x in v)):
                lvl = None
                for j in hdr:
                    if prev is None or v[:j + 1] != prev[:j + 1]:
                        lvl = j
                        break
                if lvl is not None:
                    if prev is not None:
                        close(lvl)
                    for j in hdr:
                        if j >= lvl:
                            rows.append((rbase, "grp"))
                rows.append((row_height(first_it[v], m.get("cols") or [], rbase, m.get("text") or EST_TEXT_MM,
                                        m.get("wk") or 1.0), "data"))
                prev = v
            if prev is not None and hdr:
                close(hdr[0])
            specs.append({"group": g["name"], "gi": gi, "key": key, "whole": False, "rows": rows,
                          "hdr": list(m.get("hdr") or []), "body_head": m.get("body_head") or 0.0})
    # таблицы материалов — последней в своей связке, целиком
    if mat_items and c.get("_mat_run"):
        res = safe(lambda: _mat_preview_raw(infos, c, mat_items), {}) or {}
        for idxs, mrows in res.items():
            if not mrows:
                continue
            gi = list(idxs)[-1]
            at = max([k + 1 for k, sp in enumerate(specs) if sp["gi"] in idxs] or [0])
            if at == 0:
                continue
            mp = metrics.get("pipe") or {}
            rbase = mp.get("row") or (mp.get("text") or EST_TEXT_MM) * EST_LINE_K + EST_PAD_MM
            rows = [(rbase, "data")] * len(mrows)          # таблица материалов — без строки шапки граф
            specs.insert(at, {"group": groups[gi]["name"], "gi": gi, "key": "mat", "whole": True, "rows": rows,
                              "hdr": list(mp.get("hdr") or [])[:1], "body_head": 0.0})
    seen = set()
    for sp in specs:
        g = gmap.get(sp["group"]) or {}
        sp["sys_row"] = bool(sp["key"] != "mat" and sp["group"] not in seen and g.get("sys_row"))
        if sp["key"] != "mat":
            seen.add(sp["group"])
    return specs


def sheet_frame(folder):
    """Для окна: высота штампа первого листа комплекта, мм (только чтение). None — листов нет."""
    L.SHEET_FOLDER = folder or u"ВК.С"
    sheets = safe(L.get_vks_sheets, []) or []
    if not sheets:
        return None
    tb = L.sheet_titleblock(sheets[0])
    bb = safe(lambda: tb.get_BoundingBox(sheets[0])) if tb is not None else None
    return L.mm(bb.Max.Y - bb.Min.Y) if bb is not None else None


def estimate_sheets(specs, cfg, frame_mm=None):
    """Раскладка specs (из estimate_specs) по листам — те же правила, что в do_layout / vks_layout: отступы,
    группа с нового листа и «хвост», связки, отступы между спецификациями, «не меньше N строк под заголовком»,
    перенос по строкам, таблица материалов целиком. Первый лист — Форма 5, остальные — Форма 6. -> число листов."""
    lo = layout_cfg(cfg)
    H = float(frame_mm or EST_FRAME_MM)
    top = float(lo.get("top", L.TOP_FROM_FRAME_MM))
    bot1 = L.BOTTOM_MM.get(u"Форма 5", L.BOTTOM_DEFAULT_MM)
    cap1, cap2 = H - top - bot1, H - top - L.BOTTOM_DEFAULT_MM
    rmm0 = row_mm(lo)                         # «Высота строки» на листе — одна на все строки тела; None — шаблон
    top_set = float(lo.get("title_mm") or 0)
    head_set = float(lo.get("head_mm") or 0)
    sysmm = float(lo.get("sys_row_mm") or 0) or EST_FALLBACK_HDR_MM[0]

    def rep_mm(sp):
        """Повторяется на каждой части: строки «Заголовка» (по одной, с заданными «верх» / «низ»), строка названия
        системы, шапка граф в теле, рамка части (SEGMENT_FRAME_MM, худший замер)."""
        hdr = list(sp.get("hdr") or EST_FALLBACK_HDR_MM)
        if sp.get("whole"):                   # таблица материалов: строка названия (строки материалов — в rows)
            hdr = hdr[:1]
            if top_set > 0:
                hdr[0] = top_set
        else:
            if head_set > 0:
                hdr[-1] = head_set
            if len(hdr) >= 2 and top_set > 0:
                hdr[0] = top_set
        return (sum(hdr) + float(sp.get("body_head") or 0.0) + (sysmm if sp.get("sys_row") else 0.0) +
                L.SEGMENT_FRAME_MM)
    old_min = L.MIN_GROUP_ROWS
    L.MIN_GROUP_ROWS = max(1, int(lo.get("min_rows", 4)))
    st = {"i": 0, "used": 0.0, "start": None}
    used, placed = set(), []

    def cap(i):
        return cap1 if i == 0 else cap2

    def free():
        return cap(st["i"]) - st["used"]

    def advance():
        st["i"] += 1
        st["used"] = 0.0

    def gap(mm_):
        if st["used"] <= 1e-6 or mm_ <= 0:
            return
        if free() - mm_ >= L.MIN_PIECE_MM + 10:
            st["used"] += mm_
        else:
            advance()

    def new_group():
        if st["used"] <= 1e-6:
            return
        g_ = float(lo.get("group_gap", L.GROUP_GAP_MM))
        if not lo.get("group_new_sheet", True):
            gap(g_)
            return
        carried = st["start"] is not None and st["i"] > st["start"]
        frac = float(lo.get("tail_pct", L.TAIL_MAX_FRAC * 100)) / 100.0
        if lo.get("tail_on", True) and carried and st["used"] <= cap(st["i"]) * frac:
            if free() - g_ >= L.MIN_PIECE_MM + 10:
                st["used"] += g_
                return
        advance()

    def put_here(h):
        used.add(st["i"])
        placed.append(st["i"])
        st["used"] += h

    def put(sp):
        t = rep_mm(sp)
        rows = [(rmm0 or r[0], r[1]) for r in sp["rows"]]
        h = t + sum(r[0] for r in rows)
        if sp.get("whole"):
            if h > free() + 0.3 and st["used"] > 1e-6:
                advance()
            put_here(min(h, free()))
            return
        if free() < L.MIN_PIECE_MM and st["used"] > 1e-6:
            advance()
        if h <= free() + 0.3:
            put_here(h)
            return
        bh = [r[0] for r in rows]
        for attempt in range(2):
            i0, f0 = st["i"], free()
            segs, push = L.plan_rows(rows, lambda k: (f0 if k == 0 else cap(i0 + k)) - t - L.SAFETY_MM)
            if push and attempt == 0 and st["used"] > 1e-6:
                advance()
                continue
            if push or not segs:          # сборка в этом случае делит прежним способом — оценим так же, по высотам
                segs = L.plan_rows([(x, "data") for x in bh], lambda k: (f0 if k == 0 else cap(i0 + k)) - t - L.SAFETY_MM)[0]
            if len(segs) < 2:
                put_here(h)
                return
            for si, (a, b) in enumerate(segs):
                if si > 0:
                    advance()
                put_here(t + sum(bh[a:b]))
            return

    try:
        prev = prev_link = None
        for sp in specs:
            g = None
            for gg in cfg.get("groups") or []:
                if gg.get("name") == sp["group"]:
                    g = gg
                    break
            link = (g or {}).get("link")
            first = sp["group"] != prev
            if prev is not None and first and link and link == prev_link:
                gap(float(lo.get("group_gap", 0) or 0))
            elif prev is not None and first:
                new_group()
            elif prev is not None:
                gap(float(lo.get("spec_gap", 0) or 0))
            if first:
                st["start"] = None
            n0 = len(placed)
            put(sp)
            if st["start"] is None and n0 < len(placed):
                st["start"] = placed[n0]
            prev, prev_link = sp["group"], link
    finally:
        L.MIN_GROUP_ROWS = old_min
    return len(used)


# ------------------------------------------------------------------
# проверки
# ------------------------------------------------------------------
def zero_rows(vs):
    """Строки, где в столбце количества 0 или пусто."""
    d = vs.Definition
    vis = [d.GetField(i) for i in range(d.GetFieldCount()) if not d.GetField(i).IsHidden]
    qi = None
    for i, f in enumerate(vis):
        if safe(lambda: f.GetName()) in (P_QTY, u"Число", u"Количество", u"Длина"):
            qi = i
    if qi is None:
        return []
    body = vs.GetTableData().GetSectionData(DB.SectionType.Body)
    out = []
    for r in range(body.FirstRowNumber, body.LastRowNumber + 1):
        try:
            txt = vs.GetCellText(DB.SectionType.Body, r, body.FirstColumnNumber + qi)
            name = vs.GetCellText(DB.SectionType.Body, r, body.FirstColumnNumber + min(1, qi))
        except Exception:
            continue
        t = (txt or u"").strip().replace(u",", u".")
        if not t:
            continue
        try:
            if float(t) <= 0:
                out.append(u"{0} = {1}".format(name, txt))
        except Exception:
            pass
    return out


_SECTIONS = None


def sections_module():
    """Сборка по разделам (ОВ) — vks_sections.py; получает этот модуль параметром."""
    global _SECTIONS
    if _SECTIONS is None:
        _SECTIONS = imp.load_source("spec_manager_sections", os.path.join(HERE, u"vks_sections.py"))
    return _SECTIONS


def _build(infos, cfg, report, problems, stats, amap):
    """Группы → порядок → материалы → ключи → спецификации → позиции → листы (для всех элементов или блока).
    -> (спецификации, раскладка | None)."""
    laps = Laps(stats)
    assign_groups(infos, cfg["groups"], cfg.get("hidden") or {}, stats)
    laps.lap(u"группы")
    with Tx(u"Спецификации: гибы в трубы"):
        merge_bends(infos, report, stats)
    laps.lap(u"гибы")
    compute_order(infos, cfg, report)
    laps.lap(u"порядок (шаг 3)")
    mats = {}
    run_ids = cfg.get("_mat_run") or []
    if run_ids:
        try:
            mats = mat_rows(infos, cfg, load_materials(cfg), run_ids)
        except Exception as ex:
            report.append(u"материалы: расчёт не вышел — {0}".format(ex))
        laps.lap(u"материалы")
    drop_zero_rows(infos, cfg, stats, report)
    laps.lap(u"малые строки")
    with Tx(u"Спецификации: системы, группы, сортировка"):
        write_element_keys(infos, stats, cfg, report)
    laps.lap(u"ключи (запись)")
    specs = make_specs(infos, cfg, report, mats)
    laps.lap(u"таблицы")
    _n(3, plural(len(specs), u"спецификация", u"спецификации", u"спецификаций"))
    npos = number_positions(specs, infos, cfg, amap, report, problems)
    laps.lap(u"позиции")
    _n(4, plural(POS_STATS["rows"], u"позиция", u"позиции", u"позиций") +
       (u", изменено {0}".format(npos) if npos != POS_STATS["rows"] else u""))
    seen = set()
    problems[:] = [x for x in problems if not (x in seen or seen.add(x))]
    stats[u"позиций записано"] = npos
    lay = do_layout(specs, report, cfg)
    laps.lap(u"листы")
    cfg.pop("_est_sheets", None)
    if lay is not None:
        nl = len(lay.used)
        _n(5, plural(nl, u"лист", u"листа", u"листов") + (u", новых {0}".format(lay.new_count)
                                                           if getattr(lay, "new_count", 0) else u""))
    else:
        _n(5, u"листов комплекта нет")
    return specs, lay


def _build_blocks(infos, cfg, scope, report, problems, stats, amap):
    """Сборка по блокам: «на блок» (cfg["build"]["sec"]) или «по всем блокам отдельно». У каждого блока свой
    комплект: коллекция section_folder, свои позиции с 1, свой реестр; элементы других блоков не трогаются."""
    found, nosec = sections_found(infos)
    if scope == "one":
        secs = [(cfg.get("build") or {}).get("sec")]
    else:
        secs = [x[0] for x in found]
    secs = [x for x in secs if x]
    if not secs:
        raise UserError(u"в модели не заполнен ADSK_Номер секции — собирать по блокам нечего; выберите «Общая на "
                        u"объект»")
    if nosec:
        report.append(u"без ADSK_Номер секции: {0} эл. — в комплекты блоков не попали".format(nosec))
    all_specs, lays = [], []
    for sec in secs:
        part = [it for it in infos if it.sec == sec]
        if not part:
            report.append(u"блок {0}: элементов нет".format(sec))
            continue
        c = scope_cfg(cfg, sec)
        c["groups"] = block_groups(cfg, sec, found_systems(part, amap))
        rep, st = [], {}
        _NOTE_PREFIX[0] = u"{0}: ".format(sec)
        try:
            specs, lay = _build(part, c, rep, problems, st, amap)
        finally:
            _NOTE_PREFIX[0] = u""
        scope_back(cfg, c, sec)
        report.extend(u"блок {0}: {1}".format(sec, r) for r in rep)
        for k, v in st.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                stats[k] = stats.get(k, 0) + v
            else:
                stats[k] = v
        all_specs.extend(specs)
        if lay is not None:
            lays.append(lay)
    stats[u"блоков собрано"] = len(secs)
    return all_specs, lays


def run(d, cfg, log=print, progress=None, note=None):
    if cfg.get("mode") == "sections":
        import sys
        return sections_module().run(sys.modules[__name__], d, cfg, log, progress, note)
    _timing_start(progress, note)
    set_doc(d)
    TX_WARNINGS.clear()
    report, problems, stats = [], [], {}
    _p(0)
    detect_categories()
    amap = system_abbr_map()
    lo = layout_cfg(cfg)
    L.ROW_MM = row_mm(lo)
    tg = DB.TransactionGroup(doc, u"Менеджер спецификаций")
    tg.Start()
    try:
        with Tx(u"Спецификации: параметры систем"):
            ensure_params(report)
        infos = collect()
        if cfg.get("moves"):
            with Tx(u"Спецификации: перенос систем между группами (ADSK_Группирование)"):
                apply_moves(infos, cfg, report, stats)
        with Tx(u"Спецификации: ADSK_Номер секции вложенным и изоляции"):
            sync_sections(infos, report, stats)
        set_moves(None)                      # в модели уже записано — в памяти не переносить
        set_units(infos, cfg.get("group_by") or "systems", cfg.get("group_fallback", True) is not False)
        if GROUP_BY[0] == "grouping" and UNRESOLVED:
            report.append(unresolved_text())
        _p(1)
        with Tx(u"Спецификации: изоляция и количество"):
            process_insulation(infos, report, stats)
            fill_quantities(infos, stats, report)
        _p(2)
        scope = (cfg.get("build") or {}).get("scope") or "all"
        if scope not in ("one", "each"):
            specs, lay = _build(infos, cfg, report, problems, stats, amap)
            lays = [lay] if lay is not None else []
        else:
            specs, lays = _build_blocks(infos, cfg, scope, report, problems, stats, amap)
        tg.Assimilate()
        warnings_report(report)
    except UserError as ex:
        tg.RollBack()
        _timing_stop(len(STAGES))
        return {"ok": False, "error": u"%s" % ex, "report": report, "stats": stats}
    except Exception:
        tg.RollBack()
        _timing_stop(len(STAGES))
        return {"ok": False, "error": traceback.format_exc(), "report": report, "stats": stats}
    times = _timing_stop(len(STAGES))
    cfg["_build_times"] = times
    placements = {}
    for lay in lays:
        for nm, seg, shn in lay.placements:
            placements.setdefault(nm, []).append(shn if seg < 0 else u"{0}({1})".format(shn, seg + 1))
    zeros = {}
    for sp in specs:
        z = safe(lambda: zero_rows(sp.vs), [])
        if z:
            zeros[sp.vs.Name] = z
    return {"ok": True, "report": report, "stats": stats, "problems": problems, "zeros": zeros, "times": times,
            "specs": [{"n": sp.n, "name": sp.vs.Name, "count": sp.count, "sheets": placements.get(sp.vs.Name, []),
                       "notes": sp.notes} for sp in specs]}


def remember_timing(cfg, key, times):
    """Замеры этапов — в настройки проекта: следующий запуск считает «осталось ≈» по ним (среднее с прошлым)."""
    if not times or sum(times) <= 0:
        return
    tm = cfg.setdefault("timing", {})
    old = tm.get(key)
    if isinstance(old, list) and len(old) == len(times) and sum(old) > 0:
        times = [round((a + b) / 2.0, 2) for a, b in zip(old, times)]
    tm[key] = times
