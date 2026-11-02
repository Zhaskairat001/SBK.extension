# -*- coding: utf-8 -*-
"""Менеджер спецификаций — спецификация оборудования, изделий и материалов по ГОСТ 21.601-2011 п. 9.

Окна: 1) системы и группы; 2) что специфицируем (+ «Заполнить количество»); 3) материалы и типы;
4) сортировка; 5) материалы (покраска, крепёж); 6) листы (раскладка, нумерация позиций и листов, штамп).
Чтение модели и сборка — в окне хода работы с процентами и оценкой «осталось ≈» по замерам прошлых запусков.
Всё одним шагом отмены. Прежняя версия кнопки — script_v1.py.
"""
from __future__ import print_function
import os
import imp

from pyrevit import revit, forms, script

# движок не выгружается после скрипта: панель «Исправить в Revit» (немодальное окно, ExternalEvent) живёт дальше
__persistentengine__ = True

HERE = os.path.dirname(os.path.abspath(__file__))
core = imp.load_source("spec_manager_core", os.path.join(HERE, "vks_core.py"))
ui = imp.load_source("spec_manager_ui", os.path.join(HERE, "vks_ui.py"))
try:
    anim = imp.load_source("spec_manager_anim", os.path.join(HERE, "vks_anim.py"))
except Exception:
    anim = None

doc = revit.doc
output = script.get_output()
log = core.RunLog(doc)          # журнал запуска в %LOCALAPPDATA%\Spec_Manager\logs

if doc.IsFamilyDocument:
    forms.alert(u"Запустите в файле проекта.", exitscript=True)


def splash_for(stages, times, title, default=None):
    """Окно хода работы в своём потоке; не открылось — None (тогда обычная полоса pyRevit)."""
    if anim is None:
        return None
    try:
        sp = anim.Splash(stages, doc.Title, times=times, title=title, default=default)
        return sp if sp.ok else None
    except Exception:
        return None


timing = core.load_timing(doc)

# 1. чтение модели — с процентами и «осталось ≈»
splash = splash_for(core.READ_STAGES, timing.get("read"), u"Читаю модель…",
                    getattr(anim, "READ_WEIGHTS", None) if anim else None)
log.add(u"Чтение модели. Окно хода работы: {0}".format(u"да" if splash is not None else u"нет (полоса pyRevit)"))
try:
    if splash is not None:
        ok = False
        try:
            infos, systems, cfg, amap = core.prepare(doc, progress=splash.set)
            ok = True
        finally:
            splash.finish(ok, delay=0)
    else:
        with forms.ProgressBar(title=u"Менеджер спецификаций: читаю модель…", indeterminate=True):
            infos, systems, cfg, amap = core.prepare(doc)
except Exception:
    log.error(u"чтение модели")
    raise
read_times = cfg.pop("_read_times", None)
log.add(u"Прочитано: элементов {0}, систем {1}. Этапы: {2}".format(
    len(infos or []), len(systems or []),
    u"; ".join(u"{0} — {1}".format(n, core.fmt_sec(t)) for n, t in zip(core.READ_STAGES, read_times or []))))
if not systems:
    forms.alert(u"В модели нет трубопроводных и вентиляционных систем.", exitscript=True)

owner = None
try:
    owner = __revit__.MainWindowHandle      # noqa: F821
except Exception:
    pass
# раздел проекта (ВК / ОВ): выбирается один раз и запоминается; сменить — кнопка «ВК ▾» / «ОВ ▾» в мастере
SEC = core.sections_module()


def ov_info():
    try:
        return SEC.summary(doc, cfg, core.D)
    except Exception:
        log.error(u"сводка разделов ОВ")
        return None


