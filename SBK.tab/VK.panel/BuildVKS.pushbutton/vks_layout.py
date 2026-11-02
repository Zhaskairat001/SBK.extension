# -*- coding: utf-8 -*-
"""Менеджер спецификаций — листы: штампы Форма 5 / Форма 6, раскладка спецификаций встык с переносом.
Взято из первой версии кнопки (script_v1.py); каждая группа систем — с нового листа."""
from __future__ import print_function
import re

from System.Collections.Generic import List
from Autodesk.Revit import DB

SHEET_FOLDER = u"ВК.С"
SHEET_SECTION_PARAM = u"ADSK_Штамп Раздел проекта"
SHEET_NAME = u"Спецификация оборудования, изделий и материалов"
TITLE_MM = 8.0
BOTTOM_MM = {u"Форма 5": 45.0, u"Форма 3": 62.0}
BOTTOM_DEFAULT_MM = 20.0
TOP_FROM_FRAME_MM = 37.0
LEFT_FROM_FRAME_MM = 20.0
MIN_PIECE_MM = 22.0
SAFETY_MM = 0.5
SHEET_FIRST = (u"Форма 5", {u"Девятиграфка": 1, u"Девятиграфка_Шапка": 1, u"Штамп согласований": 1})
SHEET_OTHER = (u"Форма 6", {u"Девятиграфка": 1, u"Девятиграфка_Шапка": 1, u"Штамп согласований": 0})
FT = 304.8
ROW_MM = None             # высота строк спецификации на листе, мм (None — как в шаблоне); задаёт do_layout
EXTRA_TITLE_MM = {}       # id спецификации -> высота добавленной строки названия системы, мм
RESIZE_ROWS_ALL = 1       # SCHEDULE_RESIZE_ROWS: 1 = «Все» (замер; значение задаёт vks_core из vks_defaults)
SEGMENT_FRAME_MM = 6.2    # рамка части таблицы на листе сверх строк, мм (худший замер; задаёт vks_core)
BIP_RESIZE = "SCHEDULE_RESIZE_ROWS"          # параметры экземпляра ScheduleSheetInstance (не ViewSchedule)
BIP_ROW_H = "SCHEDULE_ROW_HEIGHT_INPUT"
_ROW_STATE = {"warned": False}
SEC_COLLECTION = None     # сборка блока: коллекция листов комплекта секции (ElementId) — новые листы туда, номера
                          # внутри неё (в разных коллекциях Revit 2025 номера могут повторяться — проверено 30.10.2026)

doc = None      # задаёт вызывающий модуль


def nat_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(u"(\\d+)", s or u"")]


def plan_capacity(caps, body, title):
    """Высоты частей (без заголовка) для Split: все, кроме последней."""
    hs, acc = [], 0.0
    for c in caps:
        h = c - title - SAFETY_MM
        if acc + h >= body - 0.01:
            break
        hs.append(max(h, 1.0))
        acc += h
    return hs


def id_int(eid):
    return int(eid.Value)          # Revit 2025: ElementId.Value (Int64)


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def mm(ft):
    return ft * FT


def ft(mm_):
    return mm_ / FT


class _Swallow(DB.IFailuresPreprocessor):
    __namespace__ = "SpecManager.Layout.v040"

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue


class Tx(object):
    def __init__(self, name):
        self.t = DB.Transaction(doc, name)

    def __enter__(self):
        o = self.t.GetFailureHandlingOptions()
        o.SetFailuresPreprocessor(_Swallow())
        self.t.SetFailureHandlingOptions(o)
        self.t.Start()
        return self.t

    def __exit__(self, et, ev, tb):
        if et is None:
            self.t.Commit()
        elif self.t.HasStarted() and not self.t.HasEnded():
            self.t.RollBack()
        return False


def tname(t):
    """Имя типоразмера. В IronPython FamilySymbol.Name часто недоступно."""
    if t is None:
        return u""
    for fn in (lambda: t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString(),
               lambda: DB.Element.Name.GetValue(t),
               lambda: t.Name):
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
    return u""


def is_revision_sched(vs):
    return bool(safe(lambda: vs.IsTitleblockRevisionSchedule, False)) or (vs.Name or u"").startswith(u"<")


def _collection_names():
    """Revit 2025+: коллекции листов (SheetCollection) -> {id: имя}. В старых версиях — пусто."""
    out = {}
    cls = getattr(DB, "SheetCollection", None)
    if cls is None:
        return out
    for c in safe(lambda: list(DB.FilteredElementCollector(doc).OfClass(cls)), []) or []:
        out[id_int(c.Id)] = (safe(lambda: c.Name) or u"").strip()
    return out


def _sheet_collection(s, cols):
    cid = safe(lambda: s.SheetCollectionId)
    return cols.get(id_int(cid)) if cid is not None and cols else None


def sheet_collection_name(s, cols=None):
    """Имя коллекции листа (Revit 2025+) или u""."""
    return _sheet_collection(s, cols if cols is not None else _collection_names()) or u""


def find_collection(name):
    """Коллекция листов (SheetCollection) по имени, без учёта регистра, или None."""
    cls = getattr(DB, "SheetCollection", None)
    if cls is None:
        return None
    want = (name or u"").strip().lower()
    for c in safe(lambda: list(DB.FilteredElementCollector(doc).OfClass(cls)), []) or []:
        if (safe(lambda: c.Name) or u"").strip().lower() == want:
            return c
    return None


