# -*- coding: utf-8 -*-
"""Менеджер спецификаций — панель «Исправить в Revit»: немодальное окно поверх Revit со списком проблемных
элементов. Revit при этом активен. Все обращения к модели — через ExternalEvent (контекст Revit API):
щелчок по строке — выделить и показать элемент; «Обновить» — перечитать только элементы списка;
«Вернуться в мастер» — открыть мастер снова с теми же настройками (дальше — обычная сборка, один Ctrl+Z)."""
from __future__ import print_function
import traceback

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
try:
    clr.AddReference("RevitAPIUI")
except Exception:
    pass                    # в Revit сборка уже загружена pyRevit; вне Revit (проверка окна) — заглушки
from System.Windows import (Window, Thickness, SizeToContent, ResizeMode, WindowStartupLocation, FontWeights,
                            HorizontalAlignment, VerticalAlignment, TextWrapping, SystemParameters)
from System.Windows.Controls import (StackPanel, DockPanel, Dock, TextBlock, Button, ListBox, ListBoxItem,
                                     Orientation, ScrollBarVisibility, SelectionMode)
from System.Windows.Media import SolidColorBrush, Color, FontFamily, Brushes
from System.Collections.Generic import List
from Autodesk.Revit import DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent

import vks_theme as T

_KEEP = []          # живые панели: обработчики и окна не должны собираться сборщиком мусора


def _brush(h, bg=False):
    """Кисть для темы окна (vks_theme)."""
    return T.brush(h, bg)


def _consts():
    global C_BLUE, C_BLUE_BG, C_MUTED, C_WARN
    C_BLUE = _brush("#1F5FAD")
    C_BLUE_BG = _brush("#1F5FAD", True)
    C_MUTED = _brush("#5B6470")
    C_WARN = _brush("#8A5A00")


_consts()


class _Handler(IExternalEventHandler):
    """Выполняет одно задание в контексте Revit API (job(uiapp)); ошибка — в on_error, модель не трогается."""

    def __init__(self):
        self.job = None
        self.on_error = None

    def Execute(self, uiapp):
        job, self.job = self.job, None
        if job is None:
            return
        try:
            job(uiapp)
        except Exception:
            if self.on_error is not None:
                try:
                    self.on_error(traceback.format_exc())
                except Exception:
                    pass          # окно уже закрыто — сообщать некуда

    def GetName(self):
        return u"Менеджер спецификаций: исправить в Revit"


