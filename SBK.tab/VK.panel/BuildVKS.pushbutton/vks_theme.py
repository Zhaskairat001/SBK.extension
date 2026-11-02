# -*- coding: utf-8 -*-
"""Менеджер спецификаций — тема окон: светлая (прежние цвета) и тёмная (сине-серая, как тёмная тема Revit 2024+).

Режим: «revit» — как в Revit (Параметры → Цвета → Тема интерфейса), «light», «dark». Выбор пользователя — в
%LOCALAPPDATA%\\Spec_Manager\\ui.json (общий для всех моделей, в настройки модели не пишется).

Как красится окно:
- цвета в коде и в XAML пишутся светлыми, как раньше; brush() / xaml() переводят их в тёмные по таблице DARK
  (для фона — ещё BG_DARK), чего нет в таблице — по светлоте (светлый фон → тёмный, тёмный текст → светлый);
- стили элементов (кнопки, поля, списки, вкладки, полосы прокрутки, меню, подсказки) — словарь resources();
- переключение без закрытия окна — switch(): словарь стилей заменяется, у всех элементов окна цвета
  пересчитываются в обе стороны (walk); лист бумаги в предпросмотре (paper) остаётся белым.
"""
from __future__ import print_function
import colorsys
import io
import json
import os
import re

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System.Windows import LogicalTreeHelper, DependencyObject, DependencyProperty, ResourceDictionary
from System.Windows.Controls import Panel, Border
from System.Windows.Documents import TextElement
from System.Windows.Media import SolidColorBrush, Color, VisualTreeHelper, Visual
from System.Windows.Shapes import Shape
from System.Windows.Markup import XamlReader

MODES = ("revit", "light", "dark")
MODE_TITLES = {"revit": u"Как в Revit", "light": u"Светлая", "dark": u"Тёмная"}
MODE = "revit"
DARK = False
_MARK = u"specThemeDict"          # ключ-метка словаря стилей темы (найти и заменить при переключении)

# ------------------------------------------------------------------
# палитра тёмной темы
# ------------------------------------------------------------------
BG = "#2B313A"              # окно
PANEL = "#323843"           # шапка, подложки
TEXT = "#E2E6EC"
MUTED = "#A3ACB9"
ACCENT = "#5294E0"          # акцент: текст, рамки, линии
ACCENT_BG = "#2F6CB8"       # акцент: фон (главная кнопка, текущий шаг)

# светлый цвет -> тёмный (текст, рамки, линии и фон, если нет в BG_DARK)
DARK_MAP = {
    "#FFFFFF": BG, "#000000": "#E8EBF0",
    "#1F5FAD": ACCENT, "#174A87": "#8DB6EC", "#0F3566": "#B5CEF2", "#7FA6D8": "#5F87BC", "#9DB3CF": "#46607F",
    "#B9CDE8": "#4B6890", "#E3EEFB": "#2E4A6E", "#F3F8FE": "#2F3A4A", "#F2F6FC": "#33404F", "#EEF4FF": "#2F3D56",
    "#EEF4FC": "#303D50", "#E8EEF6": "#374252",
    "#1F2A37": TEXT, "#1A1F26": "#E6E9EE", "#1D2C43": "#DCE3ED", "#3D4652": "#C7CED7", "#4A5361": "#B3BBC6",
    "#4A535E": "#A9B2BE", "#5B6470": MUTED, "#8A939E": "#8892A0", "#A0A8B2": "#6E7785",
    "#D5DAE0": "#4A5363", "#DDE1E6": "#444B58", "#E1E5EA": "#464E5B", "#C3CAD3": "#566070", "#B8C2CE": "#5A6575",
    "#C9D3DF": "#4F5968", "#E6ECF2": "#3E4652",
    "#FAFBFC": "#30363F", "#F6F7F9": PANEL, "#F4F6F8": "#3B424E", "#F1F3F5": "#363D48", "#EEF1F4": "#3A414C",
    "#E4E7EB": "#3F4652", "#E3E7EC": "#414855",
    "#FFF5E1": "#3C3424", "#FFF3C4": "#45391C", "#FFF6D6": "#42381F", "#FFFAF0": "#373126", "#FFF0D6": "#433623",
    "#F0D9A8": "#7A6234", "#E9C46A": "#9A7F3C", "#E8C766": "#98803E", "#E3D3B5": "#6D604B",
    "#5C3900": "#EFCF96", "#6B4E00": "#EACD84", "#6B4200": "#EFC787", "#8A5A00": "#E2B565", "#987020": "#E0BD6C",
    "#C27A00": "#F0A73A", "#C2410C": "#F07A45",
    "#FDECEC": "#4A2D30", "#E3A3A3": "#9A5A5A", "#8B1E1E": "#F09A9A", "#B3261E": "#F28B82",
    "#2F6B3A": "#7CC48A", "#EEF4E8": "#33402F",
    "#2E7D32": "#84C98F", "#5F8FCB": "#5F8FCB", "#CFE0F5": "#CFE0F5",
}
# фон: где светлый вариант цвета — фон под белым текстом или фон окна
BG_DARK = {"#FFFFFF": BG, "#1F5FAD": ACCENT_BG, "#1F2A37": "#56606E", "#B3261E": "#A5302A"}