def create_collection(name):
    """Новая коллекция листов (Revit 2025+). -> элемент или None (нет коллекций в этой версии Revit)."""
    cls = getattr(DB, "SheetCollection", None)
    if cls is None:
        return None
    return cls.Create(doc, name)


def set_sheet_collection(sh, cid):
    """Лист в коллекцию: свойство SheetCollectionId, иначе параметр SHEET_COLLECTION; затем сверка. -> True/False."""
    safe(lambda: setattr(sh, "SheetCollectionId", cid))
    cur = safe(lambda: sh.SheetCollectionId)
    if cur is not None and id_int(cur) == id_int(cid):
        return True
    bip = getattr(DB.BuiltInParameter, "SHEET_COLLECTION", None)
    p = safe(lambda: sh.get_Parameter(bip)) if bip is not None else None
    if p is not None and not p.IsReadOnly:
        safe(lambda: p.Set(cid))
    cur = safe(lambda: sh.SheetCollectionId)
    return cur is not None and id_int(cur) == id_int(cid)


def collection_sheets(cid):
    """Листы коллекции cid (ElementId)."""
    out = []
    for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet):
        c = safe(lambda: s.SheetCollectionId)
        if c is not None and id_int(c) == id_int(cid):
            out.append(s)
    return out


def list_sheet_folders():
    """Для окна: коллекции/папки листов проекта -> [(имя, число листов)]. Одно чтение при открытии вкладки."""
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if not s.IsPlaceholder]
    cnt = {}
    cols = _collection_names()
    org = safe(lambda: DB.BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc))
    for s in sheets:
        names = set()
        c = _sheet_collection(s, cols)
        if c:
            names.add(c)
        if org is not None:
            for fi in safe(lambda: list(org.GetFolderItems(s.Id)), []) or []:
                n = (fi.Name or u"").strip()
                if n:
                    names.add(n)
        v = (pstr(s, SHEET_SECTION_PARAM) or u"").strip()
        if v:
            names.add(v)
        for n in names:
            cnt[n] = cnt.get(n, 0) + 1
    return sorted(cnt.items(), key=lambda x: nat_key(x[0]))


def get_vks_sheets():
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if not s.IsPlaceholder]
    wanted = SHEET_FOLDER.strip().lower()
    found = []
    cols = _collection_names()
    if cols:
        for s in sheets:
            if (_sheet_collection(s, cols) or u"").lower() == wanted:
                found.append(s)
        if found:
            return sorted(found, key=lambda s: nat_key(s.SheetNumber))
    org = safe(lambda: DB.BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc))
    if org is not None:
        for s in sheets:
            names = [(fi.Name or u"").strip().lower() for fi in (safe(lambda: list(org.GetFolderItems(s.Id)), []) or [])]
            if wanted in names:
                found.append(s)
    if not found:
        for s in sheets:
            if (pstr(s, SHEET_SECTION_PARAM) or u"").strip().lower() == wanted:
                found.append(s)
    return sorted(found, key=lambda s: nat_key(s.SheetNumber))


def pstr(el, name):
    p = safe(lambda: el.LookupParameter(name))
    if p is None:
        return None
    if p.StorageType == DB.StorageType.String:
        return p.AsString()
    return safe(lambda: p.AsValueString())


def header_cell(vs):
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or hd.NumberOfRows < 1:
        return None, None
    r, c = hd.FirstRowNumber, hd.FirstColumnNumber
    return hd, (r, c)


def set_title(vs, text):
    hd, rc = header_cell(vs)
    if hd is None:
        return u"нет заголовка"
    cur = safe(lambda: hd.GetCellText(rc[0], rc[1]))
    if cur == text:
        return None
    try:
        hd.SetCellText(rc[0], rc[1], text)
        return None
    except Exception as ex:
        return u"заголовок не записался: {0}".format(ex)


def header_rows_mm(vs):
    """Высоты всех строк раздела «Заголовок», мм (по одной; число строк читается, не предполагается)."""
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or hd.NumberOfRows < 1:
        return []
    out = []
    for i in range(hd.NumberOfRows):
        h = safe(lambda: hd.GetRowHeight(hd.FirstRowNumber + i))
        out.append(mm(h) if h else 0.0)
    return out


def body_head_mm(vs):
    """Шапка граф в теле (если у спецификации включено «Показывать заголовки»): высота первой строки тела, мм.
    Повторяется на каждой части, как «Заголовок». 0 — шапки в теле нет."""
    if not safe(lambda: vs.Definition.ShowHeaders, False):
        return 0.0
    bs = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Body))
    h = safe(lambda: bs.GetRowHeight(bs.FirstRowNumber)) if bs is not None and bs.NumberOfRows > 0 else None
    return mm(h) if h else 0.0


def title_height_mm(vs):
    """Всё, что повторяется на каждой части таблицы на листе: Σ строк «Заголовка» (+ шапка граф в теле) + рамка
    части SEGMENT_FRAME_MM. Место под строки тела части = место на листе − это."""
    rows = header_rows_mm(vs)
    t = sum(rows) if rows else TITLE_MM
    return t + body_head_mm(vs) + SEGMENT_FRAME_MM