def set_discipline(k, persist):
    """Раздел → режим сборки и единица групп (ВК — системы, ОВ — ADSK_Группирование; выбор окна — в cfg).
    В файл настроек — только если он уже есть (иначе новый проект потерял бы «шаблон для новых проектов»:
    запомнится при сборке вместе со всем)."""
    global systems
    d = ui.disc_by_key(core.D, k)
    cfg["discipline"] = k
    n_order = core.apply_disc_order(cfg)     # шаг 3: набор раздела вместо подставленного по умолчанию
    cfg["mode"] = d.get("mode") or "groups"
    if cfg.get("group_by") not in ("systems", "grouping"):
        cfg["group_by"] = d.get("group_by") or "systems"
    cfg.setdefault("group_fallback", True)
    if cfg["mode"] == "sections":
        SEC.ensure_sections(cfg, core.D)
    sp = None
    if cfg["group_by"] == "grouping":        # чтение ADSK_Группирование у всех элементов — 10–15 с на 40 тыс.
        sp = splash_for([u"ADSK_Группирование"], None, u"Группы по ADSK_Группирование…")
    ok = False
    try:
        systems = core.regroup(infos, cfg, progress=sp.set if sp is not None else None)
        ok = True
    finally:
        if sp is not None:
            sp.finish(ok, delay=0)
    if persist:
        saved = core.load_cfg()
        if saved:
            for key in ("discipline", "mode", "group_by", "group_fallback", "units_gb", "groups", "groups_by"):
                if key in cfg:
                    saved[key] = cfg[key]
            core.save_cfg(saved)
    log.add(u"Раздел проекта: {0} → {1}; групп: {2}{3}".format(
        d.get("code"), u"разделы по шаблонам" if cfg["mode"] == "sections" else
        (u"группы по ADSK_Группирование" if cfg["group_by"] == "grouping" else u"группы систем"),
        len(cfg.get("groups") or []),
        u"; не определено: {0} эл.".format(len(core.UNRESOLVED)) if core.UNRESOLVED else u""))
    if n_order:
        log.add(u"Шаг 3: набор раздела {0} — категорий {1}".format(d.get("code"), n_order))


if ui.disc_by_key(core.D, cfg.get("discipline")) is None:
    try:
        k = ui.choose_discipline(core, infos, cfg, owner_handle=owner, first=True, ov_info=ov_info())
    except Exception:
        log.error(u"окно «Раздел проекта»")
        raise
    if not k:
        log.add(u"Окно «Раздел проекта» закрыто без выбора, сборки не было")
        script.exit()
    set_discipline(k, True)
else:
    set_discipline(cfg["discipline"], False)

def choose_build():
    """«Что собираем» (ВК, ОВ): общая / на блок / по всем блокам. -> {"scope", "sec"} или None (закрыто)."""
    if cfg.get("discipline") not in getattr(core.D, "SCOPE_DISCIPLINES", ("VK", "OV")):
        return {"scope": "all", "sec": None}
    try:
        return ui.choose_scope(core, infos, cfg, owner_handle=owner)
    except Exception:
        log.error(u"окно «Что собираем»")
        raise


def wizard_flow():
    """Мастер (с «Сменить раздел»). -> настройки для сборки | None (закрыто) | "fix" (открыта панель
    «Исправить в Revit»: мастер вернётся из неё)."""
    global cfg, chosen
    while True:
        cfg["build"] = build
        w_infos, w_systems, common = infos, systems, None
        if build.get("scope") == "one":          # на блок: окно — по элементам блока, группы — свои у блока
            sec = build.get("sec")
            w_infos = [it for it in infos if it.sec == sec]
            w_systems = core.found_systems(w_infos, core.AMAP)
            common = cfg.get("groups") or []
            cfg["groups"] = core.block_groups(cfg, sec, w_systems)
        try:
            chosen = ui.run_wizard(core, w_infos, w_systems, cfg, owner_handle=owner)
        except Exception:
            log.error(u"окно настроек")
            raise
        if common is not None:                   # группы блока — в sec_groups, общие — на место
            cfg["groups"] = common
            if chosen:
                chosen.setdefault("sec_groups", {})[build.get("sec")] = chosen.get("groups") or []
                chosen["groups"] = common
        if chosen and chosen.get("_fix"):
            kind = chosen.pop("_fix")
            chosen.pop("_change_discipline", None)
            cfg = chosen                         # настройки мастера не теряются
            open_fix(kind)
            return "fix"
        if not chosen or not chosen.pop("_change_discipline", False):
            return chosen
        cfg = chosen
        try:
            k = ui.choose_discipline(core, infos, cfg, owner_handle=owner, first=False, ov_info=ov_info())
        except Exception:
            log.error(u"окно «Сменить раздел проекта»")
            raise
        if k:                                    # раздел или «группы по» могли смениться
            set_discipline(k, True)


