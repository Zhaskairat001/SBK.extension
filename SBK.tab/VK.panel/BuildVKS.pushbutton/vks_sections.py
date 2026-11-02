# -*- coding: utf-8 -*-
"""Менеджер спецификаций — сборка по разделам (ОВ) из шаблонов «О_…».

Раздел (Отопление, Вентиляция, …) → таблицы (копии шаблонов в заданном порядке) → части (заголовки по полю деления
раздела: ADSK_Группирование / ИмяСистемы) → строки → позиции. Образец — модель 414-ОВ (листы СО-1…СО-22).

Служебные ключи пишет кнопка:
  ADSK_Позиция_Комплект   = номер раздела × KIT_BASE + номер части (фильтр раздела — диапазон, порядок частей);
  ADSK_Позиция_Сортировка = Комплект + ранг строки / DIV (порядок строк внутри части, главный элемент — первым).
Сортировка каждой таблицы: Комплект → поле деления (заголовок) → Сортировка → ADSK_Наименование.
ADSK_Система_Обозначение здесь не нужен и не пишется.

Модуль не импортирует vks_core: run() получает его модулем (C). Чистые функции (порядок частей, ранги, номера
позиций) не зависят от Revit — их можно проверять заглушками CPython.
"""
from __future__ import print_function
import re
import copy
import time
import traceback

try:
    from Autodesk.Revit import DB
except Exception:            # проверка логики вне Revit
    DB = None

P_SYS = u"ИмяСистемы"
P_GRP = u"ADSK_Группирование"
P_KIT = u"ADSK_Позиция_Комплект"
P_SORT = u"ADSK_Позиция_Сортировка"
P_POS = u"ADSK_Позиция"
P_NAME = u"ADSK_Наименование"
P_MARK = u"ADSK_Марка"

KIT_BASE = 1000              # Комплект = Р × 1000 + k: до 999 частей в разделе
MAX_FILTERS = 8              # лимит фильтров спецификации Revit 2025.4 (замер 30.10.2026, claude/СЕКЦИИ_ПЛАН.md)
POS_FMT = u"{р}.{n}"
SYS_ORDER = [u"П", u"В", u"ДП", u"ДВ", u"ВЕ"]
MAIN_KEYS = [u"вентилятор", u"установка", u"насос", u"радиатор", u"конвектор", u"кондиционер", u"котел", u"котёл",
             u"теплообменник", u"агрегат", u"завеса", u"калорифер", u"холодильная машина", u"чиллер"]
POS_MODES = [("seq", u"сквозные раздела"), ("sys", u"по системе"), ("none", u"нет (очистить)")]


# ------------------------------------------------------------------
# чистые функции (без Revit)
# ------------------------------------------------------------------
def nat_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(u"(\\d+)", u"%s" % (s or u""))]


def sec_number(sections, i):
    """Номер раздела в позиции: вручную (num > 0) или по порядку разделов (1, 2, …)."""
    try:
        n = int(sections[i].get("num") or 0)
    except Exception:
        n = 0
    return n if n > 0 else i + 1


def sys_label(v):
    """«П 1» → «П1» (позиция «по системе»)."""
    return re.sub(u"\\s+", u"", u"%s" % (v or u""))


def _sys_part_key(v, order=None):
    order = order or SYS_ORDER
    m = re.match(u"^\\s*([^\\d\\s,]*)\\s*(\\d*)(.*)$", v or u"")
    letters, num, rest = m.group(1), m.group(2), m.group(3)
    li = order.index(letters) if letters in order else len(order)
    return (li, letters.lower(), int(num) if num else 0, nat_key(rest))


def order_parts(values, split, manual=None, sys_order=None):
    """Порядок частей раздела: ручной список (что в нём есть) → по умолчанию; пустое значение — в конце.
    ИмяСистемы — по сокращению П → В → ДП → ДВ → ВЕ → прочие, внутри по номеру; остальное — естественный порядок."""
    vals = set(values)
    out = [v for v in (manual or []) if v in vals]
    rest = [v for v in vals if v not in out and v != u""]
    if split == P_SYS:
        rest.sort(key=lambda v: _sys_part_key(v, sys_order))
    else:
        rest.sort(key=nat_key)
    out.extend(rest)
    if u"" in vals and u"" not in out:
        out.append(u"")
    return out


