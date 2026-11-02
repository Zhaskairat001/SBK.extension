# -*- coding: utf-8 -*-
"""Менеджер спецификаций — разбор строк спецификаций для нумерации позиций (ADSK_Позиция).
Перенесено из кнопки «Нумерация ВК.С» (NumerateVKS), чтобы менеджер работал без неё.
Кнопка «Нумерация ВК.С» остаётся отдельной и этот файл не использует.

Автонумерация позиций в спецификациях, размещённых на листах ВК.С.

Номер позиции = число из названия спецификации + номер строки:
    "13.Сантехнические приборы К1"  ->  13.1, 13.2, 13.3 ...
    "1.Оборудование ..."            ->  1.1, 1.2, 1.3 ...

Порядок и объединение строк берутся из самой спецификации
(сортировка/группировка, галочка «Для каждого экземпляра»),
поэтому номера совпадают с тем, что видно на листе.
"""
from __future__ import print_function
import re

from Autodesk.Revit import DB

# ============================ НАСТРОЙКИ ============================
SHEET_FOLDER = u"ВК.С"         # папка листов в Диспетчере проекта
PARAM_NAME = u"ADSK_Позиция"   # параметр, в который пишется номер
SEPARATOR = u"."               # 13 + "." + 1  ->  13.1
# ===================================================================

PREFIX_RE = re.compile(u"^\\s*(\\d+)")
TOKEN_FMT = u"~#{0}#~"
TOKEN_RE = re.compile(u"^~#(-?\\d+)#~$")


# ------------------------------------------------------------------
# Чистая логика (без Revit API) — разбиение строк на позиции
# ------------------------------------------------------------------
def schedule_prefix(name):
    """'13.Сантехнические приборы К1' -> '13'; без номера -> None."""
    m = PREFIX_RE.match(name or u"")
    return m.group(1) if m else None


def token_id(text):
    m = TOKEN_RE.match((text or u"").strip())
    return int(m.group(1)) if m else None


def detect_columns(rows, field_order, pos_fid, sort_fids):
    """Возвращает (pos_col, sort_cols, approx)."""
    ncols = len(rows[0]) if rows else 0
    pos_col, sort_cols, approx = None, None, False

    if len(field_order) == ncols:
        col = dict((f, i) for i, f in enumerate(field_order))
        pos_col = col.get(pos_fid)
        sort_cols = [col[f] for f in sort_fids if f in col]
        if len(sort_cols) != len(sort_fids):
            sort_cols = None

    def tok_count(c):
        return sum(1 for r in rows if token_id(r[c]) is not None)

    if pos_col is None or tok_count(pos_col) == 0:
        best = max(range(ncols), key=tok_count) if ncols else None
        if best is None or tok_count(best) == 0:
            raise Exception(u"не удалось сопоставить строки с элементами")
        pos_col = best

    if sort_cols is None:
        sort_cols = [c for c in range(ncols) if c != pos_col]
        approx = True
    return pos_col, sort_cols, approx


def build_groups(rows, pos_col, sort_cols, itemized, valid_ids):
    """Строки «для каждого экземпляра» -> строки спецификации (позиции).

    Если спецификация не «для каждого экземпляра», Revit объединяет
    подряд идущие элементы с одинаковыми значениями полей сортировки.
    Каждая группа — список id целевых элементов (None — не сопоставлен).
    """
    groups = []
    prev = None
    for r in rows:
        key = tuple(r[c] for c in sort_cols)
        if itemized or not groups or key != prev:
            groups.append([])
        prev = key
        tid = token_id(r[pos_col])
        groups[-1].append(tid if (tid is not None and tid in valid_ids) else None)
    return groups


def assign_numbers(prefix, groups):
    """-> (dict id->номер, set id, попавших в несколько строк)."""
    values, multi = {}, set()
    for n, g in enumerate(groups, 1):
        value = u"{0}{1}{2}".format(prefix, SEPARATOR, n)
        for tid in g:
            if tid is None:
                continue
            if tid in values:
                if values[tid] != value:
                    multi.add(tid)
                continue
            values[tid] = value
    return values, multi


# ------------------------------------------------------------------
# Revit
# ------------------------------------------------------------------
doc = None      # задаёт vks_core перед вызовом


def id_int(eid):
    v = getattr(eid, "Value", None)          # Revit 2024+
    if v is None:
        v = eid.IntegerValue
    return int(v)


def fid_int(fid):
    v = getattr(fid, "IntegerValue", None)
    if v is None:
        v = fid.Value
    return int(v)


class _SwallowWarnings(DB.IFailuresPreprocessor):
    __namespace__ = "SpecManager.Numerator"

    def PreprocessFailures(self, fa):
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue


def _quiet(t):
    opts = t.GetFailureHandlingOptions()
    opts.SetFailuresPreprocessor(_SwallowWarnings())
    opts.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(opts)