def set_header_heights(vs, top_mm, head_mm):
    """Высоты строк раздела «Заголовок» по одной (SetRowHeight). 1 строка — это «низ» (шапка граф); 2 и больше —
    первая «верх» (название, название системы / примечание), последняя «низ». 0 — как в шаблоне, не трогать.
    -> список ошибок (по-русски)."""
    hd = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Header))
    if hd is None or hd.NumberOfRows < 1:
        return []
    n, r0 = hd.NumberOfRows, hd.FirstRowNumber
    want = {}
    if head_mm and head_mm > 0:
        want[r0 + n - 1] = float(head_mm)
    if n >= 2 and top_mm and top_mm > 0:
        want[r0] = float(top_mm)
    errs = []
    for r, h in sorted(want.items()):
        cur = safe(lambda: hd.GetRowHeight(r))
        if cur is not None and abs(mm(cur) - h) < 0.005:
            continue
        try:
            hd.SetRowHeight(r, ft(h))
        except Exception as ex:
            errs.append(u"высота строки «Заголовка» {0:g} мм не записалась: {1}".format(h, ex))
    return errs


def _bip_param(el, name):
    """Параметр по имени BuiltInParameter (не по русскому имени): get_Parameter, иначе перебор по Definition."""
    bip = getattr(DB.BuiltInParameter, name, None)
    p = safe(lambda: el.get_Parameter(bip)) if bip is not None else None
    if p is not None:
        return p
    for q in safe(lambda: list(el.Parameters), []) or []:
        if u"%s" % (safe(lambda: q.Definition.BuiltInParameter) or u"") == name:
            return q
    return None


def _row_params(ssi):
    """Параметры экземпляра на листе (ScheduleSheetInstance): «Изменить размер строк» и «Высота строки»."""
    return _bip_param(ssi, BIP_RESIZE), _bip_param(ssi, BIP_ROW_H)


def apply_row_height(ssi, report=None):
    """На экземпляре спецификации на листе (каждая часть — свой экземпляр): SCHEDULE_RESIZE_ROWS = RESIZE_ROWS_ALL,
    затем SCHEDULE_ROW_HEIGHT_INPUT = ROW_MM. Действует на все строки тела (данные и заголовки групп), не на
    «Заголовок». ROW_MM = None («как в шаблоне») — не трогать. -> True, если записалось."""
    if ROW_MM is None or ssi is None:
        return False
    resize, height = _row_params(ssi)
    why = None
    if resize is None or height is None:
        why = u"у экземпляра спецификации на листе нет параметров {0} / {1}".format(BIP_RESIZE, BIP_ROW_H)
    elif resize.IsReadOnly or height.IsReadOnly:
        why = u"параметры {0} / {1} только для чтения".format(BIP_RESIZE, BIP_ROW_H)
    else:
        try:
            if resize.AsInteger() != RESIZE_ROWS_ALL:
                resize.Set(RESIZE_ROWS_ALL)
            want = DB.UnitUtils.ConvertToInternalUnits(float(ROW_MM), DB.UnitTypeId.Millimeters)
            if abs(height.AsDouble() - want) > 1e-9:
                height.Set(want)
            return True
        except Exception as ex:
            why = u"Revit не принял {0:g} мм ({1})".format(float(ROW_MM), ex)
    if report is not None and not _ROW_STATE["warned"]:
        _ROW_STATE["warned"] = True
        report.append(u"высота строк: {0} — такие части оставлены по шаблону".format(why))
    return False


def row_height_summary(sheets, managed_ids):
    """После раскладки: (сколько частей таблиц менеджера стоят на листах, у скольких высота строк = ROW_MM)."""
    total = ok = 0
    want = ft(float(ROW_MM)) if ROW_MM else None
    for sh in sheets:
        if not safe(lambda: sh.IsValidObject, False):
            continue
        for ssi in DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.ScheduleSheetInstance):
            if id_int(ssi.ScheduleId) not in managed_ids:
                continue
            total += 1
            if want is None:
                continue
            resize, height = _row_params(ssi)
            if resize is not None and height is not None and resize.AsInteger() == RESIZE_ROWS_ALL and \
                    abs(height.AsDouble() - want) < 1e-6:
                ok += 1
    return total, ok


class SheetGeom(object):
    def __init__(self, sheet, dx, dtop):
        self.sheet = sheet
        tb = self.titleblock()
        bb = safe(lambda: tb.get_BoundingBox(sheet)) if tb is not None else None
        if bb is None:
            self.left, self.top, self.bottom = ft(-400), ft(260), ft(BOTTOM_DEFAULT_MM)
        else:
            tname_ = tname(doc.GetElement(tb.GetTypeId()))
            b = BOTTOM_DEFAULT_MM
            for k, v in BOTTOM_MM.items():
                if k in tname_:
                    b = v
            self.left = bb.Min.X + dx
            self.top = bb.Max.Y - dtop
            self.bottom = bb.Min.Y + ft(b)
        self.cur = self.top

    def titleblock(self):
        tbs = list(DB.FilteredElementCollector(doc, self.sheet.Id).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                   .WhereElementIsNotElementType().ToElements())
        return tbs[0] if tbs else None

    def capacity(self):
        return mm(self.top - self.bottom)

    def free(self):
        return mm(self.cur - self.bottom)