def dense_rank(entries):
    """entries: [(группа, ключ сортировки, id)] -> ({id: ранг 1…}, наибольший ранг). Ранг — внутри группы,
    одинаковый ключ — один ранг (одна строка спецификации)."""
    by = {}
    for g, k, i in entries:
        by.setdefault(g, []).append((k, i))
    out, top = {}, 0
    for g, lst in by.items():
        uniq = sorted(set(k for k, i in lst))
        r = dict((k, n + 1) for n, k in enumerate(uniq))
        for k, i in lst:
            out[i] = r[k]
        top = max(top, len(uniq))
    return out, top


def kit_value(p, k):
    return p * KIT_BASE + k


def sort_value(kit, r, div):
    return round(kit + float(r) / div, 6)


def rank_div(top):
    """Делитель ранга: 1000 (Сортировка 2001.003), больше 999 строк в части — 10000."""
    return 1000 if top < 1000 else 10000


def pos_value(fmt, p, n):
    f = fmt or POS_FMT
    return f.replace(u"{р}", u"%d" % p).replace(u"{p}", u"%d" % p).replace(u"{n}", u"%d" % n)


def number_rows(rows, mode, fmt, p, counter):
    """Номера строк одной таблицы. rows: [{"part": значение части, "main": главный?, "sys": имя системы}].
    mode: seq — {р}.{n} по счётчику раздела; sys — главный элемент части «П1», остальные «П1.1», «П1.2»
    (счётчик раздела не тратит; в части нет главного — «П1» у первой строки); none — пусто. -> (номера, счётчик)."""
    out = []
    cur, label, main_done, k = None, u"", False, 0
    with_main = set((r.get("part") or u"") for r in rows if r.get("main"))
    for r in rows:
        if mode == "none":
            out.append(u"")
            continue
        if mode == "sys":
            part = r.get("part") or u""
            if part != cur or cur is None:
                cur = part
                label = sys_label(part or r.get("sys") or u"")
                main_done, k = False, 0
            if (r.get("main") or part not in with_main) and not main_done and label:
                out.append(label)
                main_done = True
            else:
                k += 1
                out.append(u"%s.%d" % (label, k) if label else u"%d" % k)
            continue
        counter += 1
        out.append(pos_value(fmt, p, counter))
    return out, counter


def is_main_name(name, keys=None):
    n = (name or u"").strip().lower()
    return any(n.startswith(k) for k in (keys or MAIN_KEYS))


def type_key(fam, typ):
    return u"%s\t%s" % (fam or u"", typ or u"")


def ensure_sections(cfg, defaults=None):
    """Нет разделов в настройках — пресет «ОВ как в 414» (vks_defaults.SECTIONS_OV)."""
    if not cfg.get("sections"):
        cfg["sections"] = copy.deepcopy(getattr(defaults, "SECTIONS_OV", None) or [])
    for s in cfg["sections"]:
        s.setdefault("tables", [])
        s.setdefault("match", {})
        s.setdefault("new_sheet", True)
        for t in s["tables"]:
            t.setdefault("header", True)
            t.setdefault("pos", "seq")
            t.setdefault("new_sheet", False)
    return cfg["sections"]


def preview_lines(cfg, have_tpl=None):
    """Для окна выбора режима: разделы и таблицы текстом."""
    secs = cfg.get("sections") or []
    pm = dict(POS_MODES)
    out = []
    for i, s in enumerate(secs):
        p = sec_number(secs, i)
        out.append(u"{0}. {1} — части по {2}; позиции {3}{4}".format(
            p, s.get("name"), s.get("split") or u"—", (s.get("pos_fmt") or POS_FMT).replace(u"{р}", u"%d" % p).replace(u"{p}", u"%d" % p)
            .replace(u"{n}", u"n"),
            u"; с нового листа" if s.get("new_sheet", True) else u""))
        for t in s.get("tables") or []:
            miss = have_tpl is not None and t.get("tpl") not in have_tpl
            out.append(u"    {0}{1}: позиции {2}{3}{4}".format(
                t.get("tpl"), u" (нет в проекте)" if miss else u"", pm.get(t.get("pos"), t.get("pos")),
                u", без заголовков частей" if not t.get("header", True) else u"",
                u", с нового листа" if t.get("new_sheet") else u""))
    return out


# ------------------------------------------------------------------
# Revit
# ------------------------------------------------------------------
def _cat_keys(C):
    ids = {}
    for key, bname, title, order in C.D.CATS:
        b = C.bic(bname)
        if b is not None:
            ids[int(b)] = (key, title)
    return ids