def block_infos():
    """Элементы, которые видит мастер: на блок — только блока."""
    if build.get("scope") == "one":
        return [it for it in infos if it.sec == build.get("sec")]
    return infos


def open_fix(kind):
    """Панель «Исправить в Revit» (vks_fix): немодальная, Revit активен. «Вернуться» — мастер снова."""
    fix = imp.load_source("spec_manager_fix", os.path.join(HERE, "vks_fix.py"))
    title = dict(core.PROBLEMS).get(kind, kind)
    titles = dict((k, t) for k, b, t, o in core.D.CATS)

    def items():
        return core.problems(block_infos(), cfg).get(kind) or []

    def refresh(ids):
        n = core.refresh_infos(infos, ids)
        core.set_units(infos, cfg.get("group_by") or "systems", cfg.get("group_fallback", True) is not False)
        return n

    def back():
        log.add(u"Панель «Исправить в Revit»: возврат в мастер")
        resume()

    def closed():
        log.add(u"Панель «Исправить в Revit» закрыта без сборки")

    log.add(u"Панель «Исправить в Revit»: {0} — {1} эл.".format(title, len(items())))
    fix.FixPanel(doc, title, items, refresh, back, closed, lambda k: titles.get(k, k), log).show(owner)


def resume():
    """Из панели исправлений (контекст Revit API): единицы групп заново, мастер, затем сборка."""
    global systems
    systems = core.regroup(infos, cfg)
    res = wizard_flow()
    if res == "fix":
        return
    finish(res)


def finish(chosen_):
    """Сборка и отчёт."""
    global chosen
    chosen = chosen_
    mode = cfg.get("mode") or "groups"
    if not chosen:
        log.add(u"Окно закрыто без сборки")
        if read_times:                           # замер чтения пригодится и без сборки
            saved = core.load_cfg()
            if saved:
                core.remember_timing(saved, "read", read_times)
                core.save_cfg(saved)
        return
    remember = chosen.pop("_remember", True)
    chosen.pop("_preset_auto", None)
    chosen.pop("_order_auto", None)              # служебное: что шаг 3 подставил по умолчанию
    chosen["mode"] = mode
    chosen["discipline"] = cfg.get("discipline")
    chosen["build"] = build
    if cfg.get("sections"):
        chosen["sections"] = cfg["sections"]

    # 2. сборка
    log.add(u"Сборка: {0}".format(u"разделов {0}".format(len(chosen.get("sections") or [])) if mode == "sections"
                                  else u"групп {0}".format(len(chosen.get("groups") or []))))
    splash = splash_for(core.STAGES, timing.get("build"), u"Менеджер спецификаций")
    try:
        if splash is not None:
            res = None
            try:
                res = core.run(doc, chosen, progress=splash.set, note=getattr(splash, "note", None))
            finally:
                splash.finish(bool(res and res.get("ok")))
        else:
            with forms.ProgressBar(title=u"Менеджер спецификаций: спецификации, позиции, листы…", indeterminate=True):
                res = core.run(doc, chosen)
    except Exception:
        log.error(u"сборка")
        raise
    if res.get("ok"):
        try:
            save_settings(res, remember)
        except Exception:
            log.error(u"сохранение настроек")
    report(res, remember)


def save_settings(res, remember):
    """Настройки: запомнить (или сохранить только служебное: созданные спецификации, замеры времени)."""
    build_times = chosen.pop("_build_times", None) or res.get("times")
    chosen.pop("_mat_run", None)                 # галочки материалов не запоминаются
    chosen.pop("moves", None)                    # переносы систем записаны в модель сборкой — больше не нужны
    if remember:
        saved = chosen
    else:
        saved = core.load_cfg()
        for k in ("registry", "sheet_registry"):
            saved[k] = chosen.get(k, [])
        saved["sec_registry"] = chosen.get("sec_registry") or {}
        saved["build"] = build
        for k in ("last_need", "last_sig"):
            saved.setdefault("layout", {})[k] = (chosen.get("layout") or {}).get(k, 0 if k == "last_need" else u"")
        saved["timing"] = chosen.get("timing") or saved.get("timing") or {}
        saved.pop("moves", None)
    core.remember_timing(saved, "read", read_times)
    core.remember_timing(saved, "build", build_times)
    core.save_cfg(saved)