def layout_offsets(sheets, managed_ids):
    """Отступы (от рамки) по уже стоящим спецификациям: самый частый вариант."""
    from collections import Counter
    cx, ct = Counter(), Counter()
    for sh in sheets:
        tbs = list(DB.FilteredElementCollector(doc, sh.Id).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                   .WhereElementIsNotElementType().ToElements())
        bb = safe(lambda: tbs[0].get_BoundingBox(sh)) if tbs else None
        if bb is None:
            continue
        tops = []
        for ssi in DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.ScheduleSheetInstance):
            vs = doc.GetElement(ssi.ScheduleId)
            if vs is None or is_revision_sched(vs):
                continue
            p = ssi.Point
            cx[round(mm(p.X - bb.Min.X), 1)] += 1
            tops.append(p.Y)
        if tops:
            ct[round(mm(bb.Max.Y - max(tops)), 1)] += 1
    dx = cx.most_common(1)[0][0] if cx else LEFT_FROM_FRAME_MM
    dtop = ct.most_common(1)[0][0] if ct else TOP_FROM_FRAME_MM
    return ft(dx), ft(dtop)


APPROVAL_RE = re.compile(u"^ADSK_Штамп боковой_\\d")   # фамилии/должности бокового штампа согласований
                                                       # («Инвентарный номер» — на всех листах, не трогаем)


def is_approval_param(name):
    return bool(APPROVAL_RE.match(name or u""))


def clear_approval(el):
    """Очистить фамилии/должности бокового штампа согласований (листы со 2-го). -> сколько очищено."""
    n = 0
    for p in safe(lambda: list(el.Parameters), []) or []:
        try:
            if p.IsReadOnly or p.StorageType != DB.StorageType.String or not is_approval_param(p.Definition.Name):
                continue
            if p.AsString():
                p.Set(u"")
                n += 1
        except Exception:
            pass            # параметр не записался — оставляем как есть, сборку не прерываем
    return n


def next_sheet_number(existing_numbers, last):
    m = re.match(u"^(.*?)(\\d+)(\\D*)$", last or u"")
    if not m:
        base, n, tail = (last or u"") + u"-", 0, u""
    else:
        base, n, tail = m.group(1), int(m.group(2)), m.group(3)
    while True:
        n += 1
        cand = u"{0}{1}{2}".format(base, n, tail)
        if cand not in existing_numbers:
            return cand


TYPE_BIPS = ("ELEM_TYPE_PARAM", "ELEM_FAMILY_AND_TYPE_PARAM", "ELEM_FAMILY_PARAM", "SYMBOL_ID_PARAM")
# не копировать с листа-образца: номер, имя и коллекция листа (0.14.2: «Коллекция листов» образца уводила новый лист
# блока из «1.4-Спецификации» туда, где номер 1 уже занят, — Revit откатывал шаг, 421-1-ОВ, 02.11.2026)
SHEET_OWN_BIPS = ("SHEET_NUMBER", "SHEET_NAME", "SHEET_COLLECTION")


def _is_type_param(p):
    """«Тип», «Семейство и типоразмер» и т.п. (их копирование возвращало новому штампу Форму 5 прошлого листа), а
    также номер, имя и коллекция листа — у нового листа они свои."""
    bip = u"%s" % (safe(lambda: p.Definition.BuiltInParameter) or u"")
    return bip in TYPE_BIPS or bip in SHEET_OWN_BIPS


def copy_params(src, dst, skip):
    for p in safe(lambda: list(src.Parameters), []) or []:
        try:
            nm = p.Definition.Name
            if nm in skip or is_approval_param(nm) or _is_type_param(p) or p.IsReadOnly or not p.HasValue:
                continue
            q = dst.LookupParameter(nm)
            if q is None or q.IsReadOnly:
                continue
            st = p.StorageType
            if st == DB.StorageType.String:
                q.Set(p.AsString() or u"")
            elif st == DB.StorageType.Integer:
                q.Set(p.AsInteger())
            elif st == DB.StorageType.Double:
                q.Set(p.AsDouble())
            elif st == DB.StorageType.ElementId:
                q.Set(p.AsElementId())
        except Exception:
            pass


def next_tb_type(tb):
    """Для продолжения: «Форма 5» (первый лист) -> «Форма 6» того же семейства."""
    t = doc.GetElement(tb.GetTypeId())
    name = tname(t)
    if u"Форма 5" not in name:
        return tb.GetTypeId()
    fam = safe(lambda: t.FamilyName)
    cands = [x for x in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
             .WhereElementIsElementType() if u"Форма 6" in tname(x)]
    same = [x for x in cands if safe(lambda: x.FamilyName) == fam]
    pick = same or cands
    return pick[0].Id if pick else tb.GetTypeId()