def resolve_templates(C, sections, report):
    """Шаблон каждой таблицы — спецификация с этим именем. -> {имя: (вид, ключ категории, название)}."""
    doc = C.doc
    want = set()
    for s in sections:
        for t in s.get("tables") or []:
            if t.get("tpl"):
                want.add(t["tpl"])
    ids = _cat_keys(C)
    out = {}
    for vs in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule):
        if vs.IsTemplate or vs.Name not in want:
            continue
        k = ids.get(C.id_int(vs.Definition.CategoryId))
        if k is None:
            report.append(u"шаблон «{0}»: категория не из списка спецификаций (или несколько категорий) — "
                          u"пропущен".format(vs.Name))
            continue
        out[vs.Name] = (vs, k[0], k[1])
    for nm in sorted(want - set(out.keys())):
        report.append(u"нет шаблона «{0}» — таблица пропущена".format(nm))
    return out


def _main_types(cfg):
    return set(cfg.get("main_types") or [])


def is_main(C, it, cfg):
    if it.parent_id is not None:
        return False
    if type_key(it.fam, it.typ) in _main_types(cfg) or it.fam in _main_types(cfg):
        return True
    keys = cfg.get("main_keys") or getattr(C.D, "MAIN_KEYS", None) or MAIN_KEYS
    return is_main_name(it.name, keys) or is_main_name(it.typ, keys)


def assign_sections(C, infos, cfg, sections, tpls, amap, report, stats):
    """Раздел элемента: ручная привязка семейства/типа → система (сокращение раздела, иначе вид: трубы / воздух)
    → категория только в одном разделе → раздел родителя. it.sec — индекс раздела, it.group — имя раздела."""
    hidden = cfg.get("hidden") or {}
    manual = cfg.get("sec_assign") or {}
    names = [s.get("name") for s in sections]
    cat_secs = {}
    for si, s in enumerate(sections):
        for t in s.get("tables") or []:
            r = tpls.get(t.get("tpl"))
            if r is not None and si not in cat_secs.setdefault(r[1], []):
                cat_secs[r[1]].append(si)

    def by_system(it, cand):
        for sname in it.systems or []:
            ab = C.abbr_of(sname, amap)
            for si in cand:
                for a in (sections[si].get("match") or {}).get("abbr") or []:
                    if a and ab.startswith(a):
                        return si, sname
        for sname in it.systems or []:
            kind = C.SYS_KIND.get(sname)
            for si in cand:
                m = sections[si].get("match") or {}
                if not m.get("abbr") and m.get("kind") and m.get("kind") == kind:
                    return si, sname
        return None, u""

    for it in infos:
        it.sec, it.group, it.main, it.is_main = None, None, u"", False
        it.hidden = C.is_hidden(it, hidden)
        cand = cat_secs.get(it.key) or []
        if not cand or it.hidden:
            continue
        si, main = None, u""
        nm = manual.get(type_key(it.fam, it.typ)) or manual.get(it.fam)
        if nm in names and names.index(nm) in cand:
            si = names.index(nm)
        if si is None:
            si, main = by_system(it, cand)
        if si is None and len(cand) == 1:
            si = cand[0]
        it.sec, it.main = si, main or (it.systems[0] if it.systems else u"")
    byid = dict((i.id, i) for i in infos)
    for it in infos:
        if it.sec is None and not it.hidden and it.parent_id is not None and cat_secs.get(it.key):
            p = byid.get(it.parent_id)
            if p is not None and p.sec in cat_secs[it.key]:
                it.sec = p.sec
    active = set(i.sec for i in infos if i.sec is not None)
    for it in infos:
        if it.sec is None and not it.hidden and cat_secs.get(it.key):
            cand = [si for si in cat_secs[it.key] if si in active]
            if len(cand) == 1:              # категория в нескольких разделах, но элементы есть только в одном
                it.sec = cand[0]
    lost = {}
    title = dict((k, t) for k, b, t, o in C.D.CATS)
    for it in infos:
        if it.sec is not None:
            it.group = names[it.sec]
            it.is_main = is_main(C, it, cfg)
        elif cat_secs.get(it.key) and not it.hidden:
            k = (title.get(it.key, it.key), it.fam)
            lost[k] = lost.get(k, 0) + 1
    n = sum(lost.values())
    stats[u"элементов без раздела"] = n
    if n:
        report.append(u"без раздела (нет системы нужного вида, не привязаны) — {0} эл., в таблицы не попадут: ".format(n) +
                      u"; ".join(u"{0} / {1} — {2}".format(c, f, v) for (c, f), v in
                                 sorted(lost.items(), key=lambda x: -x[1])[:10]) + (u" …" if len(lost) > 10 else u""))
    return cat_secs