class SchedInfo(object):
    def __init__(self, view, prefix):
        self.view = view
        self.prefix = prefix
        self.sheets = []

    @property
    def name(self):
        return u"{0}        [лист {1}]".format(self.view.Name, u"; ".join(self.sheets))


def get_vks_sheets():
    sheets = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
              if not s.IsPlaceholder]
    wanted = SHEET_FOLDER.strip().lower()
    found = []

    # 1) по папкам Диспетчера проекта
    try:
        org = DB.BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
    except Exception:
        org = None
    if org is not None:
        for s in sheets:
            try:
                names = [(fi.Name or u"").strip().lower() for fi in org.GetFolderItems(s.Id)]
            except Exception:
                names = []
            if wanted in names:
                found.append(s)

    # 2) запасной вариант — любой текстовый параметр листа = "ВК.С"
    if not found:
        for s in sheets:
            for p in s.Parameters:
                try:
                    if p.StorageType == DB.StorageType.String and \
                            (p.AsString() or u"").strip().lower() == wanted:
                        found.append(s)
                        break
                except Exception:
                    pass
    return found


def collect_schedules(sheets):
    infos, no_number = {}, set()
    for sh in sorted(sheets, key=lambda s: s.SheetNumber):
        for ssi in DB.FilteredElementCollector(doc, sh.Id).OfClass(DB.ScheduleSheetInstance):
            if ssi.IsTitleblockRevisionSchedule:
                continue
            vs = doc.GetElement(ssi.ScheduleId)
            if not isinstance(vs, DB.ViewSchedule):
                continue
            if vs.Definition.IsKeySchedule or getattr(vs, "IsInternalKeynoteSchedule", False):
                continue
            prefix = schedule_prefix(vs.Name)
            if prefix is None:
                no_number.add(vs.Name)
                continue
            k = id_int(vs.Id)
            if k not in infos:
                infos[k] = SchedInfo(vs, prefix)
            label = u"{0} - {1}".format(sh.SheetNumber, sh.Name)
            if label not in infos[k].sheets:
                infos[k].sheets.append(label)
    result = sorted(infos.values(), key=lambda i: (int(i.prefix), i.view.Name))
    return result, sorted(no_number)


def get_target(el):
    """(элемент для записи, параметр): экземпляр, иначе его тип."""
    p = el.LookupParameter(PARAM_NAME)
    if p is not None and not p.IsReadOnly:
        return el, p
    tid = el.GetTypeId()
    if tid is not None and tid != DB.ElementId.InvalidElementId:
        t = doc.GetElement(tid)
        if t is not None:
            tp = t.LookupParameter(PARAM_NAME)
            if tp is not None and not tp.IsReadOnly:
                return t, tp
    return None, None


def find_field(defn, name):
    for i in range(defn.GetFieldCount()):
        f = defn.GetField(i)
        try:
            if f.GetName() == name:
                return f
        except Exception:
            pass
    return None


def add_field(defn, name):
    for sf in defn.GetSchedulableFields():
        try:
            if sf.GetName(doc) == name:
                return defn.AddField(sf)
        except Exception:
            pass
    return None


def read_body(vs):
    body = vs.GetTableData().GetSectionData(DB.SectionType.Body)
    rows = []
    for r in range(body.FirstRowNumber, body.LastRowNumber + 1):
        rows.append([vs.GetCellText(DB.SectionType.Body, r, c)
                     for c in range(body.FirstColumnNumber, body.LastColumnNumber + 1)])
    return rows