def create_sheet(template_geom, dx, dtop, report):
    src = template_geom.sheet
    tb = template_geom.titleblock()
    tb_type = next_tb_type(tb) if tb is not None else DB.ElementId.InvalidElementId
    sh = DB.ViewSheet.Create(doc, tb_type)
    if SEC_COLLECTION is not None:
        # блок: сначала в коллекцию секции, потом номер — уникальный внутри неё (Revit 2025: коллекция — своя
        # область номеров; перенос листа с занятым номером Revit молча не делает — сверяем)
        if not set_sheet_collection(sh, SEC_COLLECTION):
            raise Exception(u"лист не перенёсся в коллекцию блока")
        mine = [s for s in collection_sheets(SEC_COLLECTION) if s.Id != sh.Id]
        nums = set(s.SheetNumber for s in mine)
        last = src.SheetNumber if any(s.Id == src.Id for s in mine) else u"0"
        sh.SheetNumber = next_sheet_number(nums, last)
    else:
        nums = set(s.SheetNumber for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))
        sh.SheetNumber = next_sheet_number(nums, src.SheetNumber)
    sh.Name = src.Name or SHEET_NAME
    copy_params(src, sh, (u"Номер листа", u"Имя листа", u"Коллекция листов", u"Sheet Collection"))
    if SEC_COLLECTION is not None:
        # после копирования параметров лист должен остаться в коллекции блока (иначе номер конфликтует)
        if not set_sheet_collection(sh, SEC_COLLECTION):
            raise Exception(u"лист не остался в коллекции блока")
    cid = safe(lambda: src.SheetCollectionId)               # Revit 2025+: в ту же коллекцию листов
    if SEC_COLLECTION is None and cid is not None and cid != DB.ElementId.InvalidElementId:
        safe(lambda: setattr(sh, "SheetCollectionId", cid))
    doc.Regenerate()
    g = SheetGeom(sh, dx, dtop)
    new_tb = g.titleblock()
    if tb is not None and new_tb is not None:
        copy_params(tb, new_tb, (u"Номер листа", u"Имя листа") + tuple(SHEET_OTHER[1].keys()))
    normalize_sheet(sh, False, [])         # Форма 6, без штампа согласований (как у листов со 2-го)
    # «Ведомость изменений» встроена в штамп — Revit ставит её сам
    doc.Regenerate()
    report.append(u"добавлен лист {0}".format(sh.SheetNumber))
    return SheetGeom(sh, dx, dtop)


def first_sheet_type():
    """Тип основной надписи первого листа комплекта для листа без образца: «Форма 5» (сначала семейство
    ADSK_ОсновнаяНадпись), иначе тип, что чаще всего стоит на листах проекта. -> тип или None."""
    types = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                 .WhereElementIsElementType())
    cands = [t for t in types if SHEET_FIRST[0] in tname(t)]
    adsk = [t for t in cands if u"ОсновнаяНадпись" in (safe(lambda: t.FamilyName) or u"")]
    pick = adsk or cands
    if pick:
        return pick[0]
    cnt = {}
    for tb in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks) \
            .WhereElementIsNotElementType():
        k = id_int(tb.GetTypeId())
        cnt[k] = cnt.get(k, 0) + 1
    if cnt:
        best = max(cnt.items(), key=lambda x: x[1])[0]
        for t in types:
            if id_int(t.Id) == best:
                return t
    return types[0] if types else None


def create_first_sheet(cid, report):
    """Первый лист комплекта без листа-образца (0.15.0): основная надпись «Форма 5», штамп пустой, в коллекцию cid
    (ElementId или None); номер — первый свободный внутри коллекции. -> лист."""
    t = first_sheet_type()
    if t is None:
        raise Exception(u"в проекте нет семейства основной надписи — загрузите ADSK_ОсновнаяНадпись")
    sh = DB.ViewSheet.Create(doc, t.Id)
    if cid is not None:
        if not set_sheet_collection(sh, cid):
            raise Exception(u"новый лист не перенёсся в коллекцию")
        nums = set(s.SheetNumber for s in collection_sheets(cid) if s.Id != sh.Id)
    else:
        nums = set(s.SheetNumber for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet) if s.Id != sh.Id)
    sh.SheetNumber = next_sheet_number(nums, u"0")
    sh.Name = SHEET_NAME
    doc.Regenerate()
    normalize_sheet(sh, True, report)
    doc.Regenerate()
    report.append(u"создан первый лист {0} без образца: штамп «{1}», надписи штампа пустые — заполните".format(
        sh.SheetNumber, tname(doc.GetElement(sheet_titleblock(sh).GetTypeId())) if sheet_titleblock(sh) else u"—"))
    return sh


def sheet_titleblock(sh):
    tbs = list(DB.FilteredElementCollector(doc, sh.Id).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsNotElementType().ToElements())
    return tbs[0] if tbs else None


def tb_type_named(tb, part):
    t = doc.GetElement(tb.GetTypeId())
    fam = safe(lambda: t.FamilyName)
    cands = [x for x in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
             .WhereElementIsElementType() if part in tname(x)]
    same = [x for x in cands if safe(lambda: x.FamilyName) == fam]
    pick = same or cands
    return pick[0] if pick else None