def part_value(C, it, split):
    if not split:
        return u""
    if split == P_SYS:            # нет своей системы — ручное значение ИмяСистемы («Жильё», «ВЕ»)
        return (it.sysraw or C.pval(it.el, P_SYS) or u"").strip()
    v = C.pval(it.el, split)
    if v is None:
        v = C.tval(it.el, split)
    return (u"%s" % v).strip() if v is not None else u""


def compute_keys(C, infos, cfg, sections, kids, report, tpls=None):
    """Части, Комплект, Сортировка — в it.part_val, it.kit_v, it.sort_v (без записи). Таблица без заголовков частей
    (и не «по системе») — все её элементы в одной части: иначе Revit дробит одинаковые строки по частям."""
    whole = set()
    for si, s in enumerate(sections):
        for t in s.get("tables") or []:
            r = (tpls or {}).get(t.get("tpl"))
            if r is not None and not t.get("header", True) and t.get("pos") != "sys":
                whole.add((si, r[1]))
    byid = dict((i.id, i) for i in infos)
    kid_of = {}
    for pid, lst in (kids or {}).items():
        for c in lst:
            kid_of[c.id] = pid
    nums = [sec_number(sections, i) for i in range(len(sections))]
    if len(set(nums)) != len(nums):
        raise Exception(u"у разделов одинаковые номера ({0}) — задайте разные".format(u", ".join(u"%d" % n for n in nums)))
    entries = []
    for si, s in enumerate(sections):
        members = [it for it in infos if it.sec == si]
        split = s.get("split") or u""
        for it in members:
            it.part_val = u"" if (si, it.key) in whole else part_value(C, it, split)
        parts = order_parts([it.part_val for it in members], split, s.get("parts_order"))
        if len(parts) >= KIT_BASE:
            raise Exception(u"раздел «{0}»: частей {1} — больше {2}".format(s.get("name"), len(parts), KIT_BASE - 1))
        pk = dict((v, n + 1) for n, v in enumerate(parts))
        s["_parts"] = parts
        for it in members:
            it.kit_v = kit_value(nums[si], pk[it.part_val])
            root = byid.get(kid_of[it.id]) if it.id in kid_of else it
            mflag = 0 if (root is not None and getattr(root, "is_main", False)) else 1
            entries.append(((si, it.kit_v, it.key), (mflag, it.sortv), it.id))
    ranks, top = dense_rank(entries)
    div = rank_div(top)
    for it in infos:
        if it.sec is not None:
            it.sort_v = sort_value(it.kit_v, ranks[it.id], div)
    return div


def write_keys(C, infos, cat_secs, report, stats):
    """ИмяСистемы — у кого есть своя система (без системы ручное значение остаётся); Комплект и Сортировка — элементам разделов; прочим элементам категорий таблиц — 0
    (в таблицы не попадут). Только чтение — в отчёт по семействам."""
    c = {u"ИмяСистемы": 0, u"Комплект": 0, u"Сортировка": 0}
    ro = {}
    for it in infos:
        if it.sysraw and C.set_val(it.el, P_SYS, it.sysraw) == "ok":   # пусто — ручное значение не затираем
            c[u"ИмяСистемы"] += 1
        if not cat_secs.get(it.key):
            continue
        kv = it.kit_v if it.sec is not None else 0.0
        sv = it.sort_v if it.sec is not None else 0.0
        for prm, v, nm in ((P_KIT, kv, u"Комплект"), (P_SORT, sv, u"Сортировка")):
            r = C.set_val(it.el, prm, v)
            if r == "ok":
                c[nm] += 1
            elif r in ("ro", "none", "err") and it.sec is not None:
                k = (prm, it.fam, r)
                ro[k] = ro.get(k, 0) + 1
    for k, v in c.items():
        stats[u"записано: " + k] = v
    if ro:
        why = {"ro": u"только чтение", "none": u"нет параметра", "err": u"ошибка записи"}
        report.append(u"ключи не записаны — эти элементы могут выпасть из таблиц или встать не на место "
                      u"(уберите параметр / формулу в семействе): " +
                      u"; ".join(u"{0} «{1}» — {2} ({3})".format(p.replace(u"ADSK_Позиция_", u""), f, n, why.get(r, r))
                                 for (p, f, r), n in sorted(ro.items(), key=lambda x: -x[1])[:12]) +
                      (u" …" if len(ro) > 12 else u""))