def map_rows(vs):
    """Определяет, какие элементы стоят в каждой строке спецификации.

    Во временной транзакции (откатывается):
      * каждому элементу пишется уникальная метка в PARAM_NAME;
      * копия спецификации переводится в режим «для каждого экземпляра»,
        все поля показываются, заголовки/итоги отключаются;
      * по меткам читается порядок элементов, по полям сортировки —
        какие элементы Revit объединяет в одну строку.
    """
    notes = []
    itemized = vs.Definition.IsItemized
    elems = list(DB.FilteredElementCollector(doc, vs.Id).ToElements())
    targets, no_param = {}, 0

    t = DB.Transaction(doc, u"tmp: разметка строк")
    _quiet(t)
    t.Start()
    try:
        for el in elems:
            tgt, p = get_target(el)
            if tgt is None:
                no_param += 1
                continue
            k = id_int(tgt.Id)
            if k in targets:
                continue
            if p.StorageType != DB.StorageType.String:
                raise Exception(u"параметр {0} не текстовый".format(PARAM_NAME))
            try:
                p.Set(TOKEN_FMT.format(k))
                targets[k] = tgt.Id
            except Exception:
                no_param += 1

        if no_param:
            notes.append(u"{0} эл. без параметра {1} (или только чтение)".format(no_param, PARAM_NAME))
        if not targets:
            return [], targets, notes + [u"нет элементов, куда можно записать номер"]

        sched = vs
        try:
            if vs.CanViewBeDuplicated(DB.ViewDuplicateOption.Duplicate):
                sched = doc.GetElement(vs.Duplicate(DB.ViewDuplicateOption.Duplicate))
        except Exception:
            sched = vs

        d = sched.Definition
        pos_field = find_field(d, PARAM_NAME) or add_field(d, PARAM_NAME)
        if pos_field is None:
            raise Exception(u"не удалось вывести {0} в спецификацию".format(PARAM_NAME))
        pos_fid = fid_int(pos_field.FieldId)

        i = d.GetSortGroupFieldCount() - 1
        while i >= 0:
            sg = d.GetSortGroupField(i)
            if fid_int(sg.FieldId) == pos_fid:
                d.RemoveSortGroupField(i)
                notes.append(u"{0} стоит в сортировке — проверьте порядок".format(PARAM_NAME))
            else:
                sg.ShowHeader = False
                sg.ShowFooter = False
                sg.ShowBlankLine = False
                d.SetSortGroupField(i, sg)
            i -= 1
        sort_fids = [fid_int(d.GetSortGroupField(j).FieldId)
                     for j in range(d.GetSortGroupFieldCount())]

        d.IsItemized = True
        for attr in ("ShowGrandTotal", "ShowHeaders"):
            try:
                setattr(d, attr, False)
            except Exception:
                pass
        for j in range(d.GetFieldCount()):
            f = d.GetField(j)
            if f.IsHidden:
                f.IsHidden = False

        doc.Regenerate()
        refresh = getattr(sched, "RefreshData", None)
        if refresh is not None:
            try:
                refresh()
            except Exception:
                pass

        rows = read_body(sched)
        order = [fid_int(x) for x in d.GetFieldOrder()]
    finally:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()

    if not rows:
        return [], targets, notes + [u"спецификация пустая"]

    pos_col, sort_cols, approx = detect_columns(rows, order, pos_fid, sort_fids)
    if approx and not itemized:
        notes.append(u"объединение строк определено приблизительно")
    groups = build_groups(rows, pos_col, sort_cols, itemized, targets)
    return groups, targets, notes


def ws_blocked(eid):
    if not doc.IsWorkshared:
        return None
    try:
        if DB.WorksharingUtils.GetCheckoutStatus(doc, eid) == DB.CheckoutStatus.OwnedByOtherUser:
            owner = u""
            try:
                owner = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, eid).Owner
            except Exception:
                pass
            return u"занят: {0}".format(owner) if owner else u"занят другим пользователем"
        st = DB.WorksharingUtils.GetModelUpdatesStatus(doc, eid)
        if st in (DB.ModelUpdatesStatus.UpdatedInCentral, DB.ModelUpdatesStatus.DeletedInCentral):
            return u"изменён в ФХ — синхронизируйтесь"
    except Exception:
        pass
    return None


def process(info, assigned, problems):
    vs = info.view
    res = {"name": vs.Name, "rows": 0, "written": 0, "same": 0, "skipped": 0, "notes": []}
    try:
        groups, targets, notes = map_rows(vs)
    except Exception as ex:
        res["notes"].append(u"ошибка: {0}".format(ex))
        return res
    res["notes"].extend(notes)
    res["rows"] = len(groups)
    if not groups:
        return res

    unmapped = sum(1 for g in groups if all(x is None for x in g))
    if unmapped:
        res["notes"].append(u"{0} строк без записываемых элементов".format(unmapped))

    values, multi = assign_numbers(info.prefix, groups)
    if multi:
        res["notes"].append(u"{0} эл. (тип) попадают в несколько строк — взят первый номер".format(len(multi)))

    t = DB.Transaction(doc, u"Нумерация: {0}".format(vs.Name))
    _quiet(t)
    t.Start()
    try:
        written = []
        for tid, value in values.items():
            prev = assigned.get(tid)
            if prev is not None and prev[1] != value:
                res["skipped"] += 1
                problems.append((targets[tid], u"уже пронумерован в «{0}» как {1}".format(prev[0], prev[1])))
                continue
            el = doc.GetElement(targets[tid])
            p = el.LookupParameter(PARAM_NAME) if el is not None else None
            if p is None or p.IsReadOnly:
                res["skipped"] += 1
                continue
            if (p.AsString() or u"") == value:
                res["same"] += 1
                assigned[tid] = (vs.Name, value)
                continue
            why = ws_blocked(el.Id)
            if why:
                res["skipped"] += 1
                problems.append((el.Id, why))
                continue
            try:
                p.Set(value)
                written.append(tid)
                assigned[tid] = (vs.Name, value)
            except Exception as ex:
                res["skipped"] += 1
                problems.append((el.Id, u"не записалось: {0}".format(ex)))
        status = t.Commit()
        if status == DB.TransactionStatus.Committed:
            res["written"] = len(written)
        else:
            res["notes"].append(u"транзакция не применилась ({0})".format(status))
            for tid in written:
                assigned.pop(tid, None)
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return res