def normalize_sheet(sh, first, report):
    """Штамп и шапка как в 414-1.2 + место ведомости изменений."""
    tb = sheet_titleblock(sh)
    if tb is None:
        report.append(u"лист {0}: нет штампа".format(sh.SheetNumber))
        return
    want, prm = SHEET_FIRST if first else SHEET_OTHER
    cur = tname(doc.GetElement(tb.GetTypeId()))
    if want not in cur:
        t = tb_type_named(tb, want)
        if t is not None:
            tb.ChangeTypeId(t.Id)
            report.append(u"лист {0}: штамп «{1}» → «{2}»".format(sh.SheetNumber, cur, tname(t)))
        else:
            report.append(u"лист {0}: нет типа штампа «{1}»".format(sh.SheetNumber, want))
    for k, v in prm.items():
        p = tb.LookupParameter(k)
        if p is None or p.IsReadOnly:
            continue
        try:
            if p.StorageType == DB.StorageType.Integer and p.AsInteger() != v:
                p.Set(v)
        except Exception:
            pass
    if not first:                          # штамп согласований — только на первом листе
        n = clear_approval(sh) + clear_approval(tb)
        if n:
            report.append(u"лист {0}: очищен боковой штамп согласований ({1} полей) — он только на первом листе".format(
                sh.SheetNumber, n))
    # «Ведомость изменений» встроена в штамп и ставится сама
    doc.Regenerate()


def unsplit(vs):
    if not safe(lambda: vs.IsSplit(), False):
        return
    for _ in range(60):
        n = safe(lambda: vs.GetSegmentCount(), 1) or 1
        if n <= 1:
            return
        ok = False
        for fn in (lambda: vs.MergeSegments(n - 2, n - 1), lambda: vs.DeleteSegment(n - 1)):
            try:
                fn()
                ok = True
                break
            except Exception:
                pass
        if not ok:
            raise Exception(u"не удалось объединить части спецификации «{0}»".format(vs.Name))


def do_split(vs, heights):
    """Split: высоты частей без заголовка; последняя часть — остаток."""
    vs.Split(List[float]([ft(x) for x in heights]))
    if heights and vs.GetSegmentCount() == len(heights):
        # в этой версии список задаёт все части — добавляем «остаток»
        unsplit(vs)
        vs.Split(List[float]([ft(x) for x in heights] + [ft(100000.0)]))


def place(vs, g, seg=None):
    origin = DB.XYZ(g.left, g.cur, 0)
    if seg is None:
        ssi = DB.ScheduleSheetInstance.Create(doc, g.sheet.Id, vs.Id, origin)
    else:
        ssi = DB.ScheduleSheetInstance.Create(doc, g.sheet.Id, vs.Id, origin, seg)
    apply_row_height(ssi, getattr(g, "report", None))
    doc.Regenerate()
    p = ssi.Point
    if abs(p.X - g.left) > 1e-6 or abs(p.Y - g.cur) > 1e-6:
        ssi.Point = origin
        doc.Regenerate()
    bb = ssi.get_BoundingBox(g.sheet)
    margin = max(0.0, ssi.Point.X - bb.Min.X)
    h = ssi.Point.Y - (bb.Min.Y + margin)
    return ssi, mm(h)


MIN_GROUP_ROWS = 4      # меньше строк под заголовком группы внизу листа — группа переносится на новый лист


def body_rows(vs):
    """Строки тела спецификации на листе: [(высота мм, 'grp' | 'data')]. 'grp' — строка во всю ширину
    (заголовок группы или пустая строка) — по высоте обычная строка. Высоты: заданная на «Листах» (ROW_MM),
    иначе реальные из вида (с переносом текста), иначе базовые. None — если не прочитать."""
    body = safe(lambda: vs.GetTableData().GetSectionData(DB.SectionType.Body))
    if body is None:
        return None
    n = body.NumberOfRows
    if ROW_MM:
        # «Высота строки» экземпляра на листе — на все строки тела (данные и заголовки групп); ни GetRowHeight,
        # ни высоты вида её не показывают (замер 14.10.2026) — считаем по заданной
        bh = [float(ROW_MM)] * n
    else:
        bh = safe(lambda: [mm(x) for x in vs.GetScheduleHeightsOnSheet().GetBodyRowHeights()])
        if not bh or len(bh) != n:   # базовые высоты тела из вида (Ф3)
            bh = [mm(safe(lambda: body.GetRowHeight(body.FirstRowNumber + i), 0.0) or 0.0) for i in range(n)]
    if not bh or len(bh) != n or not all(x > 0 for x in bh):
        return None
    c0 = body.FirstColumnNumber
    c1 = c0 + body.NumberOfColumns - 1
    out = []
    skip = 1 if body_head_mm(vs) > 0 else 0     # шапка граф в теле повторяется на каждой части — она в «заголовке» t
    for i in range(skip, n):
        r = body.FirstRowNumber + i
        mc = safe(lambda: body.GetMergedCell(r, c0))
        full = mc is not None and mc.Left <= c0 and mc.Right >= c1 and c1 > c0
        out.append((bh[i], "grp" if full else "data"))
    return out