def _set_filters(C, vs, base, notes, tpl_name=None):
    d = vs.Definition
    removed = []
    for i in reversed(range(d.GetFilterCount())):
        nm = C.field_name(d, d.GetFilter(i).FieldId)
        if nm in (P_KIT, P_SORT):
            d.RemoveFilter(i)
            if nm not in removed:
                removed.append(nm)
    if removed:
        notes.append(u"снят фильтр шаблона по " + u", ".join(removed) + u" (теперь это ключи кнопки)")
    fk = C.ensure_field(d, P_KIT)
    if fk is None:
        raise Exception(u"в «{0}» нельзя вывести поле {1}".format(vs.Name, P_KIT))
    if d.GetFilterCount() + 2 > MAX_FILTERS:
        raise Exception(u"в шаблоне «{0}» {1} фильтров — для фильтра раздела нужно 2 свободных места (в Revit не "
                        u"больше {2}); уберите лишние фильтры шаблона".format(tpl_name or vs.Name, d.GetFilterCount(),
                                                                               MAX_FILTERS))
    d.AddFilter(DB.ScheduleFilter(fk.FieldId, DB.ScheduleFilterType.GreaterThan, float(base)))
    d.AddFilter(DB.ScheduleFilter(fk.FieldId, DB.ScheduleFilterType.LessThan, float(base + KIT_BASE)))
    fn = C.find_field(d, P_NAME)
    if fn is not None and d.GetFilterCount() < MAX_FILTERS:
        has = False
        for j in range(d.GetFilterCount()):
            f = d.GetFilter(j)
            if C.field_name(d, f.FieldId) == P_NAME and (C.safe(lambda: f.GetStringValue()) or u"") == C.SKIP:
                has = True
        if not has:
            d.AddFilter(DB.ScheduleFilter(fn.FieldId, DB.ScheduleFilterType.NotEqual, C.SKIP))


def _set_sort(C, vs, split, header, notes):
    d = vs.Definition
    d.ClearSortGroupFields()
    seq = [(P_KIT, False)]
    if split:
        seq.append((split, bool(header)))
    seq += [(P_SORT, False), (P_NAME, False)]
    if not split:
        seq.append((P_MARK, False))
    for prm, hdr in seq[:4]:
        f = C.ensure_field(d, prm)
        if f is None:
            notes.append(u"нет поля «{0}» — в сортировке пропущено".format(prm))
            continue
        sg = DB.ScheduleSortGroupField(f.FieldId, DB.ScheduleSortOrder.Ascending)
        sg.ShowHeader = hdr
        sg.ShowFooter = False
        sg.ShowBlankLine = False
        d.AddSortGroupField(sg)


def _short(name):
    return name[2:] if name.startswith((u"О_", u"O_")) else name


