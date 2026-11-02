# -*- coding: utf-8 -*-
"""Менеджер спецификаций — окно хода работы (строгий вид): этапы с галочками, прогресс, время.

Окно живёт в своём потоке (STA) со своим Dispatcher: Revit занят расчётом, а окно обновляется.
Из основного потока только отправляются сообщения (BeginInvoke). Revit API здесь не трогаем.
Окно не поверх всех (Topmost=False) и есть в панели задач: окна Revit (ошибки, вопросы) не должны
прятаться под ним — 02.11.2026 сборка ждала скрытое окно Revit 37 мин.
"""
from __future__ import print_function
import os
import time
import traceback

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System import Action, TimeSpan
from System.Threading import Thread, ThreadStart, ApartmentState, ManualResetEvent
from System.Windows import Thickness, FontWeights, HorizontalAlignment, GridLength, Visibility
from System.Windows.Controls import TextBlock, Grid, ColumnDefinition
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Threading import Dispatcher, DispatcherTimer, DispatcherPriority

import vks_theme as T

TITLE = u"Менеджер спецификаций"

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Менеджер спецификаций" Width="520" Height="238" WindowStyle="None" AllowsTransparency="True"
        Background="Transparent" ResizeMode="NoResize" Topmost="False" ShowInTaskbar="True"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="13">
 <Border x:Name="root" CornerRadius="8" Background="White" BorderBrush="#C9D3DF" BorderThickness="1" Margin="10">
  <Border.Effect><DropShadowEffect BlurRadius="16" ShadowDepth="2" Opacity="0.25"/></Border.Effect>
  <DockPanel>
   <Border x:Name="band" DockPanel.Dock="Top" Background="#1F5FAD" CornerRadius="7,7,0,0" Padding="16,9">
    <DockPanel>
     <Canvas x:Name="spin" DockPanel.Dock="Right" Width="16" Height="16" VerticalAlignment="Center" RenderTransformOrigin="0.5,0.5">
      <Canvas.RenderTransform><RotateTransform x:Name="spinRot"/></Canvas.RenderTransform>
      <Canvas.Triggers>
       <EventTrigger RoutedEvent="Canvas.Loaded">
        <BeginStoryboard>
         <Storyboard>
          <DoubleAnimation Storyboard.TargetName="spinRot" Storyboard.TargetProperty="Angle"
                           From="0" To="360" Duration="0:0:1" RepeatBehavior="Forever"/>
         </Storyboard>
        </BeginStoryboard>
       </EventTrigger>
      </Canvas.Triggers>
      <Ellipse Width="16" Height="16" Stroke="#5F8FCB" StrokeThickness="2"/>
      <Path Data="M 8,1 A 7,7 0 0 1 15,8" Stroke="White" StrokeThickness="2" StrokeStartLineCap="Round" StrokeEndLineCap="Round"/>
     </Canvas>
     <TextBlock x:Name="tProject" DockPanel.Dock="Right" Foreground="#CFE0F5" FontSize="12" Margin="0,0,12,0"
                VerticalAlignment="Center" TextTrimming="CharacterEllipsis" MaxWidth="220"/>
     <TextBlock x:Name="tTitle" Text="Менеджер спецификаций" Foreground="White" FontSize="15" FontWeight="SemiBold"
                VerticalAlignment="Center"/>
    </DockPanel>
   </Border>
   <StackPanel Margin="16,10,16,12">
    <StackPanel x:Name="stagesPanel"/>
    <ProgressBar x:Name="pb" Height="6" Minimum="0" Maximum="100" Margin="0,10,0,6" Foreground="#1F5FAD"
                 Background="#E6ECF2" BorderThickness="0"/>
    <DockPanel>
     <TextBlock x:Name="tPct" DockPanel.Dock="Right" Text="0%" FontSize="12" Foreground="#1F2A37" FontWeight="SemiBold"/>
     <TextBlock x:Name="tTime" Text="Прошло 0:00" FontSize="12" Foreground="#5B6470"/>
    </DockPanel>
   </StackPanel>
  </DockPanel>
 </Border>