def _fix_break(kinds, s, b, first):
    """Конец части перед строкой b (часть начинается с s). Заголовок группы без строк или с 1–3 строками
    внизу листа уходит на следующий лист вместе с группой; законченная группа (последние строки) остаётся.
    -> (b, push): push — первую часть спецификации целиком на следующий лист."""
    def ndata(i, j):
        return sum(1 for x in range(i, j) if kinds[x] == "data")
    g = -1
    for i in range(b - 1, s - 1, -1):
        if kinds[i] == "grp":
            g = i
            break
    if g < 0:
        # заголовков в части нет: «заголовок» — название спецификации над первой частью
        return b, bool(first and ndata(s, b) < MIN_GROUP_ROWS)
    complete = ndata(b, _next_grp(kinds, b)) == 0       # группа кончается ровно на разрыве
    if complete or ndata(g + 1, b) >= MIN_GROUP_ROWS:
        return b, False
    nb = g
    while nb > s and kinds[nb - 1] == "grp":             # заголовки уровнем выше и пустые строки — тоже
        nb -= 1
    if nb <= s:
        return b, bool(first)
    return nb, False


def _next_grp(kinds, b):
    for i in range(b, len(kinds)):
        if kinds[i] == "grp":
            return i
    return len(kinds)


def plan_rows(rows, cap):
    """Разбивка строк по частям: [(s, b)], push. cap(k) — место под строки части k, мм."""
    bh = [r[0] for r in rows]
    kinds = [r[1] for r in rows]
    n = len(rows)
    segs, s, k = [], 0, 0
    while s < n:
        c = cap(k)
        acc, b = 0.0, s
        while b < n and acc + bh[b] <= c + 1e-6:
            acc += bh[b]
            b += 1
        if b >= n:
            segs.append((s, n))
            break
        if b == s:
            b = s + 1
        b, push = _fix_break(kinds, s, b, k == 0)
        if push:
            return segs, True
        segs.append((s, b))
        s = b
        k += 1
    return segs, False


class Layout(object):
    def __init__(self, sheets, dx, dtop, report):
        self.dx, self.dtop, self.report = dx, dtop, report
        self.geoms = [SheetGeom(s, dx, dtop) for s in sheets]
        for g_ in self.geoms:
            g_.report = report
        self.i = 0
        self.used = set()
        self.placements = []   # (vs name, seg, sheet number)

    @property
    def g(self):
        return self.geoms[self.i]

    def ensure(self, i):
        while i >= len(self.geoms):
            ng = create_sheet(self.geoms[-1], self.dx, self.dtop, self.report)
            ng.report = self.report
            self.geoms.append(ng)
        return self.geoms[i]

    def advance(self):
        self.i += 1
        self.ensure(self.i)
        self.g.cur = self.g.top

    def put(self, vs):
        unsplit(vs)
        t = title_height_mm(vs)
        g = self.g
        if g.free() < MIN_PIECE_MM and g.cur < g.top - 1e-6:
            self.advance()
            g = self.g
        ssi, h = place(vs, g)
        if h <= g.free() + 0.3:
            g.cur -= ft(h)
            self.used.add(self.i)
            self.placements.append((vs.Name, -1, g.sheet.SheetNumber))
            return
        rows = body_rows(vs)              # пока стоит на листе: высоты строк — с учётом «Высоты строки»
        doc.Delete(ssi.Id)
        if rows and self._put_rows(vs, t, rows):
            return
        g = self.g
        body = h - t
        start_i, start_cur = self.i, g.cur
        caps = [g.free()]
        heights = None
        for attempt in range(8):
            j = len(caps)
            while sum(c - t for c in caps) < body + 5 or len(caps) < 2:
                caps.append(self.ensure(start_i + j).capacity())
                j += 1
            heights = plan_capacity(caps, body, t) if heights is None else heights
            unsplit(vs)
            do_split(vs, heights)
            doc.Regenerate()
            n = vs.GetSegmentCount()
            self.i = start_i
            self.g.cur = start_cur
            ids, overflow = [], None
            for s in range(n):
                if s > 0:
                    self.i += 1
                    self.ensure(self.i)
                    self.g.cur = self.g.top
                ssi, hs = place(vs, self.g, s)
                ids.append(ssi.Id)
                if hs > self.g.free() + 0.3:
                    overflow = (s, hs - self.g.free())
                    break
                self.g.cur -= ft(hs)
            if overflow is None:
                for k in range(start_i, self.i + 1):
                    self.used.add(k)
                seg_sheet = start_i
                for s in range(n):
                    self.placements.append((vs.Name, s, self.geoms[seg_sheet + s].sheet.SheetNumber))
                return
            for x in ids:
                doc.Delete(x)
            s, over = overflow
            if s < len(heights):
                heights[s] = max(1.0, heights[s] - over - SAFETY_MM)
            else:
                heights.append(max(1.0, self.ensure(start_i + s).capacity() - t - SAFETY_MM)
                               if s > 0 else max(1.0, caps[0] - t - SAFETY_MM))
        raise Exception(u"не удалось разложить «{0}» по листам".format(vs.Name))