def make_tables(C, infos, cfg, sections, tpls, report):
    """Копии шаблонов по разделам. -> [Spec] в порядке раскладки."""
    doc = C.doc
    lo = C.layout_cfg(cfg)

    class SecSpec(C.Spec):
        @property
        def name(self):
            return self._name

    nums = [sec_number(sections, i) for i in range(len(sections))]
    specs = []
    for si, s in enumerate(sections):
        group = {"name": s.get("name"), "sec": True, "new_sheet": bool(s.get("new_sheet", True)), "link": None}
        n = 0
        for t in s.get("tables") or []:
            r = tpls.get(t.get("tpl"))
            if r is None:
                continue
            tpl, key, title = r
            lst = [it for it in infos if it.sec == si and it.key == key]
            if not lst:
                report.append(u"«{0}» / {1}: элементов нет — не создана".format(s.get("name"), t.get("tpl")))
                continue
            n += 1
            sp = SecSpec(group, key, _short(tpl.Name), tpl)
            sp._name = u"{0}.{1} {2}".format(nums[si], n, _short(tpl.Name))
            sp.items = lst
            sp.table = t
            sp.sec = si
            sp.p = nums[si]
            sp.new_sheet = bool(t.get("new_sheet"))
            sp.first_in_sec = (n == 1)
            specs.append(sp)
    with C.Tx(u"Спецификации: удалить прежние"):
        for uid in cfg.get("registry") or []:
            el = C.safe(lambda: doc.GetElement(uid))
            if el is None or (el.Name or u"").startswith((u"О_", u"O_")):
                continue
            try:
                doc.Delete(el.Id)
            except Exception as ex:
                report.append(u"не удалилась прежняя «{0}»: {1}".format(el.Name, ex))
        cfg["registry"] = []
    hidden_cols = {}
    with C.Tx(u"Спецификации: создать"):
        for k, sp in enumerate(specs):
            C._p(3, k + 1, len(specs))
            s = sections[sp.sec]
            sp.vs = doc.GetElement(sp.tpl.Duplicate(DB.ViewDuplicateOption.Duplicate))
            C.set_val(sp.vs, C.P_PURPOSE, C.D.SPEC_PURPOSE.format(s.get("name")))
            _set_filters(C, sp.vs, sp.p * KIT_BASE, sp.notes, sp.tpl.Name)
            split = s.get("split") or u""
            if not sp.table.get("header", True) and sp.table.get("pos") != "sys":
                split = u""           # одна часть: поле деления в сортировке дробило бы одинаковые строки
            header = bool(sp.table.get("header", True)) and len(set(it.part_val for it in sp.items)) > 1
            _set_sort(C, sp.vs, split, header, sp.notes)
            for nm in C.hide_service_fields(sp.vs):
                hidden_cols.setdefault(nm, set()).add(sp.title)
            C.center_fields(sp.vs)
            C.fix_column_widths(sp.vs)
        doc.Regenerate()
        for sp in list(specs):
            ids = C.safe(lambda: list(DB.FilteredElementCollector(doc, sp.vs.Id).WhereElementIsNotElementType()
                                      .ToElementIds()), []) or []
            sp.count = len(ids)
            sp.ids = set(C.id_int(x) for x in ids)
            if sp.count == 0:
                report.append(u"«{0}»: после фильтров шаблона пусто — не создана".format(sp.name))
                doc.Delete(sp.vs.Id)
                specs.remove(sp)
    for nm, titles in sorted(hidden_cols.items()):
        report.append(u"скрыт столбец «{0}» (в форме ГОСТ его нет): {1}".format(nm, u", ".join(sorted(titles))))
    with C.Tx(u"Спецификации: имена и заголовки"):
        existing = dict((v.Name, v) for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule))
        for n, sp in enumerate(specs, 1):
            sp.n = n
            sp.vs.Name = u"tmp_spec_{0}".format(C.id_int(sp.vs.Id))
        for sp in specs:
            old = existing.get(sp.name)
            if old is not None and old.Id != sp.vs.Id:
                k = 1
                while True:
                    cand = u"{0} (старая{1})".format(sp.name, u"" if k == 1 else u" " + str(k))
                    if cand not in existing:
                        break
                    k += 1
                old.Name = cand
                existing[cand] = old
                report.append(u"старая спецификация «{0}» переименована в «{1}»".format(sp.name, cand))
            sp.vs.Name = sp.name
            cfg["registry"].append(sp.vs.UniqueId)
            sp.notes.extend(C.L.set_header_heights(sp.vs, float(lo.get("title_mm") or 0),
                                                   float(lo.get("head_mm") or 0)))
            s = sections[sp.sec]
            if sp.first_in_sec and s.get("row"):
                text = (s.get("row_text") or u"").strip() or s.get("name") or u""
                C.add_sys_row(sp.vs, text, float(lo.get("sys_row_mm") or 8.0), sp.notes)
    return specs


def coverage(C, infos, specs, sections, report, stats):
    """Элементы раздела, которых нет ни в одной таблице раздела (отсечены фильтрами шаблонов)."""
    got = {}
    for sp in specs:
        got.setdefault((sp.sec, sp.key), set()).update(getattr(sp, "ids", set()))
    have = set(got.keys())
    miss = {}
    title = dict((k, t) for k, b, t, o in C.D.CATS)
    for it in infos:
        if it.sec is None:
            continue
        if (it.sec, it.key) not in have:
            k = (sections[it.sec].get("name"), title.get(it.key, it.key), u"нет таблицы этой категории")
        elif it.id not in got[(it.sec, it.key)]:
            k = (sections[it.sec].get("name"), title.get(it.key, it.key), it.fam)
        else:
            continue
        miss[k] = miss.get(k, 0) + 1
    n = sum(miss.values())
    stats[u"элементов раздела вне таблиц"] = n
    if n:
        report.append(u"не попали в таблицы своего раздела — {0} эл. (фильтры шаблонов): ".format(n) +
                      u"; ".join(u"{0} / {1} / {2} — {3}".format(a, b, c, v) for (a, b, c), v in
                                 sorted(miss.items(), key=lambda x: -x[1])[:12]) + (u" …" if len(miss) > 12 else u""))