</Window>
"""

WEIGHTS = [0.04, 0.02, 0.08, 0.18, 0.39, 0.29]     # доли этапов сборки, если замеров ещё нет (414-1.2)
READ_WEIGHTS = [0.15, 0.55, 0.15, 0.15]            # то же для чтения модели


def _brush(h, bg=False):
    """Кисть для темы окна (светлый цвет -> тёмный в тёмной теме, vks_theme)."""
    return T.brush(h, bg)


def _mmss(sec):
    sec = int(max(0, sec))
    return u"{0}:{1:02d}".format(sec // 60, sec % 60)


def weights_from(times, default):
    """Доли этапов из замеров прошлого запуска (секунды по этапам); нет замеров — default."""
    try:
        tot = float(sum(times))
        if times and len(times) == len(default) and tot > 0:
            return [max(0.01, t / tot) for t in times], tot
    except Exception:
        pass
    return list(default), None


class Splash(object):
    def __init__(self, stages, project=u"", snap_dir=None, snap_every=20, times=None, title=None, default=None):
        """times — секунды по этапам прошлого запуска (оценка «осталось ≈» с первых секунд)."""
        self.snap_dir = snap_dir            # для проверки: снимки окна каждые snap_every секунд
        self.snap_every = snap_every
        self.weights, self.expect = weights_from(times, default or (WEIGHTS if len(stages) == len(WEIGHTS)
                                                                   else [1.0 / len(stages)] * len(stages)))
        s_ = float(sum(self.weights)) or 1.0
        self.weights = [w / s_ for w in self.weights]
        self.title = title or TITLE
        self.stages = list(stages)
        self.project = project or u""
        self.error = None
        self.win = None
        self.disp = None
        self.cur = -1
        self.sub = {}
        self.notes = {}                     # итог этапа («46 спецификаций») — вместо «i из n», когда этап закончен
        self.t0 = time.time()
        self.done = False
        self.failed = False
        self._tick = 0
        try:
            self.dark = T.init()       # тема окна — как у мастера (ui.json / тема Revit); читается до потока окна
        except Exception:
            self.dark = False
        self._ready = ManualResetEvent(False)
        th = Thread(ThreadStart(self._thread))
        th.SetApartmentState(ApartmentState.STA)
        th.IsBackground = True
        th.Start()
        if not self._ready.WaitOne(10000) and self.error is None:
            self.error = u"окно не открылось"

    @property
    def ok(self):
        return self.error is None and self.win is not None

    # ---------- поток окна ----------
    def _thread(self):
        try:
            self.disp = Dispatcher.CurrentDispatcher
            self.win = XamlReader.Parse(T.xaml(XAML, self.dark))
            f = self.win.FindName
            for n in ("root", "band", "spin", "stagesPanel", "pb", "tPct", "tTime", "tTitle", "tProject"):
                setattr(self, n, f(n))
            self.tTitle.Text = self.title
            self.tProject.Text = self.project
            self.rows = [self._row(i, name) for i, name in enumerate(self.stages)]
            self.win.MouseLeftButtonDown += lambda s, e: self._drag()
            self._draw()
            self.timer = DispatcherTimer()
            self.timer.Interval = TimeSpan.FromSeconds(1)
            self.timer.Tick += self._on_tick
            self.timer.Start()
            self.win.Show()
        except Exception:
            self.error = traceback.format_exc()
            self.win = None
            self._ready.Set()
            return
        self._ready.Set()
        try:
            Dispatcher.Run()
        except Exception:
            pass

    def _drag(self):
        try:
            self.win.DragMove()
        except Exception:
            pass

    def _row(self, i, name):
        g = Grid()
        g.Margin = Thickness(0, 1, 0, 1)
        for w in (22, -1, 170):
            cd = ColumnDefinition()
            if w > 0:
                cd.Width = GridLength(w)
            g.ColumnDefinitions.Add(cd)
        mark = TextBlock()
        mark.FontWeight = FontWeights.Bold
        txt = TextBlock()
        txt.Text = name
        sub = TextBlock()
        sub.FontSize = 12
        sub.HorizontalAlignment = HorizontalAlignment.Right
        Grid.SetColumn(txt, 1)
        Grid.SetColumn(sub, 2)
        g.Children.Add(mark)
        g.Children.Add(txt)
        g.Children.Add(sub)
        self.stagesPanel.Children.Add(g)
        return (mark, txt, sub)

    def _draw(self):
        for i, (mark, txt, sub) in enumerate(self.rows):
            if (self.done and not self.failed) or i < self.cur:
                mark.Text, c = u"✓", "#2E7D32"
                txt.Foreground, txt.FontWeight = _brush("#1F2A37"), FontWeights.Normal
            elif i == self.cur:
                mark.Text, c = u"▶", "#1F5FAD"
                txt.Foreground, txt.FontWeight = _brush("#1F2A37"), FontWeights.SemiBold
            else:
                mark.Text, c = u"•", "#A3ACB7"
                txt.Foreground, txt.FontWeight = _brush("#8A939E"), FontWeights.Normal
            if self.failed and i == self.cur:
                mark.Text, c = u"✕", "#B3261E"
            mark.Foreground = _brush(c)
            s = self.sub.get(i)
            done_i = (self.done and not self.failed) or i < self.cur
            if done_i and self.notes.get(i):
                sub.Text = self.notes[i]
            else:
                sub.Text = u"{0} из {1}".format(s[0], s[1]) if s and s[0] is not None and s[1] else u""
            sub.Foreground = _brush("#1F5FAD" if i == self.cur and not self.done else "#7A8594")
        pct = 100.0 if (self.done and not self.failed) else self._pct()
        self.pb.Value = pct
        self.tPct.Text = u"{0:.0f}%".format(pct)
        self._time()

    def _pct(self):
        if self.cur < 0:
            return 0.0
        W = self.weights
        tot = sum(W[:min(self.cur, len(W))])
        s = self.sub.get(self.cur)
        frac = (float(s[0]) / s[1]) if s and s[0] is not None and s[1] else 0.0
        if self.cur < len(W):
            tot += W[self.cur] * min(1.0, frac)
        return min(99.0, tot * 100.0)

    def _time(self):
        el = time.time() - self.t0
        if self.done:
            self.tTime.Text = (u"Готово за " if not self.failed else u"Остановлено через ") + _mmss(el)
            return
        p = self._pct()
        t = u"Прошло " + _mmss(el)
        left = None
        if self.expect:                                   # по замерам прошлого запуска
            left = max(0.0, self.expect * (100.0 - p) / 100.0)
            if p >= 8 and el >= 5:                        # уточняем по ходу текущего
                left = (left + el * (100.0 - p) / p) / 2.0
        elif p >= 8 and el >= 5:
            left = el * (100.0 - p) / p
        if left is not None:
            t += u"  ·  осталось ≈ " + (u"{0} с".format(int(left + 0.5)) if left < 60 else _mmss(left))
        self.tTime.Text = t

    def _on_tick(self, s, e):
        self._tick += 1
        self._time()
        if self.snap_dir and self._tick % self.snap_every == 0:
            try:
                self._snap(os.path.join(self.snap_dir, u"run_%03d.png" % self._tick))
            except Exception:
                pass

    def _close_now(self):
        try:
            self.timer.Stop()
        except Exception:
            pass
        try:
            self.win.Close()
        except Exception:
            pass
        Dispatcher.CurrentDispatcher.BeginInvokeShutdown(DispatcherPriority.Background)

    def _finish(self, ok, text, delay=None):
        self.done = True
        self.failed = not ok
        if ok:
            self.cur = len(self.stages)
        self.spin.Visibility = Visibility.Collapsed
        self.tTitle.Text = text or (u"Готово" if ok else u"Ошибка — изменения отменены")
        if not ok:
            self.band.Background = _brush("#B3261E", True)
        self._draw()
        if delay == 0:
            self._close_now()
            return
        t = DispatcherTimer()
        t.Interval = TimeSpan.FromSeconds(delay if delay is not None else (1.2 if ok else 2.5))

        def fire(s, e):
            t.Stop()
            self._close_now()
        t.Tick += fire
        t.Start()

    # ---------- из основного потока ----------
    def _post(self, fn):
        if self.disp is None or self.win is None:
            return
        try:
            self.disp.BeginInvoke(Action(fn))
        except Exception:
            pass

    def set(self, stage, i=None, n=None):
        def do():
            for k in list(self.sub.keys()):          # прошедшие этапы — «n из n»
                if k < stage and self.sub[k][1]:
                    self.sub[k] = (self.sub[k][1], self.sub[k][1])
            self.cur = stage
            if i is not None or n is not None:
                self.sub[stage] = (i, n)
            self._draw()
        self._post(do)

    def note(self, stage, text):
        """Итог этапа справа (показывается, когда этап пройден)."""
        def do():
            self.notes[stage] = text
            self._draw()
        self._post(do)

    def finish(self, ok=True, text=None, delay=None):
        self._post(lambda: self._finish(ok, text, delay))

    def close(self):
        self._post(self._close_now)

    def _snap(self, path):
        from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
        from System.Windows.Media import PixelFormats
        from System.IO import FileStream, FileMode
        w, h = int(self.win.ActualWidth), int(self.win.ActualHeight)
        bmp = RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32)
        bmp.Render(self.win)
        enc = PngBitmapEncoder()
        enc.Frames.Add(BitmapFrame.Create(bmp))
        fs = FileStream(path, FileMode.Create)
        try:
            enc.Save(fs)
        finally:
            fs.Close()

    def snapshot(self, path):
        """PNG окна (для проверки)."""
        if self.disp is not None:
            self.disp.Invoke(Action(lambda: self._snap(path)))
        return path