def layout_put_rows(self, vs, t, rows):
    """Перенос по строкам: разрывы считаются по реальным высотам строк, заголовок группы не отрывается
    от строк (см. _fix_break). False — не вышло, работает прежний способ."""
    bh = [r[0] for r in rows]
    cut = {}
    pushed = False
    for attempt in range(10):
        start_i, start_cur = self.i, self.g.cur
        start_free = self.g.free()

        def cap(k):
            c = start_free if k == 0 else self.ensure(start_i + k).capacity()
            return c - t - SAFETY_MM - cut.get(k, 0.0)
        segs, push = plan_rows(rows, cap)
        if push:
            if pushed or start_cur >= self.g.top - 1e-6:
                return False
            pushed = True
            self.advance()                       # начало спецификации — на новый лист
            cut = {}
            continue
        if len(segs) < 2:                        # после переноса на новый лист влезла целиком
            unsplit(vs)
            ssi, hs = place(vs, self.g)
            if hs <= self.g.free() + 0.3:
                self.g.cur -= ft(hs)
                self.used.add(self.i)
                self.placements.append((vs.Name, -1, self.g.sheet.SheetNumber))
                return True
            doc.Delete(ssi.Id)
            cut[0] = cut.get(0, 0.0) + hs - self.g.free() + SAFETY_MM
            continue
        heights = [sum(bh[a:b]) + 0.1 for a, b in segs[:-1]]
        unsplit(vs)
        do_split(vs, heights)
        doc.Regenerate()
        n = vs.GetSegmentCount()
        if n != len(segs):
            unsplit(vs)
            return False
        ids, overflow = [], None
        for si in range(n):
            if si > 0:
                self.i += 1
                self.ensure(self.i)
                self.g.cur = self.g.top
            ssi, hs = place(vs, self.g, si)
            ids.append(ssi.Id)
            if hs > self.g.free() + 0.3:
                overflow = (si, hs - self.g.free())
                break
            self.g.cur -= ft(hs)
        if overflow is None:
            for k in range(start_i, self.i + 1):
                self.used.add(k)
            for si in range(n):
                self.placements.append((vs.Name, si, self.geoms[start_i + si].sheet.SheetNumber))
            return True
        for x in ids:
            doc.Delete(x)
        unsplit(vs)
        self.i = start_i
        self.g.cur = start_cur
        si, over = overflow
        cut[si] = cut.get(si, 0.0) + over + SAFETY_MM
    return False


Layout._put_rows = layout_put_rows


GROUP_GAP_MM = 20.0        # отступ перед новой группой на листе с перенесённым «хвостом» прошлой группы
TAIL_MAX_FRAC = 1.0 / 3    # «хвост» — перенесённое на лист (конец спецификации или целые небольшие спецификации
                           # прошлой группы, начавшейся на предыдущем листе), занимает не больше трети листа


def layout_gap(lay, gap_mm):
    """Отступ перед следующей спецификацией (если на листе уже что-то стоит). Не влезает — новый лист."""
    g = lay.g
    if g.cur >= g.top - 1e-6 or gap_mm <= 0:
        return
    if g.free() - gap_mm >= MIN_PIECE_MM + 10:
        g.cur -= ft(gap_mm)
    else:
        lay.advance()


def layout_new_group(lay, opts=None):
    """Начало новой группы систем по настройкам вкладки «Листы» (opts):
    group_new_sheet — с нового листа; но при tail_on, если прошлая группа на текущий лист только перенесена
    (началась на предыдущем листе) и занимает тут не больше tail_pct % листа, — отступ group_gap и дальше
    на этом же листе. group_new_sheet = False — все группы подряд с отступом group_gap."""
    o = opts or {}
    gap = float(o.get("group_gap", GROUP_GAP_MM))
    g = lay.g
    if g.cur >= g.top - 1e-6:
        return
    if not o.get("group_new_sheet", True):
        lay.gap(gap)
        return
    used = mm(g.top - g.cur)
    start = getattr(lay, "group_start", None)
    carried = start is not None and lay.i > start
    frac = float(o.get("tail_pct", TAIL_MAX_FRAC * 100)) / 100.0
    if o.get("tail_on", True) and carried and used <= g.capacity() * frac:
        if g.free() - gap >= MIN_PIECE_MM + 10:
            g.cur -= ft(gap)
            return
    lay.advance()


Layout.gap = layout_gap


def layout_new_sheet(lay):
    """С нового листа (разделы ОВ: флажок раздела / таблицы). Лист пуст — остаёмся на нём."""
    g = lay.g
    if g.cur >= g.top - 1e-6:
        return
    lay.advance()


Layout.new_sheet = layout_new_sheet


def layout_mark_group_start(lay, n_before):
    """После первой спецификации группы: лист, на котором группа началась (по первой её части)."""
    if n_before >= len(lay.placements):
        return
    shn = lay.placements[n_before][2]
    for k, g in enumerate(lay.geoms):
        if g.sheet.SheetNumber == shn:
            lay.group_start = k
            return


Layout.mark_group_start = layout_mark_group_start


def layout_put_whole(lay, vs):
    """Целиком, без деления (таблица материалов: раздел «Заголовок» Revit между листами не разрывает).
    Не влезает на текущий лист — на следующий."""
    unsplit(vs)
    g = lay.g
    ssi, h = place(vs, g)
    if h > g.free() + 0.3 and g.cur < g.top - 1e-6:
        doc.Delete(ssi.Id)
        lay.advance()
        g = lay.g
        ssi, h = place(vs, g)
    if h > g.free() + 0.3:
        lay.report.append(u"«{0}» выше листа — выступает за поле".format(vs.Name))
    g.cur -= ft(min(h, g.free()))
    lay.used.add(lay.i)
    lay.placements.append((vs.Name, -1, g.sheet.SheetNumber))


Layout.put_whole = layout_put_whole
Layout.new_group = layout_new_group