def report(res, remember):
    """Отчёт сборки: окно вывода pyRevit; после панели исправлений его может не быть — тогда файл отчёта."""
    try:
        _report(res, remember)
    except Exception:
        log.error(u"окно вывода")
        try:
            import io
            path = os.path.join(os.path.dirname(log.path) if getattr(log, "path", None) else os.environ.get(
                "TEMP", u"."), u"report_last.txt")
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(u"Менеджер спецификаций — {0}\n".format(u"собрано" if res.get("ok") else u"ошибка"))
                for s_ in res.get("specs") or []:
                    f.write(u"{0}. {1} — {2}\n".format(s_["n"], s_["name"], u", ".join(s_["sheets"])))
                for r in res.get("report") or []:
                    f.write(u"• {0}\n".format(r))
                if res.get("error"):
                    f.write(u"{0}\n".format(res["error"]))
            os.startfile(path)
        except Exception:
            log.error(u"файл отчёта")


def _report(res, remember):
    output.set_title(u"Менеджер спецификаций")
    if not res.get("ok"):
        log.add(u"Сборка отменена, модель не изменена. Причина: {0}".format(res.get("error")))
        output.print_md(u"## Ошибка — изменения отменены")
        print(res.get("error"))
        return

    build_times = res.get("times")
    output.print_md(u"## Собрано спецификаций: {0}".format(len(res["specs"])))
    output.print_table(
        table_data=[[s["n"], s["name"], s["count"], u", ".join(s["sheets"]), u"; ".join(s["notes"])] for s in res["specs"]],
        columns=[u"№", u"Спецификация", u"Строк / элементов", u"Листы", u"Примечание"])
    output.print_md(u"### Что сделано")
    for k, v in sorted(res["stats"].items()):
        print(u"{0}: {1}".format(k, v))
    for r in res["report"]:
        print(u"• " + r)
    if res.get("zeros"):
        output.print_md(u"### Строки с нулевым количеством")
        for k, v in res["zeros"].items():
            print(u"{0}: {1}".format(k, u" | ".join(v)))
    if res.get("problems"):
        output.print_md(u"### Позиции не записаны ({0})".format(len(res["problems"])))
        for eid, why in res["problems"][:60]:
            print(u"{0} — {1}".format(eid, why))
    output.print_md(u"### Время")
    if read_times:
        print(u"Чтение модели: " + u"; ".join(u"{0} — {1}".format(n, core.fmt_sec(t))
                                             for n, t in zip(core.READ_STAGES, read_times)) +
              u". Всего {0}".format(core.fmt_sec(sum(read_times))))
    if build_times:
        print(u"Сборка: " + u"; ".join(u"{0} — {1}".format(n, core.fmt_sec(t)) for n, t in zip(core.STAGES, build_times)) +
              u". Всего {0}".format(core.fmt_sec(sum(build_times))))
    output.print_md(u"Отменить всё — Ctrl+Z (одним шагом). Настройки: `{0}`".format(core.settings_path()))

    log.add(u"Готово: спецификаций {0}, позиций не записано {1}".format(
        len(res.get("specs") or []), len(res.get("problems") or [])))
    for k, v in sorted((res.get("stats") or {}).items()):
        log.add(u"  {0}: {1}".format(k, v))
    for r in res.get("report") or []:
        log.add(u"  • " + r)
    for eid, why in (res.get("problems") or [])[:60]:
        log.add(u"  не записано {0} — {1}".format(eid, why))
    if build_times:
        log.add(u"Этапы сборки: " + u"; ".join(u"{0} — {1}".format(n, core.fmt_sec(t))
                                              for n, t in zip(core.STAGES, build_times)))
    log.add(u"Конец")


build = choose_build()
if build is None:
    log.add(u"Окно «Что собираем» закрыто, сборки не было")
    script.exit()
log.add(u"Что собираем: {0}".format({"one": u"блок {0}".format(build.get("sec")), "each": u"по всем блокам"}.get(
    build.get("scope"), u"общая на объект")))
chosen = None
_first = wizard_flow()
if _first != "fix":
    finish(_first)