def number_positions(C, specs, infos, cfg, sections, report, problems):
    """Позиции в порядке листа: разделы → таблицы → строки. Режим таблицы: seq / sys / none (очистить)."""
    doc = C.doc
    C.POS_STATS["rows"] = C.POS_STATS["written"] = 0
    num = C.load_numerator()
    byid = dict((i.id, i) for i in infos)
    by_type = {}
    for i in infos:
        by_type.setdefault(C.id_int(i.el.GetTypeId()), i)
    values = {}
    counters = {}
    for k, sp in enumerate(specs):
        C._p(4, k + 1, len(specs))
        s = sections[sp.sec]
        mode = sp.table.get("pos", "seq")
        if mode == "none":            # без разбора строк (долго на больших таблицах): очистить у заполненных
            for t in getattr(sp, "ids", set()):
                it = byid.get(t)
                if it is not None and (u"%s" % (C.pval(it.el, P_POS) or u"")).strip():
                    values[t] = (it.el.Id, u"")
            continue
        rows, targets, notes = num.map_rows(sp.vs)
        sp.notes.extend(notes)
        descr, idrows = [], []
        for row in rows:
            ids = [t for t in row if t is not None]
            if not ids:
                continue
            its = [byid.get(t) or by_type.get(t) for t in ids]
            its = [x for x in its if x is not None]
            first = its[0] if its else None
            descr.append({"part": getattr(first, "part_val", u"") if first else u"",
                          "main": any(getattr(x, "is_main", False) for x in its),
                          "sys": first.main if first else u""})
            idrows.append(ids)
        vals, counters[sp.sec] = number_rows(descr, mode, s.get("pos_fmt") or POS_FMT, sp.p, counters.get(sp.sec, 0))
        for ids, value in zip(idrows, vals):
            if value:
                C.POS_STATS["rows"] += 1
            for t in ids:
                if t in values and values[t][1] != value:
                    problems.append((t, u"в двух строках: {0} и {1} (ADSK_Позиция — параметр типа?)".format(
                        values[t][1] or u"пусто", value or u"пусто")))
                    continue
                values[t] = (targets[t], value)
    n = kept = 0
    keep = C.layout_cfg(cfg).get("pos_update") == "keep"
    with C.Tx(u"Спецификации: позиции"):
        for t, (eid, value) in values.items():
            el = doc.GetElement(eid)
            if keep and value and el is not None and (u"%s" % (C.pval(el, P_POS) or u"")).strip():
                kept += 1
                continue
            r = C.set_val(el, P_POS, value) if el is not None else "none"
            if r == "ok":
                n += 1
            elif r in ("ro", "err", "none") and value:
                problems.append((t, u"позиция не записалась ({0})".format(r)))
    if kept:
        report.append(u"позиции: сохранены прежние номера у {0} элементов".format(kept))
    C.POS_STATS["written"] = n
    return n


def check_params(C, report):
    for nm in (P_KIT, P_SORT):
        if C.bound_categories(nm)[0] is None:
            raise Exception(u"в проекте нет параметра «{0}» (число, экземпляр) — добавьте его как параметр проекта "
                            u"для категорий спецификаций".format(nm))
    if C.bound_categories(P_SYS)[0] is None:
        report.append(u"в проекте нет параметра «ИмяСистемы» — деление вентиляции по системам не работает")