class FixPanel(object):
    """items_fn() -> [Info] — проблемные элементы (пересчитываются после «Обновить»);
    refresh_fn(ids) — перечитать элементы (в контексте API); on_return() — вернуться в мастер (в контексте API);
    on_close() — закрыто без сборки; cat_title(key) -> название категории."""

    def __init__(self, doc, title, items_fn, refresh_fn, on_return, on_close, cat_title, log=None):
        self.doc = doc
        self.title = title
        self.items_fn = items_fn
        self.refresh_fn = refresh_fn
        self.on_return = on_return
        self.on_close = on_close
        self.cat_title = cat_title
        self.log = log
        self.items = []
        self.done = False
        self.handler = _Handler()
        self.handler.on_error = self._error
        self.event = ExternalEvent.Create(self.handler)       # создаётся в контексте API (из script.py)
        try:
            T.init()            # тема — как у мастера
        except Exception:
            T.DARK = False
        _consts()
        w = Window()
        T.dress(w)
        w.Title = u"Исправить в Revit — {0}".format(title)
        w.Width = 560
        w.Height = 560
        w.MinWidth = 420
        w.MinHeight = 300
        w.ShowInTaskbar = False
        w.Topmost = True
        w.WindowStartupLocation = WindowStartupLocation.Manual
        w.Left = max(0.0, SystemParameters.WorkArea.Right - w.Width - 24)
        w.Top = SystemParameters.WorkArea.Top + 90
        w.FontFamily = FontFamily(u"Segoe UI")
        w.FontSize = 13
        w.Background = _brush("#FFFFFF", True)
        w.Closed += self._closed
        self.win = w
        root = DockPanel()
        root.Margin = Thickness(12, 10, 12, 12)
        top = StackPanel()
        DockPanel.SetDock(top, Dock.Top)
        self.tHead = TextBlock()
        self.tHead.FontWeight = FontWeights.SemiBold
        self.tHead.TextWrapping = TextWrapping.Wrap
        top.Children.Add(self.tHead)
        hint = TextBlock()
        hint.Text = (u"Щелчок по строке — выделить и показать в Revit. Исправьте элементы в модели, затем "
                     u"«Обновить» — перечитаются только они, исправленные уйдут из списка.")
        hint.Foreground = C_MUTED
        hint.FontSize = 12
        hint.TextWrapping = TextWrapping.Wrap
        hint.Margin = Thickness(0, 4, 0, 8)
        top.Children.Add(hint)
        root.Children.Add(top)
        bar = StackPanel()
        bar.Orientation = Orientation.Vertical
        DockPanel.SetDock(bar, Dock.Bottom)
        self.tStatus = TextBlock()
        self.tStatus.Foreground = C_BLUE
        self.tStatus.FontSize = 12
        self.tStatus.TextWrapping = TextWrapping.Wrap
        self.tStatus.Margin = Thickness(0, 8, 0, 6)
        bar.Children.Add(self.tStatus)
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        row.HorizontalAlignment = HorizontalAlignment.Right
        for text, fn, primary in ((u"Выделить все", self._select_all, False), (u"Обновить", self._refresh, False),
                                  (u"Вернуться в мастер", self._back, True), (u"Закрыть", self._close_btn, False)):
            b = Button()
            b.Content = text
            b.Padding = Thickness(12, 4, 12, 4)
            b.Margin = Thickness(6, 0, 0, 0)
            if primary:
                b.Background = C_BLUE_BG
                b.Foreground = Brushes.White
                b.FontWeight = FontWeights.SemiBold
            b.Click += (lambda f: (lambda s, e: f()))(fn)
            row.Children.Add(b)
        bar.Children.Add(row)
        root.Children.Add(bar)
        self.lb = ListBox()
        self.lb.SelectionMode = SelectionMode.Extended
        self.lb.SelectionChanged += self._picked
        root.Children.Add(self.lb)
        w.Content = root
        self._fill()

    # ---------- список ----------
    def _fill(self):
        self.items = list(self.items_fn() or [])
        self.lb.Items.Clear()
        for it in self.items:
            li = ListBoxItem()
            li.Tag = it.id
            sp = StackPanel()
            t1 = TextBlock()
            t1.Text = u"{0} · {1}: {2}".format(self.cat_title(it.key), it.fam or u"—", it.typ or u"—")
            t1.TextWrapping = TextWrapping.Wrap
            sp.Children.Add(t1)
            t2 = TextBlock()
            sysn = u", ".join(it.systems[:3]) + (u" …" if len(it.systems) > 3 else u"") if it.systems else u"без системы"
            t2.Text = u"id {0} · {1}{2}".format(it.id, sysn, (u" · " + it.name) if (it.name or u"").strip() else u"")
            t2.Foreground = C_MUTED
            t2.FontSize = 11.5
            t2.TextWrapping = TextWrapping.Wrap
            sp.Children.Add(t2)
            li.Content = sp
            self.lb.Items.Add(li)
        n = len(self.items)
        self.tHead.Text = u"{0}: {1} эл.".format(self.title, n) if n else u"{0}: всё исправлено".format(self.title)
        self.tHead.Foreground = C_WARN if n else C_BLUE

    def _ids(self, only_selected=False):
        if only_selected:
            return [li.Tag for li in self.lb.SelectedItems]
        return [it.id for it in self.items]

    # ---------- задания в контексте Revit API ----------
    def _run(self, job, busy=u""):
        if self.handler.job is not None:
            self.tStatus.Text = u"Revit занят предыдущим действием — повторите через секунду."
            return
        self.handler.job = job
        if busy:
            self.tStatus.Text = busy
        self.event.Raise()

    def _show(self, ids):
        def job(uiapp):
            uidoc = uiapp.ActiveUIDocument
            if uidoc is None or not uidoc.Document.Equals(self.doc):
                self.tStatus.Text = u"Активен другой документ — переключитесь на модель, из которой запущен менеджер."
                return
            lst = List[DB.ElementId]()
            for i in ids:
                el = _element(self.doc, i)
                if el is not None:
                    lst.Add(el.Id)
            if lst.Count == 0:
                self.tStatus.Text = u"Элементов уже нет в модели — нажмите «Обновить»."
                return
            uidoc.Selection.SetElementIds(lst)
            try:
                uidoc.ShowElements(lst)
                self.tStatus.Text = u"Выделено: {0}.".format(lst.Count)
            except Exception:
                self.tStatus.Text = u"Выделено: {0}; на активном виде их не показать — откройте план или 3D.".format(
                    lst.Count)
        self._run(job)

    def _picked(self, s, e):
        ids = self._ids(True)
        if ids:
            self._show(ids)

    def _select_all(self):
        if self.items:
            self._show(self._ids())

    def _refresh(self):
        ids = self._ids()

        def job(uiapp):
            n, gone = self.refresh_fn(ids)
            before = len(ids)
            self._fill()
            fixed = before - len(self.items)
            self.tStatus.Text = u"Перечитано {0} эл.{1}; исправлено {2}, осталось {3}.".format(
                n, u", удалено из модели {0}".format(gone) if gone else u"", max(0, fixed), len(self.items))
        self._run(job, u"Перечитываю {0} эл.…".format(len(ids)))

    def _back(self):
        ids = self._ids()

        def job(uiapp):
            self.refresh_fn(ids)            # перед мастером — свежие данные по исправленным
            self.done = True
            self.win.Close()
            self.on_return()
        self._run(job, u"Возвращаюсь в мастер…")

    def _close_btn(self):
        self.win.Close()

    def _closed(self, s, e):
        if not self.done:
            self.done = True
            try:
                self.on_close()
            except Exception:
                pass                         # закрытие без сборки — сообщать нечего
        if self in _KEEP:
            _KEEP.remove(self)

    def _error(self, tb):
        if self.log is not None:
            try:
                self.log.add(u"Панель «Исправить в Revit»: ошибка\n" + tb)
            except Exception:
                pass                         # журнал недоступен — ошибка видна в окне
        self.tStatus.Text = u"Не вышло, модель не изменена: " + (tb.strip().splitlines() or [u""])[-1]

    def show(self, owner_handle=None):
        if owner_handle:
            try:
                from System.Windows.Interop import WindowInteropHelper
                WindowInteropHelper(self.win).Owner = owner_handle
                self.win.Topmost = False             # над Revit и так (владелец), не над другими программами
            except Exception:
                pass                                 # без владельца — поверх всех окон
        _KEEP.append(self)
        self.win.Show()


def _element(doc, i):
    try:
        from System import Int64
        return doc.GetElement(DB.ElementId(Int64(i)))
    except Exception:
        try:
            return doc.GetElement(DB.ElementId(int(i)))
        except Exception:
            return None