_REV = {}                   # тёмный -> светлый (для обратного переключения)
PAPER = set()               # элементы «лист бумаги»: не перекрашиваются
for _m in (BG_DARK, DARK_MAP):
    for _k, _v in _m.items():
        if _k != _v:
            _REV.setdefault(_v, _k)


def _norm(h):
    h = (h or u"").strip().upper()
    if not h.startswith("#"):
        h = "#" + h
    return h


def _auto(h6):
    """Цвета вне таблицы: светлый фон -> тёмный того же оттенка, тёмный текст -> светлый, средние — как есть."""
    r, g, b = [int(h6[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    if l >= 0.62:
        l, s = 0.17 + (1.0 - l) * 0.9, min(s, 0.45)
    elif l <= 0.40:
        l, s = 0.93 - l * 0.6, min(s, 0.7)
    else:
        return h6
    r, g, b = colorsys.hls_to_rgb(hh, l, s)
    return "#" + u"".join(u"%02X" % int(round(max(0.0, min(1.0, v)) * 255)) for v in (r, g, b))


def dark_of(hexs, bg=False):
    """Светлый цвет -> тёмный (#RRGGBB или #AARRGGBB, прозрачность сохраняется)."""
    h = _norm(hexs)
    a, h6 = (h[1:3], "#" + h[3:]) if len(h) == 9 else (u"", h)
    if not bg and h6 == "#FFFFFF":
        d = h6                              # белый текст — только на цветном фоне, остаётся белым
    else:
        d = (BG_DARK.get(h6) if bg else None) or DARK_MAP.get(h6) or _auto(h6)
    if d != h6:
        _REV.setdefault(d, h6)
    return ("#" + a + d[1:]) if a else d


def mix(a, b, k):
    """Смесь цветов: k — доля a (0..1) -> #RRGGBB."""
    a_, b_ = _norm(a)[-6:], _norm(b)[-6:]
    ca = [int(a_[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b_[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + u"".join(u"%02X" % int(round(x * k + y * (1.0 - k))) for x, y in zip(ca, cb))


def _lum(h):
    c = [int(_norm(h)[-6:][i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def under_white(h):
    """Темнее h, пока белый текст на нём не станет читаемым (контраст не меньше 5:1)."""
    for _ in range(12):
        if 1.05 / (_lum(h) + 0.05) >= 5.0:
            break
        h = mix(h, "#000000", 0.85)
    return h


def light_of(hexs):
    """Тёмный цвет (выданный dark_of) -> исходный светлый; чужой цвет — как есть."""
    h = _norm(hexs)
    a, h6 = (h[1:3], "#" + h[3:]) if len(h) == 9 else (u"", h)
    l6 = _REV.get(h6, h6)
    return ("#" + a + l6[1:]) if a else l6


def hexc(hexs, bg=False):
    """Цвет для текущей темы."""
    return dark_of(hexs, bg) if DARK else _norm(hexs)


def raw_brush(hexs):
    h = _norm(hexs).lstrip("#")
    if len(h) == 8:
        return SolidColorBrush(Color.FromArgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)))
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def brush(hexs, bg=False):
    """Кисть цвета для текущей темы (hexs — светлый вариант, как в прежнем коде)."""
    return raw_brush(hexc(hexs, bg))


def _hex_of(b):
    c = b.Color
    if c.A == 255:
        return u"#%02X%02X%02X" % (c.R, c.G, c.B)
    return u"#%02X%02X%02X%02X" % (c.A, c.R, c.G, c.B)


# ------------------------------------------------------------------
# режим: настройка пользователя и тема Revit
# ------------------------------------------------------------------
def ui_path():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Spec_Manager", "ui.json")


def _read_ui():
    try:
        with io.open(ui_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}               # файла ещё нет или он испорчен — режим по умолчанию


def _write_ui(d):
    p = ui_path()
    try:
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        s = json.dumps(d, ensure_ascii=False, indent=1)
        if not isinstance(s, type(u"")):
            s = s.decode("utf-8")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(s)
        return True
    except Exception:
        return False            # не записалось — тема действует до закрытия окна


def revit_dark():
    """Тема интерфейса Revit (2024+): True — тёмная. Нет API или ошибка — светлая."""
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        return UIThemeManager.CurrentTheme == UITheme.Dark
    except Exception:
        return False


def resolve(mode=None):
    m = mode or MODE
    if m == "dark":
        return True
    if m == "light":
        return False
    return bool(revit_dark())


def init():
    """Прочитать режим из ui.json и определить тему. Вызывается при открытии окна."""
    global MODE, DARK
    m = _read_ui().get("theme")
    MODE = m if m in MODES else "revit"
    DARK = resolve(MODE)
    return DARK


def set_mode(mode):
    """Запомнить режим; -> новая тема (True — тёмная). Применить к окнам — switch()."""
    global MODE
    MODE = mode if mode in MODES else "revit"
    d = _read_ui()
    d["theme"] = MODE
    _write_ui(d)
    return resolve(MODE)


def mode_label(mode):
    t = MODE_TITLES.get(mode, mode)
    if mode == "revit":
        t += u" (сейчас: {0})".format(u"тёмная" if revit_dark() else u"светлая")
    return t


# ------------------------------------------------------------------
# XAML окна: цвета атрибутов -> тёмные
# ------------------------------------------------------------------
_BG_ATTRS = ("Background", "Fill")
_ATTR = re.compile(u'([A-Za-z][\\w.]*)="(#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?|White|Black)"')
_NAMED = {"White": "#FFFFFF", "Black": "#000000"}


def xaml(text, dark=None):
    """Текст XAML окна для темы: цвета атрибутов (Background, Foreground, BorderBrush, Fill, Stroke …) — тёмные."""
    if not (DARK if dark is None else dark):
        return text

    def rep(m):
        name, val = m.group(1), m.group(2)
        bg = name.split(".")[-1] in _BG_ATTRS
        return u'{0}="{1}"'.format(name, dark_of(_NAMED.get(val, val), bg))
    return _ATTR.sub(rep, text)


# ------------------------------------------------------------------
# стили
# ------------------------------------------------------------------
_NS = (u'xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
       u'xmlns:sys="clr-namespace:System;assembly=mscorlib"')

# стили кнопок светлой темы — прежние (из XAML мастера 0.21.0)
LIGHT_BUTTONS = u"""
  <Style TargetType="Button">
   <Setter Property="Background" Value="#F4F6F8"/>
   <Setter Property="BorderBrush" Value="#C3CAD3"/>
   <Setter Property="Foreground" Value="#1F2A37"/>
   <Setter Property="BorderThickness" Value="1"/>
   <Setter Property="Padding" Value="8,3"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Button">
      <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
              BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="4" Padding="{TemplateBinding Padding}"
              SnapsToDevicePixels="True">
       <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"
                         VerticalAlignment="{TemplateBinding VerticalContentAlignment}" RecognizesAccessKey="True"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsKeyboardFocused" Value="True">
        <Setter TargetName="bd" Property="BorderBrush" Value="#1F5FAD"/>
       </Trigger>
       <Trigger Property="IsMouseOver" Value="True">
        <Setter TargetName="bd" Property="Background" Value="#E3EEFB"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#7FA6D8"/>
       </Trigger>
       <Trigger Property="IsPressed" Value="True">
        <Setter TargetName="bd" Property="Background" Value="#1F5FAD"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#1F5FAD"/>
        <Setter Property="Foreground" Value="White"/>
       </Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter TargetName="bd" Property="Background" Value="#F1F3F5"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#E1E5EA"/>
        <Setter Property="Foreground" Value="#A0A8B2"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style x:Key="Primary" TargetType="Button">
   <Setter Property="Background" Value="#1F5FAD"/>
   <Setter Property="Foreground" Value="White"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Button">
      <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}"
              SnapsToDevicePixels="True">
       <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center" RecognizesAccessKey="True"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Background" Value="#174A87"/></Trigger>
       <Trigger Property="IsPressed" Value="True"><Setter TargetName="bd" Property="Background" Value="#0F3566"/></Trigger>
       <Trigger Property="IsEnabled" Value="False"><Setter TargetName="bd" Property="Background" Value="#9DB3CF"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
"""

DARK_STYLES = u"""
  <SolidColorBrush x:Key="tBg" Color="#2B313A"/>
  <SolidColorBrush x:Key="tPanel" Color="#323843"/>
  <SolidColorBrush x:Key="tInput" Color="#252A32"/>
  <SolidColorBrush x:Key="tCtrl" Color="#3B424E"/>
  <SolidColorBrush x:Key="tHover" Color="#2E4A6E"/>
  <SolidColorBrush x:Key="tHoverLine" Color="#5F87BC"/>
  <SolidColorBrush x:Key="tLine" Color="#4A5363"/>
  <SolidColorBrush x:Key="tCtrlLine" Color="#566070"/>
  <SolidColorBrush x:Key="tText" Color="#E2E6EC"/>
  <SolidColorBrush x:Key="tMuted" Color="#A3ACB9"/>
  <SolidColorBrush x:Key="tOff" Color="#6E7785"/>
  <SolidColorBrush x:Key="tOffBg" Color="#343A44"/>
  <SolidColorBrush x:Key="tAccent" Color="#5294E0"/>
  <SolidColorBrush x:Key="tAccentBg" Color="#2F6CB8"/>
  <SolidColorBrush x:Key="tSel" Color="#34506F"/>
  <SolidColorBrush x:Key="tThumb" Color="#5D6676"/>
  <SolidColorBrush x:Key="tThumbHover" Color="#7A8496"/>

  <SolidColorBrush x:Key="{x:Static SystemColors.WindowBrushKey}" Color="#2B313A"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.WindowTextBrushKey}" Color="#E2E6EC"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.ControlBrushKey}" Color="#323843"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.ControlTextBrushKey}" Color="#E2E6EC"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.ControlLightBrushKey}" Color="#3B424E"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.ControlDarkBrushKey}" Color="#566070"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.GrayTextBrushKey}" Color="#6E7785"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.HighlightBrushKey}" Color="#34506F"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.HighlightTextBrushKey}" Color="#FFFFFF"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.MenuBrushKey}" Color="#323843"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.MenuTextBrushKey}" Color="#E2E6EC"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.InfoBrushKey}" Color="#3B424E"/>
  <SolidColorBrush x:Key="{x:Static SystemColors.InfoTextBrushKey}" Color="#E2E6EC"/>

  <Style TargetType="Button">
   <Setter Property="Background" Value="#3B424E"/>
   <Setter Property="BorderBrush" Value="#566070"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="BorderThickness" Value="1"/>
   <Setter Property="Padding" Value="8,3"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Button">
      <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
              BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="4" Padding="{TemplateBinding Padding}"
              SnapsToDevicePixels="True">
       <ContentPresenter HorizontalAlignment="{TemplateBinding HorizontalContentAlignment}"
                         VerticalAlignment="{TemplateBinding VerticalContentAlignment}" RecognizesAccessKey="True"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsKeyboardFocused" Value="True">
        <Setter TargetName="bd" Property="BorderBrush" Value="#5294E0"/>
       </Trigger>
       <Trigger Property="IsMouseOver" Value="True">
        <Setter TargetName="bd" Property="Background" Value="#2E4A6E"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#5F87BC"/>
       </Trigger>
       <Trigger Property="IsPressed" Value="True">
        <Setter TargetName="bd" Property="Background" Value="#2F6CB8"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#2F6CB8"/>
        <Setter Property="Foreground" Value="White"/>
       </Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter TargetName="bd" Property="Background" Value="#343A44"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#424956"/>
        <Setter Property="Foreground" Value="#6E7785"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style x:Key="Primary" TargetType="Button">
   <Setter Property="Background" Value="#2F6CB8"/>
   <Setter Property="Foreground" Value="White"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Button">
      <Border x:Name="bd" Background="{TemplateBinding Background}" CornerRadius="4" Padding="{TemplateBinding Padding}"
              SnapsToDevicePixels="True">
       <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center" RecognizesAccessKey="True"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Background" Value="#3A7BCB"/></Trigger>
       <Trigger Property="IsPressed" Value="True"><Setter TargetName="bd" Property="Background" Value="#255A9C"/></Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter TargetName="bd" Property="Background" Value="#3D4C60"/>
        <Setter Property="Foreground" Value="#8C96A4"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>

  <Style TargetType="ToggleButton">
   <Setter Property="Background" Value="#3B424E"/>
   <Setter Property="BorderBrush" Value="#566070"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
  </Style>

  <Style TargetType="TextBox">
   <Setter Property="Background" Value="#252A32"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="BorderBrush" Value="#566070"/>
   <Setter Property="BorderThickness" Value="1"/>
   <Setter Property="CaretBrush" Value="#E2E6EC"/>
   <Setter Property="SelectionBrush" Value="#5294E0"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="TextBox">
      <Border x:Name="bd" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}"
              BorderThickness="{TemplateBinding BorderThickness}" SnapsToDevicePixels="True">
       <ScrollViewer x:Name="PART_ContentHost" Focusable="False" HorizontalScrollBarVisibility="Hidden"
                     VerticalScrollBarVisibility="Hidden"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="BorderBrush" Value="#5F87BC"/></Trigger>
       <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="bd" Property="BorderBrush" Value="#5294E0"/></Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter TargetName="bd" Property="Background" Value="#30353E"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#424956"/>
        <Setter Property="Foreground" Value="#6E7785"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>

  <ControlTemplate x:Key="tComboToggle" TargetType="ToggleButton">
   <Border x:Name="bd" Background="#3B424E" BorderBrush="#566070" BorderThickness="1" SnapsToDevicePixels="True">
    <Path x:Name="arrow" HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,7,0"
          Data="M 0,0 L 4,4 L 8,0" Stroke="#B3BBC6" StrokeThickness="1.5"/>
   </Border>
   <ControlTemplate.Triggers>
    <Trigger Property="IsMouseOver" Value="True">
     <Setter TargetName="bd" Property="BorderBrush" Value="#5F87BC"/>
     <Setter TargetName="bd" Property="Background" Value="#2E4A6E"/>
    </Trigger>
    <Trigger Property="IsChecked" Value="True"><Setter TargetName="bd" Property="BorderBrush" Value="#5294E0"/></Trigger>
    <Trigger Property="IsEnabled" Value="False">
     <Setter TargetName="bd" Property="Background" Value="#343A44"/>
     <Setter TargetName="bd" Property="BorderBrush" Value="#424956"/>
     <Setter TargetName="arrow" Property="Stroke" Value="#6E7785"/>
    </Trigger>
   </ControlTemplate.Triggers>
  </ControlTemplate>
  <Style TargetType="ComboBox">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Background" Value="#3B424E"/>
   <Setter Property="SnapsToDevicePixels" Value="True"/>
   <Setter Property="ScrollViewer.HorizontalScrollBarVisibility" Value="Auto"/>
   <Setter Property="ScrollViewer.VerticalScrollBarVisibility" Value="Auto"/>
   <Setter Property="ScrollViewer.CanContentScroll" Value="True"/>
   <Setter Property="MinHeight" Value="22"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="ComboBox">
      <Grid>
       <ToggleButton x:Name="toggle" Template="{StaticResource tComboToggle}" Focusable="False" ClickMode="Press"
                     IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}"/>
       <ContentPresenter x:Name="content" IsHitTestVisible="False" Margin="6,2,24,2" VerticalAlignment="Center"
                         HorizontalAlignment="Left" Content="{TemplateBinding SelectionBoxItem}"
                         ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                         ContentTemplateSelector="{TemplateBinding ItemTemplateSelector}"/>
       <TextBox x:Name="PART_EditableTextBox" Visibility="Hidden" Margin="2,1,22,1" VerticalAlignment="Center"
                Background="Transparent" BorderThickness="0" Foreground="#E2E6EC" Focusable="True"
                IsReadOnly="{TemplateBinding IsReadOnly}"/>
       <Popup x:Name="PART_Popup" Placement="Bottom" IsOpen="{TemplateBinding IsDropDownOpen}" AllowsTransparency="True"
              Focusable="False" PopupAnimation="Slide">
        <Border x:Name="dd" Background="#2B313A" BorderBrush="#566070" BorderThickness="1"
                MinWidth="{TemplateBinding ActualWidth}" MaxHeight="{TemplateBinding MaxDropDownHeight}">
         <ScrollViewer SnapsToDevicePixels="True">
          <ItemsPresenter KeyboardNavigation.DirectionalNavigation="Contained"/>
         </ScrollViewer>
        </Border>
       </Popup>
      </Grid>
      <ControlTemplate.Triggers>
       <Trigger Property="IsEditable" Value="True">
        <Setter TargetName="PART_EditableTextBox" Property="Visibility" Value="Visible"/>
        <Setter TargetName="content" Property="Visibility" Value="Hidden"/>
       </Trigger>
       <Trigger Property="HasItems" Value="False"><Setter TargetName="dd" Property="MinHeight" Value="24"/></Trigger>
       <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#6E7785"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="ComboBoxItem">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="ComboBoxItem">
      <Border x:Name="bd" Background="Transparent" Padding="6,3" SnapsToDevicePixels="True">
       <ContentPresenter/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="bd" Property="Background" Value="#2E4A6E"/></Trigger>
       <Trigger Property="IsSelected" Value="True"><Setter TargetName="bd" Property="Background" Value="#34506F"/></Trigger>
       <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#6E7785"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>

  <Style TargetType="CheckBox">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="CheckBox">
      <Grid Background="Transparent">
       <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
       <Border x:Name="box" Width="14" Height="14" VerticalAlignment="Center" Background="#252A32"
               BorderBrush="#7A8496" BorderThickness="1" CornerRadius="2" SnapsToDevicePixels="True">
        <Grid>
         <Path x:Name="mark" Data="M 2.5,7 L 5.5,10 L 11,3.5" Stroke="White" StrokeThickness="1.8" Visibility="Collapsed"/>
         <Rectangle x:Name="mid" Width="6" Height="6" Fill="White" Visibility="Collapsed"/>
        </Grid>
       </Border>
       <ContentPresenter x:Name="cp" Grid.Column="1" Margin="5,0,0,0" VerticalAlignment="Center" RecognizesAccessKey="True"/>
      </Grid>
      <ControlTemplate.Triggers>
       <Trigger Property="HasContent" Value="False"><Setter TargetName="cp" Property="Margin" Value="0"/></Trigger>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="box" Property="BorderBrush" Value="#5F87BC"/></Trigger>
       <Trigger Property="IsChecked" Value="True">
        <Setter TargetName="mark" Property="Visibility" Value="Visible"/>
        <Setter TargetName="box" Property="Background" Value="#2F6CB8"/>
        <Setter TargetName="box" Property="BorderBrush" Value="#2F6CB8"/>
       </Trigger>
       <Trigger Property="IsChecked" Value="{x:Null}">
        <Setter TargetName="mid" Property="Visibility" Value="Visible"/>
        <Setter TargetName="box" Property="Background" Value="#2F6CB8"/>
        <Setter TargetName="box" Property="BorderBrush" Value="#2F6CB8"/>
       </Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter Property="Foreground" Value="#6E7785"/>
        <Setter TargetName="box" Property="Opacity" Value="0.45"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="RadioButton">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="RadioButton">
      <Grid Background="Transparent">
       <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
       <Grid Width="14" Height="14" VerticalAlignment="Center">
        <Ellipse x:Name="ring" Fill="#252A32" Stroke="#7A8496" StrokeThickness="1"/>
        <Ellipse x:Name="dot" Width="6" Height="6" Fill="#E2E6EC" Visibility="Collapsed"/>
       </Grid>
       <ContentPresenter x:Name="cp" Grid.Column="1" Margin="5,0,0,0" VerticalAlignment="Center" RecognizesAccessKey="True"/>
      </Grid>
      <ControlTemplate.Triggers>
       <Trigger Property="HasContent" Value="False"><Setter TargetName="cp" Property="Margin" Value="0"/></Trigger>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="ring" Property="Stroke" Value="#5F87BC"/></Trigger>
       <Trigger Property="IsChecked" Value="True">
        <Setter TargetName="dot" Property="Visibility" Value="Visible"/>
        <Setter TargetName="ring" Property="Fill" Value="#2F6CB8"/>
        <Setter TargetName="ring" Property="Stroke" Value="#2F6CB8"/>
       </Trigger>
       <Trigger Property="IsEnabled" Value="False">
        <Setter Property="Foreground" Value="#6E7785"/>
        <Setter TargetName="ring" Property="Opacity" Value="0.45"/>
       </Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>

  <Style TargetType="ListBox">
   <Setter Property="Background" Value="#2B313A"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="BorderBrush" Value="#4A5363"/>
  </Style>
  <Style TargetType="ListBoxItem">
   <Setter Property="Foreground" Value="#E2E6EC"/>
  </Style>
  <Style TargetType="TreeView">
   <Setter Property="Background" Value="#2B313A"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="BorderBrush" Value="#4A5363"/>
  </Style>
  <Style TargetType="TreeViewItem">
   <Setter Property="Foreground" Value="#E2E6EC"/>
  </Style>
  <Style TargetType="ScrollViewer">
   <Setter Property="Foreground" Value="#E2E6EC"/>
  </Style>

  <Style TargetType="TabControl">
   <Setter Property="Background" Value="#2B313A"/>
   <Setter Property="BorderBrush" Value="#4A5363"/>
   <Setter Property="Foreground" Value="#E2E6EC"/>
  </Style>
  <Style TargetType="TabItem">
   <Setter Property="Foreground" Value="#B3BBC6"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="TabItem">
      <Border x:Name="bd" Background="#323843" BorderBrush="#4A5363" BorderThickness="1,1,1,0" CornerRadius="4,4,0,0"
              Padding="10,4" Margin="0,0,2,0" SnapsToDevicePixels="True">
       <ContentPresenter ContentSource="Header" HorizontalAlignment="Center" VerticalAlignment="Center"
                         RecognizesAccessKey="True"/>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="bd" Property="Background" Value="#2E4A6E"/></Trigger>
       <Trigger Property="IsSelected" Value="True">
        <Setter TargetName="bd" Property="Background" Value="#2B313A"/>
        <Setter TargetName="bd" Property="BorderBrush" Value="#5294E0"/>
        <Setter Property="Foreground" Value="#E2E6EC"/>
        <Setter Property="Panel.ZIndex" Value="1"/>
       </Trigger>
       <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#6E7785"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>

  <Style x:Key="tPageBtn" TargetType="RepeatButton">
   <Setter Property="Focusable" Value="False"/>
   <Setter Property="IsTabStop" Value="False"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="RepeatButton"><Border Background="Transparent"/></ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style x:Key="tThumbStyle" TargetType="Thumb">
   <Setter Property="IsTabStop" Value="False"/>
   <Setter Property="Focusable" Value="False"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Thumb">
      <Border x:Name="th" Background="#5D6676" CornerRadius="4" Margin="2"/>
      <ControlTemplate.Triggers>
       <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="th" Property="Background" Value="#7A8496"/></Trigger>
       <Trigger Property="IsDragging" Value="True"><Setter TargetName="th" Property="Background" Value="#8D97A8"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="ScrollBar">
   <Setter Property="Background" Value="#2F353F"/>
   <Setter Property="Width" Value="12"/>
   <Setter Property="MinWidth" Value="12"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="ScrollBar">
      <Border Background="{TemplateBinding Background}">
       <Track x:Name="PART_Track" IsDirectionReversed="True">
        <Track.DecreaseRepeatButton><RepeatButton Style="{StaticResource tPageBtn}" Command="ScrollBar.PageUpCommand"/></Track.DecreaseRepeatButton>
        <Track.IncreaseRepeatButton><RepeatButton Style="{StaticResource tPageBtn}" Command="ScrollBar.PageDownCommand"/></Track.IncreaseRepeatButton>
        <Track.Thumb><Thumb Style="{StaticResource tThumbStyle}"/></Track.Thumb>
       </Track>
      </Border>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
   <Style.Triggers>
    <Trigger Property="Orientation" Value="Horizontal">
     <Setter Property="Width" Value="Auto"/>
     <Setter Property="MinWidth" Value="0"/>
     <Setter Property="Height" Value="12"/>
     <Setter Property="MinHeight" Value="12"/>
     <Setter Property="Template">
      <Setter.Value>
       <ControlTemplate TargetType="ScrollBar">
        <Border Background="{TemplateBinding Background}">
         <Track x:Name="PART_Track" IsDirectionReversed="False">
          <Track.DecreaseRepeatButton><RepeatButton Style="{StaticResource tPageBtn}" Command="ScrollBar.PageLeftCommand"/></Track.DecreaseRepeatButton>
          <Track.IncreaseRepeatButton><RepeatButton Style="{StaticResource tPageBtn}" Command="ScrollBar.PageRightCommand"/></Track.IncreaseRepeatButton>
          <Track.Thumb><Thumb Style="{StaticResource tThumbStyle}"/></Track.Thumb>
         </Track>
        </Border>
       </ControlTemplate>
      </Setter.Value>
     </Setter>
    </Trigger>
   </Style.Triggers>
  </Style>

  <Style TargetType="ContextMenu">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="ContextMenu">
      <Border Background="#323843" BorderBrush="#566070" BorderThickness="1" Padding="2" SnapsToDevicePixels="True">
       <StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Cycle"/>
      </Border>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="MenuItem">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="MenuItem">
      <Border x:Name="bd" Background="Transparent" Padding="4,4,12,4" SnapsToDevicePixels="True">
       <Grid>
        <Grid.ColumnDefinitions><ColumnDefinition Width="22"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
        <Path x:Name="chk" Data="M 2,6 L 5,9 L 10,3" Stroke="#E2E6EC" StrokeThickness="1.6" VerticalAlignment="Center"
              HorizontalAlignment="Center" Visibility="Collapsed"/>
        <ContentPresenter Grid.Column="1" ContentSource="Header" VerticalAlignment="Center" RecognizesAccessKey="True"/>
        <Path x:Name="sub" Grid.Column="2" Data="M 0,0 L 4,4 L 0,8" Stroke="#B3BBC6" StrokeThickness="1.4"
              Margin="10,0,0,0" VerticalAlignment="Center" Visibility="Collapsed"/>
        <Popup x:Name="PART_Popup" Placement="Right" IsOpen="{TemplateBinding IsSubmenuOpen}" AllowsTransparency="True"
               Focusable="False" PopupAnimation="Fade">
         <Border Background="#323843" BorderBrush="#566070" BorderThickness="1" Padding="2">
          <StackPanel IsItemsHost="True" KeyboardNavigation.DirectionalNavigation="Cycle"/>
         </Border>
        </Popup>
       </Grid>
      </Border>
      <ControlTemplate.Triggers>
       <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="bd" Property="Background" Value="#2E4A6E"/></Trigger>
       <Trigger Property="IsChecked" Value="True"><Setter TargetName="chk" Property="Visibility" Value="Visible"/></Trigger>
       <Trigger Property="Role" Value="SubmenuHeader"><Setter TargetName="sub" Property="Visibility" Value="Visible"/></Trigger>
       <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#6E7785"/></Trigger>
      </ControlTemplate.Triggers>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="Separator">
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Separator"><Border Height="1" Margin="4,3" Background="#4A5363"/></ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style x:Key="{x:Static MenuItem.SeparatorStyleKey}" TargetType="Separator">
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="Separator"><Border Height="1" Margin="4,3" Background="#4A5363"/></ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
  <Style TargetType="ToolTip">
   <Setter Property="Foreground" Value="#E2E6EC"/>
   <Setter Property="Template">
    <Setter.Value>
     <ControlTemplate TargetType="ToolTip">
      <Border Background="#3B424E" BorderBrush="#566070" BorderThickness="1" Padding="8,5" MaxWidth="520">
       <ContentPresenter>
        <ContentPresenter.Resources>
         <Style TargetType="TextBlock"><Setter Property="TextWrapping" Value="Wrap"/></Style>
        </ContentPresenter.Resources>
       </ContentPresenter>
      </Border>
     </ControlTemplate>
    </Setter.Value>
   </Setter>
  </Style>
"""

def resources(dark=None, base=True):
    """Словарь стилей темы (или None). base — стили кнопок мастера в светлой теме (малым окнам не нужны)."""
    d = DARK if dark is None else dark
    if not d and not base:
        return None
    body = DARK_STYLES if d else LIGHT_BUTTONS
    return XamlReader.Parse(u'<ResourceDictionary {0}>\n<sys:String x:Key="{1}">1</sys:String>\n{2}\n'
                            u'</ResourceDictionary>'.format(_NS, _MARK, body))


def _set_dict(owner, dark, base):
    """Заменить словарь темы в owner.Resources."""
    md = owner.Resources.MergedDictionaries
    for i in range(md.Count - 1, -1, -1):
        try:
            if md[i].Contains(_MARK):
                md.RemoveAt(i)
        except Exception:
            pass            # чужой словарь — не трогаем
    rd = resources(dark, base)
    if rd is not None:
        md.Add(rd)


def dress(win, base=False, root=None):
    """Окно (новое, ещё не показанное) — в текущую тему: стили, фон, цвет текста."""
    _set_dict(win, DARK, base)
    if root is not None:
        _set_dict(root, DARK, base)
    if DARK:
        win.Background = raw_brush(BG)
        for o in (win, root):
            if o is not None:
                o.SetValue(TextElement.ForegroundProperty, raw_brush(TEXT))


def menu(cm):
    """Контекстное меню (своё дерево, стили окна не наследует) — в текущую тему."""
    try:
        _set_dict(cm, DARK, False)
    except Exception:
        pass                # меню без стилей темы — просто светлое
    return cm


# ------------------------------------------------------------------
# переключение открытого окна
# ------------------------------------------------------------------
_PROPS = ((Panel.BackgroundProperty, True), (TextElement.ForegroundProperty, False),
          (Border.BorderBrushProperty, False), (Shape.FillProperty, True), (Shape.StrokeProperty, False))


def paper(el):
    """Элемент «лист бумаги»: при переключении темы он и его содержимое не перекрашиваются."""
    PAPER.add(el)
    return el


def _children(o):
    out = []
    if isinstance(o, Visual):
        try:
            for i in range(VisualTreeHelper.GetChildrenCount(o)):
                out.append(VisualTreeHelper.GetChild(o, i))
        except Exception:
            pass            # элемент без визуальных детей
    try:
        for c in LogicalTreeHelper.GetChildren(o):
            if isinstance(c, DependencyObject):
                out.append(c)
    except Exception:
        pass
    return out


def walk(tops, dark):
    """Перекрасить заданные в элементах цвета (свои значения, не из стилей) в тему dark; -> число замен.
    tops — элемент или список (корень, отцепленный от окна, — отдельно)."""
    n = 0
    seen = set()
    stack = list(tops) if isinstance(tops, (list, tuple)) else [tops]
    while stack:
        o = stack.pop()
        if o is None or o in seen or o in PAPER:
            continue
        seen.add(o)
        for dp, bg in _PROPS:
            try:
                v = o.ReadLocalValue(dp)
            except Exception:
                continue
            if not isinstance(v, SolidColorBrush):
                continue
            h = _hex_of(v)
            h6 = "#" + h[-6:]
            if dark:
                if h6 in _REV:
                    continue                    # уже тёмный
                nh = dark_of(h, bg)
            else:
                nh = light_of(h)
            if nh != h:
                o.SetValue(dp, raw_brush(nh))
                n += 1
        stack.extend(_children(o))
    return n


def switch(win, dark, roots=(), base=True):
    """Перевести открытое окно в тему dark без закрытия."""
    global DARK
    DARK = bool(dark)
    _set_dict(win, DARK, base)
    for r in roots:
        _set_dict(r, DARK, base)
    for o in [win] + list(roots):
        if DARK:
            o.SetValue(TextElement.ForegroundProperty, raw_brush(TEXT))
        else:
            o.ClearValue(TextElement.ForegroundProperty)
    return walk([win] + list(roots), DARK)