def run(C, d, cfg, log=print, progress=None, note=None):
    """Сборка по разделам. Всё — одной группой транзакций (один Ctrl+Z); ошибка — откат, модель не меняется."""
    C._timing_start(progress, note)
    C.set_doc(d)
    C.TX_WARNINGS.clear()
    report, problems, stats = [], [], {}
    sections = ensure_sections(cfg, C.D)
    C._p(0)
    C.detect_categories()
    amap = C.system_abbr_map()
    lo = C.layout_cfg(cfg)
    C.L.ROW_MM = C.row_mm(lo)
    old_groups = cfg.get("groups")
    specs, lay = [], None
    tg = DB.TransactionGroup(d, u"Менеджер спецификаций")
    tg.Start()
    try:
        check_params(C, report)
        infos = C.collect()
        C._p(1)
        with C.Tx(u"Спецификации: изоляция и количество"):
            C.process_insulation(infos, report, stats)
            C.fill_quantities(infos, stats, report)
        C._p(2)
        tm = [time.time()]

        def lap(name):
            now = time.time()
            stats[u"время, с: " + name] = round(now - tm[0], 1)
            tm[0] = now
        tpls = resolve_templates(C, sections, report)
        cat_secs = assign_sections(C, infos, cfg, sections, tpls, amap, report, stats)
        lap(u"разделы")
        # служебные «группы» для общих функций (количество, малые строки): раздел = группа
        cfg["groups"] = [{"name": s.get("name"), "systems": [], "split": s.get("split") or None, "header": True}
                         for s in sections]
        # гибы — в трубу своей части (зоны / системы): на время переноса группа = раздел + часть
        keep = []
        for it in infos:
            if it.group and it.sec is not None:
                keep.append((it, it.group))
                it.group = u"%s\u241f%s" % (it.group, part_value(C, it, sections[it.sec].get("split") or u""))
        try:
            with C.Tx(u"Спецификации: гибы в трубы"):
                C.merge_bends(infos, report, stats)
        finally:
            for it, g in keep:
                if it.group is not None:
                    it.group = g
        lap(u"гибы")
        kids = C.compute_order(infos, cfg, report)
        lap(u"порядок (шаг 3)")
        C.drop_zero_rows(infos, cfg, stats, report)
        lap(u"малые строки")
        for it in infos:
            if it.group is None or it.hidden:
                it.sec = None
        compute_keys(C, infos, cfg, sections, kids, report, tpls)
        lap(u"ключи (расчёт)")
        with C.Tx(u"Спецификации: разделы, части, порядок"):
            write_keys(C, infos, cat_secs, report, stats)
        lap(u"ключи (запись)")
        specs = make_tables(C, infos, cfg, sections, tpls, report)
        coverage(C, infos, specs, sections, report, stats)
        lap(u"таблицы")
        C._n(3, C.plural(len(specs), u"спецификация", u"спецификации", u"спецификаций"))
        npos = number_positions(C, specs, infos, cfg, sections, report, problems)
        C._n(4, C.plural(C.POS_STATS["rows"], u"позиция", u"позиции", u"позиций"))
        stats[u"позиций записано"] = npos
        lap(u"позиции")
        lay = C.do_layout(specs, report, cfg)
        lap(u"листы")
        cfg.pop("_est_sheets", None)
        if lay is not None:
            C._n(5, C.plural(len(lay.used), u"лист", u"листа", u"листов") +
                 (u", новых {0}".format(lay.new_count) if getattr(lay, "new_count", 0) else u""))
        else:
            C._n(5, u"листов комплекта нет")
        tg.Assimilate()
        C.warnings_report(report)
    except C.UserError as ex:                  # Revit откатил шаг — причина без трассировки
        tg.RollBack()
        C._timing_stop(len(C.STAGES))
        return {"ok": False, "error": u"%s" % ex, "report": report, "stats": stats}
    except Exception:
        tg.RollBack()
        C._timing_stop(len(C.STAGES))
        return {"ok": False, "error": traceback.format_exc(), "report": report, "stats": stats}
    finally:
        if old_groups is not None:
            cfg["groups"] = old_groups
        for s in sections:
            s.pop("_parts", None)
    times = C._timing_stop(len(C.STAGES))
    cfg["_build_times"] = times
    placements = {}
    if lay is not None:
        for nm, seg, shn in lay.placements:
            placements.setdefault(nm, []).append(shn if seg < 0 else u"{0}({1})".format(shn, seg + 1))
    zeros = {}
    for sp in specs:
        z = C.safe(lambda: C.zero_rows(sp.vs), [])
        if z:
            zeros[sp.vs.Name] = z
    return {"ok": True, "report": report, "stats": stats, "problems": problems, "zeros": zeros, "times": times,
            "specs": [{"n": sp.n, "name": sp.vs.Name, "count": sp.count, "sheets": placements.get(sp.vs.Name, []),
                       "notes": sp.notes} for sp in specs]}


def template_names(doc):
    return set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule) if not v.IsTemplate)


def summary(doc, cfg, defaults=None):
    """Для окна «Раздел проекта» (ОВ): -> (кратко, [строки подробно]). Разделы из настроек проекта (нет — пресет
    «ОВ как в 414»), число таблиц, шаблоны «О_…», которых нет в проекте."""
    ensure_sections(cfg, defaults)
    have = template_names(doc)
    secs = cfg.get("sections") or []
    short, miss = [], 0
    for i, s in enumerate(secs):
        tbl = s.get("tables") or []
        miss += len([t for t in tbl if t.get("tpl") not in have])
        short.append(u"{0}. {1} — таблиц {2}".format(sec_number(secs, i), s.get("name"), len(tbl)))
    text = u"Разделы ОВ в настройках проекта: " + (u"; ".join(short) if short else u"нет") + u"."
    if miss:
        text += u" Шаблонов «О_…» нет в проекте: {0} — такие таблицы не соберутся.".format(miss)
    return text, preview_lines(cfg, have)
