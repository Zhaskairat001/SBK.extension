# -*- coding: utf-8 -*-
"""Менеджер спецификаций — окна настройки (WPF): Системы → Что специфицируем → Материалы и типы → Сортировка →
Материалы → Листы."""
from __future__ import print_function
import copy
import json
import math

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xaml")

from System.Windows import (Thickness, Visibility, FontWeights, DragDrop, DragDropEffects, DataObject, TextTrimming,
                            HorizontalAlignment, VerticalAlignment, TextWrapping, CornerRadius, GridLength,
                            GridUnitType, Size, Rect, LogicalTreeHelper, SystemParameters, Window, SizeToContent,
                            WindowStartupLocation, ResizeMode, MessageBox, MessageBoxButton, MessageBoxResult,
                            MessageBoxImage, TextAlignment, LineStackingStrategy)
from System.Windows.Controls import (ListBoxItem, TextBlock, TextBox, CheckBox, ComboBox, Button, Border, Grid,
                                     RowDefinition,
                                     StackPanel, WrapPanel, DockPanel, ColumnDefinition, Orientation, TreeViewItem,
                                     TabItem, RadioButton, ScrollViewer, ListBox, Dock, ContextMenu, MenuItem,
                                     Separator, ScrollBarVisibility, Canvas, SelectionMode)
from System.Windows.Media import SolidColorBrush, Color, VisualTreeHelper, Brushes, DoubleCollection, FontFamily
from System.Windows.Documents import Run
from System.Windows.Shapes import Rectangle, Line
from System.Windows.Controls import Panel
from System.Windows.Markup import XamlReader
from System.Windows.Input import (MouseButtonState, Keyboard, Key, ModifierKeys, TraversalRequest,
                                  FocusNavigationDirection, Cursors)
from System.Windows.Controls.Primitives import Selector, UniformGrid
from System.Windows.Controls import SelectionChangedEventHandler
from System.Windows.Threading import DispatcherPriority
from System import Action

import vks_theme as T

P_MAIN = u"ADSK_Система_Имя"      # прежние настройки; заменён на ИмяСистемы
P_SYS = u"ИмяСистемы"
P_GRP = u"ADSK_Группирование"
STEPS = [u"Системы", u"Что специфицируем", u"Материалы и типы", u"Сортировка", u"Материалы", u"Листы"]
NO_DROP = getattr(DragDropEffects, "None")
NO_SPLIT = u"— нет —"
NO_WRITE = u"— не писать —"
ZQ_IDX = {"none": 0, "empty": 1, "zero": 2}
ZQ_LABELS = (u"нет параметра", u"пусто", u"0")
HISTORY_MAX = 100
LAST = len(STEPS) - 1


def brush(hexs, bg=False):
    """Кисть для текущей темы окна: hexs — светлый цвет (как в светлой теме), bg — цвет фона (белый -> фон окна,
    акцент -> тёмно-синий под белым текстом). Тёмная тема — vks_theme."""
    return T.brush(hexs, bg)


pbrush = T.raw_brush            # «лист бумаги» в предпросмотре: цвет без темы


def _consts():
    """Общие кисти — для текущей темы (заново после переключения темы)."""
    global C_BLUE, C_BLUE_BG, C_MUTED, C_LINE, C_SEL, C_DONE, C_ZERO, C_WARN_BG, C_WARN_LINE, C_BG, C_TEXT
    C_BLUE = brush("#1F5FAD")
    C_BLUE_BG = brush("#1F5FAD", True)  # фон под белым текстом
    C_MUTED = brush("#5B6470")
    C_LINE = brush("#D5DAE0")
    C_SEL = brush("#F2F6FC")
    C_DONE = brush("#2F6B3A")
    C_ZERO = brush("#FFF3C4")        # ADSK_Количество = 0 — мягкий жёлтый
    C_WARN_BG = brush("#FDECEC")     # конфликт номера — мягкий красный
    C_WARN_LINE = brush("#E3A3A3")
    C_BG = brush("#FFFFFF", True)    # фон окна / карточки
    C_TEXT = brush("#000000")        # чёрный текст


def theme_init():
    """Тема окон при открытии: настройка пользователя (ui.json) или тема Revit."""
    try:
        T.init()
    except Exception:
        T.DARK = False      # тема не определилась — светлая, как раньше
    _consts()


_consts()

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Менеджер спецификаций: настройка" Width="1180" Height="780" MinWidth="1000" MinHeight="600"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="13" Background="White">
 <Grid x:Name="root" Background="White">
  <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
  <Border Grid.Row="0" Background="#F6F7F9" BorderBrush="#DDE1E6" BorderThickness="0,0,0,1" Padding="16,10">
   <DockPanel>
    <StackPanel DockPanel.Dock="Right" Orientation="Horizontal" VerticalAlignment="Center">
     <Button x:Name="btnTheme" Padding="7,2" Margin="0,0,10,0" FontFamily="Segoe UI Symbol" FontSize="14"
             ToolTip="Тема окна: как в Revit, светлая или тёмная"/>
     <TextBlock Text="Шаблон:" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="#4A5361"/>
     <ComboBox x:Name="cbPreset" Width="210" Margin="0,0,6,0"/>
     <Button x:Name="btnPresetApply" Content="Применить" Padding="10,3" Margin="0,0,6,0"/>
     <Button x:Name="btnPresetSave" Content="Сохранить как…" Padding="10,3" Margin="0,0,6,0"/>
     <Button x:Name="btnPresetMenu" Content="Файл ▾" Padding="10,3"/>
    </StackPanel>
    <Button x:Name="btnDisc" DockPanel.Dock="Left" Padding="10,3" Margin="0,0,12,0" VerticalAlignment="Center"
            FontWeight="SemiBold" Foreground="#1F5FAD" ToolTip="Раздел проекта — сменить"/>
    <StackPanel x:Name="steps" Orientation="Horizontal"/>
   </DockPanel>
  </Border>
  <Grid Grid.Row="1" Margin="16,12">

   <Grid x:Name="page0">
    <Grid.ColumnDefinitions><ColumnDefinition Width="300"/><ColumnDefinition Width="16"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
    <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6">
     <DockPanel>
      <StackPanel DockPanel.Dock="Top" Margin="12,10,12,6">
       <TextBlock Text="Системы в модели" FontWeight="SemiBold"/>
       <TextBlock x:Name="sysInfo" Foreground="#5B6470" FontSize="12" TextWrapping="Wrap"/>
      </StackPanel>
      <WrapPanel DockPanel.Dock="Bottom" Margin="8">
       <Button x:Name="btnToNew" Content="В новую группу" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnToSel" Content="В отмеченную группу" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnSkip" Content="Исключить" Padding="8,4" Margin="0,0,0,4"
               ToolTip="Выделенное слева — не специфицировать: элементы не попадут в спецификации, и при следующем запуске группа сама не вернётся. Вернуть — «В новую группу» или перетащить в группу."/>
      </WrapPanel>
      <ListBox x:Name="lbSystems" BorderThickness="0" SelectionMode="Extended" HorizontalContentAlignment="Stretch"
               AllowDrop="True"/>
     </DockPanel>
    </Border>
    <DockPanel Grid.Column="2">
     <StackPanel DockPanel.Dock="Top" Margin="0,0,0,8">
      <TextBlock Text="Группы спецификаций" FontWeight="SemiBold" FontSize="14"/>
      <TextBlock Foreground="#5B6470" FontSize="12" TextWrapping="Wrap" Margin="0,2,0,6"
       Text="Порядок групп = порядок разделов; карточку можно тянуть мышью. Щелчок — выбрать, Ctrl+щелчок — добавить, Shift+щелчок — диапазон, Ctrl+рамка — выделить системы, Esc — снять. Система, брошенная в пустое место, — новая группа в конце. Tab — связать выбранные группы. «Делить по», «Заголовок», «Строка названия системы» меняются сразу у всех выбранных групп. Ctrl+Z / Ctrl+Y — отменить / повторить."/>
      <WrapPanel>
       <Button x:Name="btnMerge" Content="Объединить отмеченные" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnSplit" Content="Разъединить" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnAuto" Content="По сокращению" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnLink" Content="Связать (Tab)" Padding="8,4" Margin="0,0,6,4"
               ToolTip="Выбранные группы — подряд на одном листе, без перехода на новый лист между ними"/>
       <Button x:Name="btnUnlink" Content="Разъединить связку" Padding="8,4" Margin="0,0,6,4"/>
       <Button x:Name="btnGUp" Content="↑" Width="30" Margin="0,0,4,4" ToolTip="Выше (Ctrl+↑)"/>
       <Button x:Name="btnGDown" Content="↓" Width="30" Margin="0,0,0,4" ToolTip="Ниже (Ctrl+↓)"/>
      </WrapPanel>
     </StackPanel>
     <Border DockPanel.Dock="Bottom" Background="#FFF5E1" CornerRadius="6" Padding="10,8" Margin="0,8,0,0">
      <TextBlock x:Name="tGrpNote" TextWrapping="Wrap" FontSize="12" Foreground="#5C3900"
       Text="Элемент сразу в нескольких системах попадёт один раз — в первую группу по этому порядку. Имя группы пишется в ADSK_Система_Обозначение (по нему фильтр), основная система — в ADSK_Система_Имя."/>
     </Border>
     <ListBox x:Name="lbGroups" AllowDrop="True" HorizontalContentAlignment="Stretch" BorderBrush="#D5DAE0"
              ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>
    </DockPanel>
    <Canvas Grid.ColumnSpan="3" IsHitTestVisible="False">
     <Rectangle x:Name="marqRect" Stroke="#1F5FAD" StrokeThickness="1" Fill="#261F5FAD" Visibility="Collapsed"/>
    </Canvas>
   </Grid>

   <DockPanel x:Name="page1" Visibility="Collapsed">
    <DockPanel DockPanel.Dock="Top" Margin="0,0,0,8">
     <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
      <Button x:Name="btnFillQty" Content="Заполнить количество…" Padding="8,4" Margin="8,0,6,0"
              ToolTip="Изделиям с пустым или нулевым ADSK_Количество — 1 шт. Сначала список: что и куда запишется. Выделите категорию / семейство в дереве — только их; без выделения — все жёлтые."/>
      <Button x:Name="btnExpand" Content="Развернуть всё" Padding="8,4" Margin="0,0,6,0"/>
      <Button x:Name="btnCollapse" Content="Свернуть всё" Padding="8,4"/>
     </StackPanel>
     <TextBlock Text="Поиск" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="#4A5361"/>
     <TextBox x:Name="tbSearch" Padding="4,3"/>
    </DockPanel>
    <TextBlock DockPanel.Dock="Bottom" x:Name="treeInfo" Margin="0,8,0,0" Foreground="#3D4652" FontSize="12" TextWrapping="Wrap"/>
    <TreeView x:Name="tvCats" BorderBrush="#C3CAD3"/>
   </DockPanel>

   <DockPanel x:Name="page2" Visibility="Collapsed">
    <Border DockPanel.Dock="Top" Background="#F3F8FE" BorderBrush="#B9CDE8" BorderThickness="1" CornerRadius="6"
            Padding="10,6" Margin="0,0,0,8">
     <DockPanel>
      <CheckBox x:Name="cbOrderOn" DockPanel.Dock="Left" FontWeight="SemiBold" VerticalAlignment="Center"
                Content="Распределять по готовым спискам (шаг 3)"/>
      <TextBlock x:Name="tOrderInfo" Margin="14,0,0,0" FontSize="12" Foreground="#4A5361" TextWrapping="Wrap"
                 VerticalAlignment="Center"/>
     </DockPanel>
    </Border>
    <WrapPanel DockPanel.Dock="Bottom" Margin="0,8,0,0">
     <TextBlock Text="Внутри материала:" FontWeight="SemiBold" VerticalAlignment="Center" Margin="0,0,10,0"/>
     <RadioButton x:Name="rbTypeDiam" Content="тип → диаметр" GroupName="inner" Margin="0,0,14,0" VerticalAlignment="Center"/>
     <RadioButton x:Name="rbDiamType" Content="диаметр → тип" GroupName="inner" VerticalAlignment="Center"/>
     <TextBlock Text="   Диаметр — по возрастанию. Порядок пишется в параметры, выбранные на вкладке «Сортировка»."
                Foreground="#5B6470" VerticalAlignment="Center" FontSize="12"/>
    </WrapPanel>
    <TabControl x:Name="tabOrder"/>
   </DockPanel>

   <DockPanel x:Name="page3" Visibility="Collapsed">
    <WrapPanel DockPanel.Dock="Top" Margin="0,0,0,6">
     <TextBlock Text="Настройка для:" VerticalAlignment="Center" Margin="0,0,8,0" Foreground="#4A5361"/>
     <ComboBox x:Name="cbSortFor" Width="260"/>
     <Border x:Name="bdSortMode" CornerRadius="9" Padding="8,1,8,2" Margin="10,0,0,0" VerticalAlignment="Center">
      <TextBlock x:Name="tSortMode" FontSize="12"/>
     </Border>
     <Button x:Name="btnSortReset" Content="Сбросить к общей" Padding="8,3" Margin="10,0,0,0"/>
     <Button x:Name="btnSortDraft" Content="Набор по умолчанию" Padding="8,3" Margin="6,0,0,0"
             ToolTip="Черновик сортировки для этой категории (правьте под себя)"/>
    </WrapPanel>
    <TextBlock DockPanel.Dock="Top" TextWrapping="Wrap" FontSize="12" Foreground="#5B6470" Margin="0,0,0,6"
     Text="Сверху вниз — порядок строк в спецификации. По системе (ИмяСистемы) спецификация сортируется всегда, отдельной строки для этого нет. «Материал и тип» и «Диаметр» кнопка считает сама; итоговый порядок пишется числом в параметр ниже — Revit сортирует по нему. Правка категории без своей сортировки создаёт свою; ×, ↑↓, перетаскивание — Ctrl+Z отменяет."/>
    <Border x:Name="bdSortWarn" DockPanel.Dock="Top" Background="#FFF3C4" BorderBrush="#E9C46A" BorderThickness="1"
            CornerRadius="6" Padding="10,6" Margin="0,0,0,8" Visibility="Collapsed">
     <TextBlock x:Name="tSortWarn" TextWrapping="Wrap" FontSize="12" Foreground="#5C3900"/>
    </Border>
    <Border DockPanel.Dock="Bottom" Margin="0,10,0,0" BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,8">
     <Grid>
      <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="20"/><ColumnDefinition Width="360"/></Grid.ColumnDefinitions>
      <StackPanel>
       <TextBlock Text="Куда кнопка пишет порядок" FontWeight="SemiBold" Margin="0,0,0,4"/>
       <WrapPanel Margin="0,2,0,0">
        <TextBlock Text="Ранг строки (по нему сортирует Revit):" Width="250" VerticalAlignment="Center"/>
        <ComboBox x:Name="cbSortParam" Width="260" IsEditable="True" IsTextSearchEnabled="True" MaxDropDownHeight="380"/>
       </WrapPanel>
       <WrapPanel Margin="0,4,0,0">
        <TextBlock Text="Материал × 100 + тип:" Width="250" VerticalAlignment="Center"/>
        <ComboBox x:Name="cbKitParam" Width="260" IsEditable="True" IsTextSearchEnabled="True" MaxDropDownHeight="380"/>
       </WrapPanel>
       <TextBlock Foreground="#5B6470" FontSize="11.5" TextWrapping="Wrap" Margin="0,4,0,0"
        Text="«— не писать —» — только ранг. Нумерация позиций и номера насосов — на вкладке «Листы»."/>
      </StackPanel>
      <StackPanel Grid.Column="2">
       <WrapPanel>
        <TextBlock Text="Малые строки: количество меньше" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbQty" Width="60" Padding="3,2"/>
       </WrapPanel>
       <Button x:Name="btnQtyRows" Content="Строки &lt; порога…" Padding="8,3" Margin="0,6,0,0" HorizontalAlignment="Left"
               ToolTip="Список строк и суммы по единицам; что скрыть — решаете галками. Сами строки не скрываются. Считается только по нажатию."/>
       <TextBlock x:Name="qtyInfo" Foreground="#5B6470" FontSize="11.5" TextWrapping="Wrap" Margin="0,4,0,0"/>
      </StackPanel>
     </Grid>
    </Border>
    <WrapPanel DockPanel.Dock="Bottom" Margin="0,8,0,0">
     <Button x:Name="btnSUp" Content="↑" Width="30" Margin="0,0,4,0" ToolTip="Выше (Ctrl+↑)"/>
     <Button x:Name="btnSDown" Content="↓" Width="30" Margin="0,0,16,0" ToolTip="Ниже (Ctrl+↓)"/>
     <TextBlock Text="Добавить параметр" VerticalAlignment="Center" Margin="0,0,6,0"/>
     <ComboBox x:Name="cbAddParam" Width="330" IsEditable="True" IsTextSearchEnabled="True" Margin="0,0,6,0"
               MaxDropDownHeight="420"/>
     <Button x:Name="btnAddParam" Content="Добавить" Padding="8,3" Margin="0,0,10,0"/>
     <TextBlock x:Name="addInfo" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center"/>
    </WrapPanel>
    <ListBox x:Name="lbSort" AllowDrop="True" HorizontalContentAlignment="Stretch" BorderBrush="#C3CAD3"
             SelectionMode="Extended"/>
   </DockPanel>

   <DockPanel x:Name="page4" Visibility="Collapsed"/>

   <ScrollViewer x:Name="page5" Visibility="Collapsed" VerticalScrollBarVisibility="Auto">
    <StackPanel MaxWidth="960" HorizontalAlignment="Left">
     <TextBlock Text="Размещение спецификаций на листах комплекта" FontWeight="SemiBold" FontSize="14"/>
     <TextBlock Foreground="#5B6470" FontSize="12" TextWrapping="Wrap" Margin="0,2,0,10"
      Text="Спецификации ставятся сверху вниз в порядке групп и номеров; не влезает — переносится на следующий лист (Форма 6). Здесь — как делить по листам, отступы, высота строк, нумерация позиций и листов."/>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Коллекция листов комплекта" FontWeight="SemiBold" Margin="0,0,0,6"/>
       <WrapPanel>
        <ComboBox x:Name="cbFolder" Width="220" IsEditable="True" Margin="0,0,10,0"/>
        <TextBlock x:Name="tFolderInfo" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center" TextWrapping="Wrap"/>
       </WrapPanel>
       <WrapPanel Margin="0,8,0,0">
        <TextBlock Text="Коллекции блоков:" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbSecFolder" Width="200" Padding="3,2" Margin="0,0,10,0"/>
        <TextBlock Text="{}{секция} — номер секции (ADSK_Номер секции); сборка «На блок» и «По всем блокам»" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center" TextWrapping="Wrap"/>
       </WrapPanel>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <Grid>
       <Grid.ColumnDefinitions><ColumnDefinition Width="320"/><ColumnDefinition Width="16"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
       <StackPanel>
        <TextBlock Text="Строки таблицы" FontWeight="SemiBold" Margin="0,0,0,8"/>
        <TextBlock Text="Название системы" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <WrapPanel>
         <TextBlock Text="Высота, мм" VerticalAlignment="Center" Margin="0,0,6,0"/>
         <TextBox x:Name="tbSysRowMm" Width="46" Padding="3,2" Margin="0,0,10,0"/>
         <TextBlock Text="шрифт" VerticalAlignment="Center" Margin="0,0,6,0"/>
         <ComboBox x:Name="cbSysFont" Width="56" Margin="0,0,10,0"/>
         <CheckBox x:Name="cbSysBold" Content="Ж" FontWeight="Bold" VerticalAlignment="Center" ToolTip="полужирный"/>
        </WrapPanel>
        <WrapPanel Margin="0,6,0,0">
         <RadioButton x:Name="rbSysL" GroupName="sysal" Content="Л" ToolTip="слева" Margin="0,0,8,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbSysC" GroupName="sysal" Content="Ц" ToolTip="по центру" Margin="0,0,8,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbSysR" GroupName="sysal" Content="П" ToolTip="справа" Margin="0,0,18,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbSysAbove" GroupName="syspos" Content="над названием" Margin="0,0,10,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbSysBelow" GroupName="syspos" Content="под названием" VerticalAlignment="Center"/>
        </WrapPanel>
        <CheckBox x:Name="cbSysShow" Margin="0,6,0,0">
         <TextBlock Text="показать на схеме — строка есть у групп с «Строкой названия системы»" Foreground="#5B6470" FontSize="12" TextWrapping="Wrap"/>
        </CheckBox>
        <Border Height="1" Background="#D5DAE0" Margin="0,10,0,10"/>
        <TextBlock Text="Название спецификации" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <WrapPanel>
         <TextBlock Text="Высота, мм" VerticalAlignment="Center" Margin="0,0,6,0"/>
         <TextBox x:Name="tbTitleMm" Width="46" Padding="3,2" Margin="0,0,10,0"/>
         <CheckBox x:Name="cbTitleTpl" Content="как в шаблоне" VerticalAlignment="Center"/>
        </WrapPanel>
        <WrapPanel Margin="0,6,0,0">
         <TextBlock Text="шрифт" VerticalAlignment="Center" Margin="0,0,6,0"/>
         <ComboBox x:Name="cbTitleFont" Width="56" Margin="0,0,10,0"/>
         <CheckBox x:Name="cbTitleBold" Content="Ж" FontWeight="Bold" Margin="0,0,18,0" VerticalAlignment="Center" ToolTip="полужирный"/>
         <RadioButton x:Name="rbTitleL" GroupName="titleal" Content="Л" ToolTip="слева" Margin="0,0,8,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbTitleC" GroupName="titleal" Content="Ц" ToolTip="по центру" Margin="0,0,8,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbTitleR" GroupName="titleal" Content="П" ToolTip="справа" VerticalAlignment="Center"/>
        </WrapPanel>
        <Border Height="1" Background="#D5DAE0" Margin="0,10,0,10"/>
        <TextBlock Text="Обычная строка" FontWeight="SemiBold" Margin="0,0,0,4"/>
        <WrapPanel>
         <RadioButton x:Name="rbRow5" GroupName="row" Content="5 мм" Margin="0,0,10,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbRow8" GroupName="row" Content="8 мм" Margin="0,0,10,0" VerticalAlignment="Center"/>
         <RadioButton x:Name="rbRowCustom" GroupName="row" Content="своя" Margin="0,0,6,0" VerticalAlignment="Center"/>
         <TextBox x:Name="tbRowMm" Width="46" Padding="3,2" Margin="0,0,10,0"/>
         <RadioButton x:Name="rbRowTpl" GroupName="row" Content="как в шаблоне" VerticalAlignment="Center"/>
        </WrapPanel>
        <TextBlock Text="Строка группирования — той же высоты, текст слева." Foreground="#5B6470" FontSize="12" TextWrapping="Wrap" Margin="0,6,0,0"/>
       </StackPanel>
       <StackPanel Grid.Column="2">
        <Border Background="#FAFBFC" BorderBrush="#E1E5EA" BorderThickness="1" CornerRadius="6" Padding="4">
         <Canvas x:Name="cvRows" Height="200" ClipToBounds="True" Background="#FAFBFC"/>
        </Border>
        <TextBlock x:Name="tRowsSum" Foreground="#5B6470" FontSize="12" TextWrapping="Wrap" Margin="0,6,0,0"/>
        <Border x:Name="bdRowsWarn" Background="#FFF6D6" BorderBrush="#E8C766" BorderThickness="1" CornerRadius="4" Padding="8,4" Margin="0,6,0,0" Visibility="Collapsed">
         <TextBlock x:Name="tRowsWarn" Foreground="#6B4E00" FontSize="12" TextWrapping="Wrap"/>
        </Border>
       </StackPanel>
      </Grid>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Группы систем (В1, Т3, К1 …)" FontWeight="SemiBold" Margin="0,0,0,6"/>
       <RadioButton x:Name="rbGrpNew" GroupName="grp" Content="Каждая группа — с нового листа" Margin="0,2"/>
       <CheckBox x:Name="cbTail" Margin="22,4,0,2">
        <WrapPanel>
         <TextBlock Text="…но если прошлая группа перенесена на лист маленьким хвостом (до " VerticalAlignment="Center"/>
         <TextBox x:Name="tbTailPct" Width="40" Padding="2,1"/>
         <TextBlock Text=" % высоты листа) — не начинать новый лист, а продолжить на нём после отступа" VerticalAlignment="Center"/>
        </WrapPanel>
       </CheckBox>
       <RadioButton x:Name="rbGrpSame" GroupName="grp" Content="Группы подряд, с отступом между ними (новый лист — только когда не влезает)" Margin="0,6,0,2"/>
       <WrapPanel Margin="0,8,0,0">
        <TextBlock Text="Отступ между группами на одном листе, мм" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbGrpGap" Width="50" Padding="3,2"/>
        <TextBlock Text="   (20 мм = 2 см)" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center"/>
       </WrapPanel>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Спецификации внутри группы" FontWeight="SemiBold" Margin="0,0,0,6"/>
       <WrapPanel>
        <TextBlock Text="Отступ между спецификациями группы, мм" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbSpecGap" Width="50" Padding="3,2"/>
        <TextBlock Text="   0 — встык" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center"/>
       </WrapPanel>
       <WrapPanel Margin="0,8,0,0">
        <TextBlock Text="Заголовок подгруппы внизу листа меньше чем с" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbMinRows" Width="40" Padding="3,2"/>
        <TextBlock Text=" строками — переносить на следующий лист вместе со строками" VerticalAlignment="Center"/>
       </WrapPanel>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Поля и листы" FontWeight="SemiBold" Margin="0,0,0,4"/>
       <TextBlock Foreground="#5B6470" FontSize="11.5" TextWrapping="Wrap" Margin="0,0,0,6"
        Text="Основа — лист А3, основная надпись Форма 6 (последующие листы); первый лист комплекта — Форма 5. Расчёт раскладки общий для обоих."/>
       <WrapPanel>
        <TextBlock Text="Слева, мм" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbLeft" Width="50" Padding="3,2"/>
        <TextBlock Text=" — от левой линии внутренней рамки до края спецификации" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center"/>
       </WrapPanel>
       <WrapPanel Margin="0,6,0,0">
        <TextBlock Text="Сверху, мм" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbTop" Width="50" Padding="3,2"/>
        <TextBlock Text=" — от верхней линии внутренней рамки до верха первой спецификации" Foreground="#5B6470" FontSize="12" VerticalAlignment="Center"/>
       </WrapPanel>
       <CheckBox x:Name="cbDelSheets" Content="удалять пустые листы спецификаций в конце" Margin="0,8,0,0"/>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Нумерация позиций (ADSK_Позиция)" FontWeight="SemiBold" Margin="0,0,0,4"/>
       <StackPanel x:Name="posModes"/>
       <TextBlock x:Name="posPreview" Foreground="#1F5FAD" FontSize="12" TextWrapping="Wrap" Margin="0,4,0,0"/>
       <TextBlock x:Name="posNote" Foreground="#5B6470" FontSize="11.5" TextWrapping="Wrap" Margin="0,3,0,0"/>
       <TextBlock Text="При повторной сборке:" Margin="0,8,0,2" FontSize="12"/>
       <RadioButton x:Name="rbPosRenum" GroupName="posupd" Content="перенумеровать все позиции" Margin="12,1"/>
       <RadioButton x:Name="rbPosKeep" GroupName="posupd" Content="сохранить номера (заполненные ADSK__Позиция не трогать, пустые — дописать)" Margin="12,1"/>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <TextBlock Text="Нумерация листов комплекта" FontWeight="SemiBold" Margin="0,0,0,6"/>
       <StackPanel x:Name="numModes"/>
       <WrapPanel x:Name="wpNumFields" Margin="22,6,0,0">
        <TextBlock Text="Префикс" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbNumPrefix" Width="90" Padding="3,2"/>
        <TextBlock Text="   начиная с" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbNumStart" Width="50" Padding="3,2"/>
        <TextBlock Text="   шаг" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbNumStep" Width="40" Padding="3,2"/>
        <TextBlock Text="   суффикс" VerticalAlignment="Center" Margin="0,0,6,0"/>
        <TextBox x:Name="tbNumSuffix" Width="70" Padding="3,2"/>
       </WrapPanel>
       <WrapPanel x:Name="wpNumExample" Margin="22,6,0,0"/>
       <Border x:Name="bdNumWarn" Background="#FFF5E1" BorderBrush="#F0D9A8" BorderThickness="1" CornerRadius="6"
               Padding="10,6" Margin="0,8,0,0" Visibility="Collapsed">
        <TextBlock x:Name="tNumWarn" TextWrapping="Wrap" FontSize="12" Foreground="#5C3900"/>
       </Border>
       <WrapPanel Margin="0,8,0,0">
        <CheckBox x:Name="cbNumStamp" Content="номер без префикса (1, 2, 3 …) писать ещё и в параметр штампа" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <TextBox x:Name="tbNumStampParam" Width="220" Padding="3,2"/>
       </WrapPanel>
      </StackPanel>
     </Border>
     <Border BorderBrush="#D5DAE0" BorderThickness="1" CornerRadius="6" Padding="12,10" Margin="0,0,0,10">
      <StackPanel>
       <CheckBox x:Name="cbCount" Content="Количество листов комплекта — в штамп каждого листа" FontWeight="SemiBold"/>
       <TextBlock x:Name="tCountParams" Margin="22,6,0,0" FontSize="12" TextWrapping="Wrap"/>
       <WrapPanel Margin="22,6,0,0">
        <TextBlock x:Name="tCountAuto" VerticalAlignment="Center" Margin="0,0,14,0"/>
        <CheckBox x:Name="cbCountOwn" Content="другое:" VerticalAlignment="Center" Margin="0,0,6,0"
                  ToolTip="Своё итоговое число (например, с листами, которые добавятся после печати) — расчёт не учитывается"/>
        <TextBox x:Name="tbCountValue" Width="50" Padding="3,2"/>
       </WrapPanel>
       <TextBlock Foreground="#5B6470" FontSize="11.5" TextWrapping="Wrap" Margin="22,6,0,0"
        Text="Пишется число листов этого комплекта (в проекте 20 листов, в комплекте 8 — на каждом листе «8»). Галка сама включает параметр Да/Нет штампа и пишет число; параметры ищутся по слову «лист» в имени."/>
      </StackPanel>
     </Border>
     <Border Background="#F3F8FE" BorderBrush="#B9CDE8" BorderThickness="1" CornerRadius="6" Padding="12,8">
      <TextBlock x:Name="tLayPrev" TextWrapping="Wrap" FontSize="12" Foreground="#174A87"/>
     </Border>
    </StackPanel>
   </ScrollViewer>

  </Grid>
  <Border Grid.Row="2" Background="#F6F7F9" BorderBrush="#DDE1E6" BorderThickness="0,1,0,0" Padding="16,10">
   <DockPanel>
    <StackPanel DockPanel.Dock="Right" Orientation="Horizontal">
     <Button x:Name="btnFix" Content="Исправить в Revit ▾" Padding="12,6" Margin="0,0,16,0"
             ToolTip="Проблемные элементы — списком поверх Revit: выделить, исправить, вернуться в мастер"/>
     <Button x:Name="btnCancel" Content="Отмена" Padding="16,6" Margin="0,0,8,0"/>
     <Button x:Name="btnBack" Content="← Назад" Padding="16,6" Margin="0,0,8,0"/>
     <Button x:Name="btnNext" Content="Далее →" Padding="18,6" Style="{DynamicResource Primary}"/>
    </StackPanel>
    <CheckBox x:Name="cbRemember" DockPanel.Dock="Left" Content="Запомнить для этого проекта" IsChecked="True" VerticalAlignment="Center"/>
    <TextBlock x:Name="tStatus" Margin="18,0,12,0" VerticalAlignment="Center" Foreground="#1F5FAD" FontSize="12"
               TextTrimming="CharacterEllipsis"/>
   </DockPanel>
  </Border>
 </Grid>
</Window>
"""


# ------------------------------------------------------------------
# помощники WPF
# ------------------------------------------------------------------
def tb(text, bold=False, size=None, color=None, wrap=False, margin=None):
    t = TextBlock()
    t.Text = text
    if bold:
        t.FontWeight = FontWeights.SemiBold
    if size:
        t.FontSize = size
    if color is not None:
        t.Foreground = color
    if wrap:
        t.TextWrapping = TextWrapping.Wrap
    if margin is not None:
        t.Margin = margin
    t.VerticalAlignment = VerticalAlignment.Center
    return t


def ancestor(el, typ):
    while el is not None:
        if isinstance(el, typ):
            return el
        p = None
        try:
            p = VisualTreeHelper.GetParent(el)
        except Exception:
            p = None
        if p is None:
            try:
                p = LogicalTreeHelper.GetParent(el)
            except Exception:
                p = None
        el = p
    return None


CHIP_TAG = u"SMCHIP"


def chip_of(src):
    """Плашка назначенного семейства (её тащат отдельно от строки списка)."""
    el = src
    while el is not None:
        if isinstance(el, Border) and el.Tag == CHIP_TAG:
            return el
        p = None
        try:
            p = VisualTreeHelper.GetParent(el)
        except Exception:
            p = None
        if p is None:
            try:
                p = LogicalTreeHelper.GetParent(el)
            except Exception:
                p = None
        el = p
    return None


def is_control_source(src):
    for typ in (TextBox, ComboBox, CheckBox, Button, RadioButton):
        if ancestor(src, typ) is not None:
            return True
    return chip_of(src) is not None


def item_index(lb, src):
    it = ancestor(src, ListBoxItem)
    if it is None:
        return -1
    return lb.ItemContainerGenerator.IndexFromContainer(it)


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def drag_label(data, single=None):
    """Подпись «призрака»: одно — его имя, несколько — «N элементов»."""
    lines = [x for x in (u"%s" % (data or u"")).split(u"\n") if x]
    if len(lines) > 1:
        n = len(lines)
        return u"{0} {1}".format(n, plural(n, u"элемент", u"элемента", u"элементов"))
    if single:
        return single
    t = lines[0] if lines else u""
    return t.split(u"\t")[-1] if u"\t" in t else t


class DragViz(object):
    """Видимое перетаскивание (как в Проводнике): «призрак» у курсора (при нескольких — «N элементов»), линия места
    вставки, подсветка цели, курсор «нельзя» над недопустимым местом. И рамка выделения (Ctrl + протягивание)."""

    def __init__(self, win, root):
        self.win = win
        self.root = root
        self.active = False
        cv = Canvas()
        cv.IsHitTestVisible = False
        Grid.SetRowSpan(cv, 9)
        Grid.SetColumnSpan(cv, 9)
        Panel.SetZIndex(cv, 1000)
        self.canvas = cv
        self.hl = Rectangle()
        self.hl.Stroke = brush("#1F5FAD")
        self.hl.StrokeThickness = 2
        self.hl.Fill = brush("#261F5FAD")
        self.hl.RadiusX = self.hl.RadiusY = 5
        self.line = Rectangle()
        self.line.Height = 3
        self.line.Fill = brush("#1F5FAD")
        self.line.RadiusX = self.line.RadiusY = 1.5
        self.mq = Rectangle()
        self.mq.Stroke = brush("#1F5FAD")
        self.mq.StrokeThickness = 1
        self.mq.Fill = brush("#261F5FAD")
        g = Border()
        g.Background = brush("#FFFFFF", True)
        g.BorderBrush = brush("#1F5FAD")
        g.BorderThickness = Thickness(1)
        g.CornerRadius = CornerRadius(4)
        g.Padding = Thickness(8, 3, 8, 3)
        g.Opacity = 0.88
        self.ghost_text = TextBlock()
        self.ghost_text.FontSize = 12
        self.ghost_text.Foreground = brush("#174A87")
        self.ghost_text.MaxWidth = 320
        self.ghost_text.TextTrimming = TextTrimming.CharacterEllipsis
        g.Child = self.ghost_text
        self.ghost = g
        for el in (self.hl, self.line, self.mq, self.ghost):
            el.Visibility = Visibility.Collapsed
            cv.Children.Add(el)
        root.Children.Add(cv)
        win.AllowDrop = True
        win.PreviewDragOver += self._move_ghost
        win.DragOver += self._nowhere
        win.Drop += self._drop_nowhere
        win.PreviewDrop += lambda s, e: self._clear_marks()
        self._mq = None

    # ---- перетаскивание ----
    def start(self, src, fmt, data, label=None):
        self.ghost_text.Text = drag_label(data, label)
        self.active = True
        try:
            DragDrop.DoDragDrop(src, DataObject(fmt, data), DragDropEffects.Move)
        finally:
            self.end()

    def end(self):
        self.active = False
        for el in (self.hl, self.line, self.ghost):
            el.Visibility = Visibility.Collapsed

    def _clear_marks(self):
        self.hl.Visibility = Visibility.Collapsed
        self.line.Visibility = Visibility.Collapsed

    def _move_ghost(self, s, e):
        self._clear_marks()
        if not self.active:
            return
        p = e.GetPosition(self.root)
        Canvas.SetLeft(self.ghost, p.X + 16)
        Canvas.SetTop(self.ghost, p.Y + 12)
        self.ghost.Visibility = Visibility.Visible

    def _nowhere(self, s, e):
        if not e.Handled:
            e.Effects = NO_DROP                     # не цель — курсор «нельзя»
            e.Handled = True

    def _drop_nowhere(self, s, e):
        e.Handled = True

    def bounds(self, el):
        try:
            if not el.IsVisible:
                return None
            return el.TransformToAncestor(self.root).TransformBounds(Rect(0, 0, el.ActualWidth, el.ActualHeight))
        except Exception:
            return None

    def show_hl(self, el):
        r = self.bounds(el)
        if r is None:
            return
        Canvas.SetLeft(self.hl, r.X)
        Canvas.SetTop(self.hl, r.Y)
        self.hl.Width = max(0.0, r.Width)
        self.hl.Height = max(0.0, r.Height)
        self.hl.Visibility = Visibility.Visible

    def show_line(self, el, after):
        r = self.bounds(el)
        if r is None:
            return
        Canvas.SetLeft(self.line, r.X)
        Canvas.SetTop(self.line, (r.Y + r.Height if after else r.Y) - 1.5)
        self.line.Width = max(0.0, r.Width)
        self.line.Visibility = Visibility.Visible

    def target(self, lb, formats, reorder=(), on_item=None):
        """Цель — ListBox: formats — что принимает; reorder — форматы «переставить» (линия вставки), остальные —
        подсветка строки (или всего списка). on_item(fmt, idx) -> False — строка не годится (курсор «нельзя»)."""
        lb.AllowDrop = True

        def over(s, e):
            fmt = next((f for f in formats if e.Data.GetDataPresent(f)), None)
            e.Handled = True
            if fmt is None:
                e.Effects = NO_DROP
                self._clear_marks()
                return
            item = ancestor(e.OriginalSource, ListBoxItem)
            if item is not None and ancestor(item, ListBox) is not lb:
                item = None
            idx = lb.ItemContainerGenerator.IndexFromContainer(item) if item is not None else -1
            if on_item is not None and on_item(fmt, idx) is False:
                e.Effects = NO_DROP
                self._clear_marks()
                return
            e.Effects = DragDropEffects.Move
            self._clear_marks()
            if fmt in reorder:
                if item is not None:
                    self.show_line(item, e.GetPosition(item).Y > item.ActualHeight / 2.0)
                elif lb.Items.Count:
                    last = lb.ItemContainerGenerator.ContainerFromIndex(lb.Items.Count - 1)
                    if last is not None:
                        self.show_line(last, True)
            elif item is not None:
                self.show_hl(item)
            else:
                self.show_hl(lb)
        lb.DragOver += over

    @staticmethod
    def drop_index(lb, e):
        """Куда вставить: по линии (верхняя / нижняя половина строки); мимо строк — в конец."""
        item = ancestor(e.OriginalSource, ListBoxItem)
        if item is None or ancestor(item, ListBox) is not lb:
            return lb.Items.Count
        i = lb.ItemContainerGenerator.IndexFromContainer(item)
        return i + 1 if e.GetPosition(item).Y > item.ActualHeight / 2.0 else i

    # ---- рамка (Ctrl + протягивание) ----
    def marquee(self, host, apply_fn, start_fn=None):
        """host — где тянуть; apply_fn(rect в координатах root, итог?) выделяет задетое. Esc — mq_cancel()."""
        def down(s, e):
            if (Keyboard.Modifiers & ModifierKeys.Control) != ModifierKeys.Control:
                return
            for typ in (TextBox, ComboBox, Button, CheckBox, RadioButton):
                if ancestor(e.OriginalSource, typ) is not None:
                    return
            self._mq = {"p0": e.GetPosition(self.root), "moved": False, "host": host, "apply": apply_fn,
                        "state": start_fn() if start_fn else None}
            host.CaptureMouse()

        def move(s, e):
            m = self._mq
            if m is None or m["host"] is not host:
                return
            p = e.GetPosition(self.root)
            if not m["moved"]:
                if abs(p.X - m["p0"].X) < 4 and abs(p.Y - m["p0"].Y) < 4:
                    return
                m["moved"] = True
                self.mq.Visibility = Visibility.Visible
            r = Rect(min(p.X, m["p0"].X), min(p.Y, m["p0"].Y), abs(p.X - m["p0"].X), abs(p.Y - m["p0"].Y))
            Canvas.SetLeft(self.mq, r.X)
            Canvas.SetTop(self.mq, r.Y)
            self.mq.Width = r.Width
            self.mq.Height = r.Height
            apply_fn(r, m["state"])
            e.Handled = True

        def up(s, e):
            m = self._mq
            if m is None or m["host"] is not host:
                return
            self._mq = None
            host.ReleaseMouseCapture()
            self.mq.Visibility = Visibility.Collapsed
            if m["moved"]:
                e.Handled = True
        host.PreviewMouseLeftButtonDown += down
        host.PreviewMouseMove += move
        host.PreviewMouseLeftButtonUp += up

    def mq_cancel(self, restore=None):
        m = self._mq
        if m is None:
            return False
        self._mq = None
        try:
            m["host"].ReleaseMouseCapture()
        except Exception:
            pass
        self.mq.Visibility = Visibility.Collapsed
        if restore is not None:
            restore(m["state"])
        return True


class Dragger(object):
    """Перетаскивание строк ListBox: payload(index) -> (формат, данные). Несколько выбранных — тянутся вместе."""

    def __init__(self, lb, payload, viz=None):
        self.lb = lb
        self.viz = viz
        self.payload = payload
        self.start = None
        self.idx = -1
        self.pending = -1
        lb.PreviewMouseLeftButtonDown += self.down
        lb.PreviewMouseMove += self.move
        lb.PreviewMouseLeftButtonUp += self.up

    def down(self, s, e):
        self.pending = -1
        if is_control_source(e.OriginalSource):
            self.start = None
            return
        self.idx = item_index(self.lb, e.OriginalSource)
        self.start = e.GetPosition(None) if self.idx >= 0 else None
        if self.idx >= 0 and int(Keyboard.Modifiers) == 0:
            it = self.lb.Items[self.idx]
            if getattr(it, "IsSelected", False) and self.lb.SelectedItems.Count > 1:
                self.pending = self.idx          # не сбрасывать выделение: может начаться перетаскивание всех
                e.Handled = True

    def up(self, s, e):
        if self.pending >= 0:                    # щелчок без перетаскивания — выбрать только эту строку
            it = self.lb.Items[self.pending]
            self.lb.SelectedItems.Clear()
            it.IsSelected = True
        self.pending = -1

    def move(self, s, e):
        if self.start is None or e.LeftButton != MouseButtonState.Pressed:
            return
        p = e.GetPosition(None)
        if abs(p.X - self.start.X) < SystemParameters.MinimumHorizontalDragDistance and \
                abs(p.Y - self.start.Y) < SystemParameters.MinimumVerticalDragDistance:
            return
        self.start = None
        self.pending = -1
        pl = self.payload(self.idx)
        if pl is None:
            return
        if self.viz is not None:
            self.viz.start(self.lb, pl[0], pl[1], pl[2] if len(pl) > 2 else None)
        else:
            DragDrop.DoDragDrop(self.lb, DataObject(pl[0], pl[1]), DragDropEffects.Move)


_LAT = dict(zip(u"BTKHMPAOCEX", u"ВТКНМРАОСЕХ"))


def sys_color(D, abbr, kind="pipe"):
    """Цвет системы по таблице D.SYSTEM_COLORS: (линия, подпись, светлый). Вентиляция — нейтральный."""
    if kind == "duct":
        return D.SYSTEM_COLOR_OTHER
    a = u"".join(_LAT.get(ch, ch) for ch in (abbr or u"").strip().upper())
    best = None
    for k, line, text, light in D.SYSTEM_COLORS:
        if a == k:
            return line, text, light
        if a.startswith(k) and (best is None or len(k) > len(best[0])):
            best = (k, line, text, light)
    return best[1:] if best else D.SYSTEM_COLOR_OTHER


def model_color(hexs):
    """Цвет линий типа системы из модели -> (линия, подпись, светлый): подпись — темнее, светлый — по яркости."""
    h = hexs.lstrip("#")
    c = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    lum = (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255.0
    k = 0.45 if lum > 0.6 else 0.15
    dark = "#" + u"".join(u"%02X" % int(round(v * (1 - k))) for v in c)
    return "#" + h.upper(), dark, lum > 0.75


def ask_text(owner, title, prompt, default=u""):
    """Маленькое окно ввода строки -> текст или None (Отмена / Esc)."""
    w = Window()
    T.dress(w)
    w.Title = title
    w.Width = 420
    w.SizeToContent = SizeToContent.Height
    w.ResizeMode = ResizeMode.NoResize
    w.WindowStartupLocation = WindowStartupLocation.CenterOwner
    w.ShowInTaskbar = False
    w.FontFamily = FontFamily(u"Segoe UI")
    w.FontSize = 13
    try:
        w.Owner = owner
    except Exception:
        w.WindowStartupLocation = WindowStartupLocation.CenterScreen
    sp = StackPanel()
    sp.Margin = Thickness(14, 12, 14, 12)
    sp.Children.Add(tb(prompt, wrap=True, margin=Thickness(0, 0, 0, 8)))
    box = TextBox()
    box.Text = default or u""
    box.Padding = Thickness(4, 3, 4, 3)
    sp.Children.Add(box)
    bar = StackPanel()
    bar.Orientation = Orientation.Horizontal
    bar.HorizontalAlignment = HorizontalAlignment.Right
    bar.Margin = Thickness(0, 12, 0, 0)
    res = {"v": None}
    ok = Button()
    ok.Content = u"Создать"
    ok.IsDefault = True
    ok.Padding = Thickness(16, 4, 16, 4)
    ok.Margin = Thickness(0, 0, 8, 0)

    def done(s, e):
        res["v"] = (box.Text or u"").strip() or None
        w.Close()
    ok.Click += done
    cancel = Button()
    cancel.Content = u"Отмена"
    cancel.IsCancel = True
    cancel.Padding = Thickness(16, 4, 16, 4)
    bar.Children.Add(ok)
    bar.Children.Add(cancel)
    sp.Children.Add(bar)
    w.Content = sp
    box.Loaded += lambda s, e: (box.Focus(), box.SelectAll())
    w.ShowDialog()
    return res["v"]


def pastel(hexs, k=0.82):
    """Цвет, смешанный с белым (k — доля белого): пастельный фон чипа."""
    h = hexs.lstrip("#")
    c = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + u"".join(u"%02X" % int(round(v + (255 - v) * k)) for v in c)


def sys_bg(line, k):
    """Фон таблетки системы: светлая тема — пастельный (k — доля белого), тёмная — цвет системы на тёмном фоне."""
    if T.DARK:
        return T.raw_brush(T.under_white(T.mix(line, T.BG, 0.45)))
    return brush(pastel(line, k))


def sys_line(line, k):
    """Рамка таблетки системы."""
    if T.DARK:
        return T.raw_brush(T.mix(line, T.BG, 0.75))
    return brush(pastel(line, k))


def sys_text(text, line=None):
    """Текст внутри таблетки системы: светлая тема — цвет системы, тёмная — белый (решение 02.11.2026)."""
    if T.DARK:
        return T.raw_brush("#FFFFFF")
    return brush(text)


def sys_name(text, line):
    """Имя системы в списке слева: светлая тема — цвет системы, тёмная — светлый оттенок цвета системы."""
    if T.DARK:
        return T.raw_brush(T.mix(line, "#FFFFFF", 0.30))
    return brush(text)


def color_square(line, light, size=10):
    sq = Border()
    sq.Width = sq.Height = size
    sq.CornerRadius = CornerRadius(2)
    sq.Background = brush(line)
    sq.BorderThickness = Thickness(1 if light else 0)
    sq.BorderBrush = brush("#4A5361")
    sq.VerticalAlignment = VerticalAlignment.Center
    sq.Margin = Thickness(0, 0, 5, 0)
    return sq


# ------------------------------------------------------------------
# окно
# ------------------------------------------------------------------
class Wizard(object):
    def __init__(self, core, infos, systems, cfg):
        self.core = core
        self.infos = infos
        self.systems = systems
        self.sysinfo = dict((s[0], s) for s in systems)
        self.cfg = copy.deepcopy(cfg)
        self.result = None
        self.page = 0
        theme_init()
        self.win = XamlReader.Parse(T.xaml(XAML))
        f = self.win.FindName
        for n in ("steps", "page0", "page1", "page2", "page3", "page4", "page5", "sysInfo",
                  "rbGrpNew", "rbGrpSame", "cbTail", "tbTailPct", "tbGrpGap", "tbSpecGap", "tbMinRows", "tbLeft", "tbTop",
                  "tLayPrev", "numModes", "tbNumStart", "tbNumPrefix", "cbNumStamp", "tbNumStampParam", "lbSystems", "lbGroups", "btnToNew", "btnToSel", "btnSkip",
                  "btnMerge", "btnSplit", "btnAuto", "btnGUp", "btnGDown", "tbSearch", "tvCats", "treeInfo", "btnExpand",
                  "btnCollapse", "tabOrder", "rbTypeDiam", "rbDiamType", "cbSortFor", "posModes", "posPreview", "posNote", "tbQty",
                  "btnSUp", "btnSDown", "cbAddParam", "btnAddParam", "addInfo", "lbSort", "btnCancel", "btnBack", "btnNext", "cbDelSheets",
                  "cbRemember", "root", "cbPreset", "btnPresetApply", "btnPresetSave", "btnPresetMenu", "tStatus",
                  "btnLink", "btnUnlink", "btnQtyRows", "qtyInfo", "cbFolder", "tFolderInfo", "rbRow5", "rbRow8",
                  "rbRowCustom", "rbRowTpl", "tbRowMm", "tbTitleMm", "tbSysRowMm", "cbSysFont", "cbSysBold", "rbSysL",
                  "rbSysC", "rbSysR", "rbSysAbove", "rbSysBelow", "cbSysShow", "cbTitleTpl", "cbTitleFont",
                  "cbTitleBold", "rbTitleL", "rbTitleC", "rbTitleR", "tRowsSum", "bdRowsWarn", "tRowsWarn", "tbSecFolder", "tbNumSuffix", "bdNumWarn",
                  "tNumWarn", "cbCount", "marqRect", "btnFillQty", "cbOrderOn", "tOrderInfo", "bdSortMode",
                  "tSortMode", "btnSortReset", "btnSortDraft", "bdSortWarn", "tSortWarn", "cbSortParam", "cbKitParam",
                  "cvRows", "rbPosRenum", "rbPosKeep", "wpNumFields", "wpNumExample", "tbNumStep", "tCountParams",
                  "tCountAuto", "cbCountOwn", "tbCountValue", "btnDisc", "tGrpNote", "btnFix", "btnTheme"):
            setattr(self, n, f(n))
        self.sel_groups = set()
        self.sel_chips = set()
        self._chip_elems = []
        self._mq = None
        self._gdrag = None
        self.anchor = None
        self.tree_nodes = []
        self.order_tabs = {}
        self._sheet_snap = None
        self._frame = None              # высота штампа листа комплекта, мм (для оценки числа листов)
        self._est_rows = None           # (подпись, строки будущих спецификаций) — кэш оценки числа листов
        self._metrics = None            # ширины граф, шапка, шрифт шаблонов «О_…» (для переноса строк)
        self._stamp_lists = None
        self._edit_orig = None
        self.sort_key = "common"
        self._enter_actions = []        # (поле, действие): Enter в поле = «Применить»
        self.sel_fchips = set()         # выбранные плашки семейств на вкладке 3: (ключ, поле, тег)
        self._fam_open = set()          # раскрытые семейства (▸) в «Не распределено»: (ключ, семейство)
        self.mat_items = []
        self.mat_run = set()
        T.dress(self.win, base=True, root=self.root)
        self._init_paper()
        self.viz = DragViz(self.win, self.root)
        self._init_page0()
        self._init_page1()
        self._init_page2()
        self._init_page3()
        self._init_page4()
        self._init_page5()
        self._init_presets()
        self.btnCancel.Click += lambda s, e: self.win.Close()
        self._init_disc_button()
        self._init_fix_button()
        self._init_theme_button()
        self.btnBack.Click += lambda s, e: self.go(self.page - 1)
        self.btnNext.Click += self.on_next
        self.go(0)
        self._init_history()

    # ---------------- навигация ----------------
    def go(self, p):
        if p < 0 or p > LAST:
            return
        if self.page == 1 and p != 1:
            self.collect_hidden()
        self.page = p
        for i in range(LAST + 1):
            getattr(self, "page%d" % i).Visibility = Visibility.Visible if i == p else Visibility.Collapsed
        if p == 1:
            self.build_tree()
        if p == 2:
            self.refresh_order_tabs()
        if p == 3:
            self.draw_sort()
        if p == 4:
            self.draw_paint()
        if p == 5:
            self._load_sheet_data()
            self._spec_prev = None
            self.draw_pos_preview()
            self.draw_layout_prev()
        self.btnBack.IsEnabled = p > 0
        self.btnNext.Content = u"Собрать спецификации" if p == LAST else u"Далее →"
        self.draw_steps()

    def _init_disc_button(self):
        """Кнопка раздела проекта слева вверху («ОВ ▾»): закрывает мастер с пометкой — script.py покажет окно
        «Сменить раздел проекта» и откроет мастер снова с теми же настройками."""
        d = disc_by_key(self.core.D, self.cfg.get("discipline"))
        if d is None:
            self.btnDisc.Visibility = Visibility.Collapsed
            return
        self.btnDisc.Content = u"{0} ▾".format(d["code"])

        def click(s, e):
            self._sync()
            self.cfg["_change_discipline"] = True
            self.result = self.cfg
            self.win.Close()
        self.btnDisc.Click += click

    def _init_fix_button(self):
        """«Исправить в Revit ▾»: меню видов проблем с числом элементов; выбор закрывает мастер с пометкой —
        script.py откроет панель исправлений поверх Revit (vks_fix), потом мастер снова с теми же настройками."""
        if not hasattr(self.core, "problems"):
            self.btnFix.Visibility = Visibility.Collapsed
            return

        def open_menu(s, e):
            self._sync()
            try:
                found = self.core.problems(self.infos, self.cfg)
            except Exception as ex:
                self.status(u"Проблемные элементы не посчитаны: {0}".format(ex))
                return
            cm = T.menu(ContextMenu())
            for k, t in self.core.PROBLEMS:
                n = len(found.get(k) or [])
                mi = MenuItem()
                mi.Header = u"{0} — {1}".format(t, n)
                mi.IsEnabled = n > 0

                def pick(s_, e_, k=k):
                    self._sync()
                    self.cfg["_fix"] = k
                    self.result = self.cfg
                    self.win.Close()
                mi.Click += pick
                cm.Items.Add(mi)
            cm.PlacementTarget = self.btnFix
            cm.IsOpen = True
        self.btnFix.Click += open_menu

    def _init_paper(self):
        """Схема строк на «Листах» — лист бумаги: белый в любой теме."""
        cv = self.cvRows
        cv.Background = pbrush("#FAFBFC")
        bd = cv.Parent
        if isinstance(bd, Border):
            bd.Background = pbrush("#FAFBFC")
            bd.BorderBrush = pbrush("#E1E5EA")
            T.paper(bd)
        T.paper(cv)

    def _init_theme_button(self):
        """Кнопка темы в шапке (☀ / ☾): меню «Как в Revit / Светлая / Тёмная»; смена — сразу, без закрытия окна,
        выбор запоминается (%LOCALAPPDATA%\\Spec_Manager\\ui.json)."""
        self._show_theme()

        def open_menu(s, e):
            cm = T.menu(ContextMenu())
            for m in T.MODES:
                mi = MenuItem()
                mi.Header = T.mode_label(m)
                mi.IsCheckable = True
                mi.IsChecked = (m == T.MODE)
                mi.Click += (lambda m_: (lambda s_, e_: self.set_theme(m_)))(m)
                cm.Items.Add(mi)
            cm.PlacementTarget = self.btnTheme
            cm.IsOpen = True
        self.btnTheme.Click += open_menu

    def _show_theme(self):
        self.btnTheme.Content = u"☾" if T.DARK else u"☀"

    def set_theme(self, mode):
        """Сменить тему открытого окна: стили, цвета элементов, общие кисти."""
        dark = T.set_mode(mode)
        if dark == T.DARK:
            return
        try:
            T.switch(self.win, dark, roots=[self.root])
            _consts()
            self._show_theme()
            self.draw_steps()
            self.draw_systems()
            self.draw_groups()
            self.status(u"Тема окна: {0}.".format(u"тёмная" if dark else u"светлая"))
        except Exception as ex:
            self.status(u"Тема не сменилась: {0}".format(ex))

    def draw_steps(self):
        self.steps.Children.Clear()
        for i, name in enumerate(STEPS):
            b = Border()
            b.CornerRadius = CornerRadius(6)
            b.Padding = Thickness(10, 5, 12, 5)
            b.Margin = Thickness(0, 0, 8, 0)
            sp = StackPanel()
            sp.Orientation = Orientation.Horizontal
            mark = u"✓" if i < self.page else str(i + 1)
            if i == self.page:
                b.Background = C_BLUE_BG
                sp.Children.Add(tb(u"{0}  {1}".format(mark, name), bold=True, color=Brushes.White))
            else:
                sp.Children.Add(tb(u"{0}  {1}".format(mark, name), color=C_DONE if i < self.page else brush("#4A5361")))
            b.Child = sp
            self.steps.Children.Add(b)

    def on_next(self, s, e):
        if self.page < LAST:
            self.go(self.page + 1)
            return
        self.collect_sort_extras()
        self._set_rank_params()
        self.collect_paint()
        self.collect_layout()
        self.cfg["_remember"] = bool(self.cbRemember.IsChecked)
        need, how = self._sheets_need(self._lo())
        if how == "est" and need:
            self.cfg["_est_sheets"] = need     # в отчёт сборки: «оценка была ≈ N»
        self.result = self.cfg
        self.win.Close()

    # ---------------- отмена / повтор, клавиатура ----------------
    def _later(self, fn):
        """Выполнить после текущего события (перерисовка карточки из её же обработчика)."""
        try:
            self.win.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(fn))
        except Exception:
            fn()

    def _sync(self):
        """Значения полей окна — в self.cfg (только чтение элементов окна)."""
        if self.tree_nodes:
            self.collect_hidden()
        self.collect_sort_extras()
        self.collect_paint()
        self.collect_layout()

    def _state(self):
        self._sync()
        return json.dumps(self.cfg, sort_keys=True, ensure_ascii=False)

    def _init_history(self):
        self.hist, self.redo = [], []
        self._restoring = False
        self._pending = False
        self._last = self._state()
        w = self.win
        w.PreviewKeyDown += self.on_key
        w.PreviewMouseLeftButtonUp += lambda s, e: self._queue_check()
        w.PreviewKeyUp += lambda s, e: self._queue_check()
        w.PreviewDrop += lambda s, e: self._queue_check()
        w.PreviewGotKeyboardFocus += self._on_focus
        w.AddHandler(Selector.SelectionChangedEvent, SelectionChangedEventHandler(lambda s, e: self._queue_check()))

    def _queue_check(self):
        if self._pending or self._restoring:
            return
        self._pending = True
        self._later(self._check_change)

    def _check_change(self):
        self._pending = False
        if self._restoring:
            return
        try:
            cur = self._state()
        except Exception:
            return
        if cur != self._last:
            self.hist.append((self._last, self.page))
            if len(self.hist) > HISTORY_MAX:
                self.hist.pop(0)
            self.redo = []
            self._last = cur

    def _restore(self, src, dst):
        self._check_change()                          # незаписанное изменение — сначала в историю
        if not src:
            self.status(u"Нечего отменять" if src is self.hist else u"Нечего повторять")
            return
        state, page = src.pop()
        dst.append((self._last, page))
        self._restoring = True
        try:
            keep_sel = set(self.sel_groups)
            self.page = page
            self.reload_cfg(json.loads(state))
            self.sel_groups = set(i for i in keep_sel if i < len(self.cfg["groups"]))
            if self.page == 0 and self.sel_groups:
                self.draw_groups()
            self._last = self._state()
        finally:
            self._restoring = False
        self.status((u"Отменено" if dst is self.redo else u"Повторено") +
                    u" · окно «{0}» · осталось отмен: {1}".format(STEPS[page], len(self.hist)))

    def undo(self):
        self._restore(self.hist, self.redo)

    def redo_(self):
        self._restore(self.redo, self.hist)

    def _on_focus(self, s, e):
        t = e.NewFocus
        if isinstance(t, TextBox):
            self._edit_orig = (t, t.Text)

    def on_key(self, s, e):
        k = e.Key
        mods = Keyboard.Modifiers
        ctrl = (mods & ModifierKeys.Control) == ModifierKeys.Control
        shift = (mods & ModifierKeys.Shift) == ModifierKeys.Shift
        foc = Keyboard.FocusedElement
        in_text = isinstance(foc, TextBox)
        if ctrl and k in (Key.Z, Key.Y):
            if in_text:
                return                                 # в поле — отмена набора средствами поля
            if k == Key.Y or shift:
                self.redo_()
            else:
                self.undo()
            e.Handled = True
            return
        if k in (Key.Return, Key.Enter) and in_text and not foc.AcceptsReturn:
            combo = ancestor(foc, ComboBox)
            act = next((fn for t, fn in self._enter_actions if t is foc), None)
            if combo is not None and combo is self.cbAddParam:
                self.on_add_param(None, None)
            elif act is not None:
                act()                                                        # Enter в полях группы = «Применить»
            else:
                foc.MoveFocus(TraversalRequest(FocusNavigationDirection.Next))   # принять значение
            e.Handled = True
            return
        if k == Key.Escape and (self.mq_cancel() or self.viz.mq_cancel(self._fchip_restore)):
            e.Handled = True
            return
        if k == Key.Escape:
            if in_text:
                o = self._edit_orig
                if o is not None and o[0] is foc:
                    foc.Text = o[1]                    # незавершённый ввод — отменить
                self.root.Focus()
                Keyboard.ClearFocus()
                e.Handled = True
                return
            if self.page == 0 and self.clear_selection():
                e.Handled = True
            elif self.page == 2 and self._clear_order_selection():
                e.Handled = True
            elif self.page == 3 and self.lbSort.SelectedItems.Count:
                self.lbSort.SelectedItems.Clear()
                e.Handled = True
            return
        if in_text or isinstance(foc, ComboBox) or ancestor(foc, ComboBox) is not None:
            return
        if self.page == 3 and ctrl and k in (Key.Up, Key.Down):
            self._move_sort(-1 if k == Key.Up else 1)
            e.Handled = True
            return
        if self.page == 2 and ctrl and k in (Key.Up, Key.Down):
            self._move_focused_entry(-1 if k == Key.Up else 1)
            e.Handled = True
            return
        if self.page != 0:
            return
        if k == Key.Tab and not ctrl and len(self.sel_groups) >= 2:
            self.link_selected()
            e.Handled = True
        elif ctrl and k in (Key.Up, Key.Down):
            self.move_groups(-1 if k == Key.Up else 1)
            e.Handled = True
        elif ctrl and k in (Key.OemPlus, Key.Add):
            self.on_merge(None, None)
            e.Handled = True
        elif ctrl and k in (Key.OemMinus, Key.Subtract):
            self.on_split(None, None)
            e.Handled = True

    # ---------------- 1. системы ----------------
    def _init_page0(self):
        kinds = getattr(self.core, "FOUND_KINDS", None) or []
        kt = u" и ".join({"pipe": u"трубопроводы", "duct": u"воздуховоды"}.get(k, k) for k in kinds)
        ncat = len(set(i.key for i in self.infos))
        if self._by_grouping():
            nfb = len([s_ for s_ in self.systems if self.core.is_fallback_unit(s_[0])])
            nun = len(getattr(self.core, "UNRESOLVED", None) or [])
            self.sysInfo.Text = (u"{0} значений ADSK_Группирование · по сокращению системы: {1} · не определено: "
                                 u"{2} эл. (пусто, сокращения систем разные) · найдены {3}").format(
                len(self.systems) - nfb, nfb, nun, kt or u"—")
            self.tGrpNote.Text = (u"Группа элемента — по ADSK_Группирование (одно значение — одна группа, сколько бы "
                                  u"систем ни было у элемента); пусто — по сокращению системы (В 0, В 1, В 2 → «В»); "
                                  u"сокращения разные — не определено, в спецификации не попадёт (список — в отчёте "
                                  u"сборки). Вложенные семейства с пустым значением — по родителю. «Исключить» — не "
                                  u"специфицировать. Имя группы пишется в ADSK_Система_Обозначение (по нему фильтр).")
        else:
            self.sysInfo.Text = u"{0} систем · найдены {1} · категорий с элементами: {2}".format(
                len(self.systems), kt or u"—", ncat)
        self.btnToNew.Click += self.on_to_new
        self.btnToSel.Click += self.on_to_sel
        self.btnSkip.Click += self.on_skip
        self.btnMerge.Click += self.on_merge
        self.btnSplit.Click += self.on_split
        self.btnAuto.Click += self.on_auto
        self.btnGUp.Click += lambda s, e: self.move_groups(-1)
        self.btnGDown.Click += lambda s, e: self.move_groups(1)
        self.btnLink.Click += lambda s, e: self.link_selected()
        self.btnUnlink.Click += lambda s, e: self.unlink_selected()
        Dragger(self.lbSystems, self._sys_payload, self.viz)
        self.lbGroups.Drop += self.on_group_drop
        self.viz.target(self.lbGroups, ["SM_SYS", "SM_SYSCHIP", "SM_GRP", "SM_PILL"], reorder=("SM_GRP",))
        self.lbSystems.Drop += self.on_systems_drop
        self.viz.target(self.lbSystems, ["SM_SYSCHIP"])
        self.page0.PreviewMouseLeftButtonDown += self.mq_down
        self.page0.PreviewMouseMove += self.mq_move
        self.page0.PreviewMouseLeftButtonUp += self.mq_up
        self.draw_systems()
        self.draw_groups()

    def _by_grouping(self):
        return getattr(self.core, "GROUP_BY", ["systems"])[0] == "grouping"

    def on_drag_over(self, s, e):
        e.Effects = DragDropEffects.Move
        e.Handled = True

    def _sys_payload(self, idx):
        names = [it.Tag for it in self.lbSystems.SelectedItems if it.Tag]
        item = self.lbSystems.Items[idx] if 0 <= idx < self.lbSystems.Items.Count else None
        if item is not None and item.Tag and item.Tag not in names:
            names = [item.Tag]
        else:
            names += [n for n in self._ordered(self.sel_chips) if n not in names]   # и чипы, выделенные рамкой
        return ("SM_SYS", u"\n".join(names)) if names else None

    def _ordered(self, names):
        order = [s[0] for s in self.systems]
        return sorted(names, key=lambda n: order.index(n) if n in order else 999)

    def _sys_color(self, name):
        info = self.sysinfo.get(name)
        ab = info[2] if info else u""
        return sys_color(self.core.D, ab, getattr(self.core, "SYS_KIND", {}).get(name, "pipe"))

    def group_of(self, sysname):
        for i, g in enumerate(self.cfg["groups"]):
            if sysname in g["systems"]:
                return i
        return -1

    def draw_systems(self):
        self.lbSystems.Items.Clear()
        last = None
        byg = self._by_grouping()
        for name, cnt, ab, desc in self.systems:
            if byg:
                head = (u"Без системы и без ADSK_Группирование" if name == self.core.D.NO_SYSTEM else
                        u"По сокращению системы — ADSK_Группирование пусто" if self.core.is_fallback_unit(name) else
                        u"ADSK_Группирование — значения")
            else:
                head = (ab + u" · " + desc) if ab else u"Без системы"
            if head != last:
                h = ListBoxItem()
                h.IsEnabled = False
                h.Focusable = False
                h.Content = tb(head, bold=True, size=11, color=brush("#3D4652"), margin=Thickness(2, 6, 0, 0))
                self.lbSystems.Items.Add(h)
                last = head
            it = ListBoxItem()
            it.Tag = name
            g = Grid()
            for w in (GridLength(1, GridUnitType.Star), GridLength.Auto, GridLength.Auto):
                cd = ColumnDefinition()
                cd.Width = w
                g.ColumnDefinitions.Add(cd)
            t1 = StackPanel()
            t1.Orientation = Orientation.Horizontal
            line, text, light = self._sys_color(name)
            t1.Children.Add(tb(u"⋮⋮ ", color=brush("#8A939E")))
            t1.Children.Add(color_square(line, light))
            t1.Children.Add(tb(name, bold=True, color=sys_name(text, line)))
            if byg and self.core.is_fallback_unit(name):
                t1.Children.Add(tb(u"  по сокращению", size=11, color=brush("#B3261E")))
            g.Children.Add(t1)
            t2 = tb(u"{0:,}".format(cnt).replace(u",", u" "), color=C_MUTED, margin=Thickness(8, 0, 8, 0))
            Grid.SetColumn(t2, 1)
            g.Children.Add(t2)
            gi = self.group_of(name)
            skipped = gi < 0 and name in (self.cfg.get("skip_units") or [])
            bd = Border()
            bd.CornerRadius = CornerRadius(9)
            bd.Padding = Thickness(7, 0, 7, 1)
            bd.Background = brush("#EEF1F4") if gi >= 0 else (brush("#E4E7EB") if skipped else brush("#FFF0D6"))
            bd.Child = tb(u"гр. {0}".format(gi + 1) if gi >= 0 else (u"исключено" if skipped else u"не в группе"),
                          size=11, color=C_MUTED if skipped else None)
            if skipped:
                bd.ToolTip = u"Не специфицируется. Вернуть — «В новую группу» или перетащить в группу."
                t1.Opacity = 0.55
            Grid.SetColumn(bd, 2)
            g.Children.Add(bd)
            it.Content = g
            it.Padding = Thickness(6, 3, 6, 3)
            self.lbSystems.Items.Add(it)

    def _color_of(self, sysname, abbr=None):
        """Цвет системы: ОВ — из модели (цвет линий типа системы), иначе таблица ВК, иначе серый; ВК — таблица ВК
        (решение 0.3.2), нет в ней — из модели. -> (линия, подпись, светлый)."""
        D = self.core.D
        if abbr is None:
            abbr = self.core.abbr_of(sysname, getattr(self.core, "AMAP", None) or {})
        kind = getattr(self.core, "SYS_KIND", {}).get(sysname, "pipe")
        tab = sys_color(D, abbr, kind)
        hx = (getattr(self.core, "SYS_COLORS", None) or {}).get(sysname)
        if hx and (self.cfg.get("discipline") == "OV" or tab == D.SYSTEM_COLOR_OTHER):
            return model_color(hx)
        return tab

    def _sys_pills(self, panel, g):
        """ADSK_Группирование: после чипов значений — системы элементов группы, свёрнутые по сокращению
        («ВЕ · 84»; щелчок — развернуть). Таблетку можно перетащить в другую группу или в пустое место (новая
        группа) — ADSK_Группирование элементов этих систем перепишется при сборке. «⚠ N» — элементы, взятые по
        системе (ADSK_Группирование пусто)."""
        usys = getattr(self.core, "UNIT_SYS", None) or {}
        cnt, src = {}, {}
        for u_ in g["systems"]:
            for sn, n in (usys.get(u_) or {}).items():
                cnt[sn] = cnt.get(sn, 0) + n
                src.setdefault(sn, []).append(u_)
        sep = Border()
        sep.Width = 1
        sep.Height = 16
        sep.Background = C_LINE
        sep.Margin = Thickness(4, 0, 6, 0)
        panel.Children.Add(sep)
        panel.Children.Add(tb(u"системы:" if cnt else u"системы: —", size=11, color=C_MUTED,
                              margin=Thickness(0, 0, 4, 0)))
        amap = getattr(self.core, "AMAP", None) or {}
        moved = {}
        for m in self.cfg.get("moves") or []:
            if m.get("to") in g["systems"]:
                moved[m.get("sys")] = m.get("from")
        by_ab = {}
        for sn in cnt:
            by_ab.setdefault(self.core.abbr_of(sn, amap) or sn, []).append(sn)
        opened = getattr(self, "_open_pills", None)
        if opened is None:
            opened = self._open_pills = set()
        for ab in sorted(by_ab, key=lambda x: self.core.nat_key(x)):
            names = sorted(by_ab[ab], key=lambda x: self.core.nat_key(x))
            key = (g["name"], ab)
            if len(names) > 1 and key not in opened:
                self._pill(panel, g, names, src, cnt, u"{0} · {1}".format(ab, len(names)), ab, key, moved)
            else:
                for sn in names:
                    self._pill(panel, g, [sn], src, cnt, sn, ab, key if len(names) > 1 else None, moved)
        nfb = sum(getattr(self.core, "UNIT_FALLBACK", {}).get(u_, 0) for u_ in g["systems"]
                  if self.core.is_fallback_unit(u_))
        if nfb:
            w = tb(u" ⚠ {0} эл.".format(nfb), bold=True, size=12, color=brush("#987020"), margin=Thickness(6, 0, 0, 0))
            w.ToolTip = (u"ADSK_Группирование пусто — взяты по сокращению системы. Заполните ADSK_Группирование, "
                         u"если группа другая.")
            panel.Children.Add(w)

    def _pill(self, panel, g, names, src, cnt, text, ab, key, moved):
        """Таблетка системы (или свёрнутых систем одного сокращения): цвет, подсказка, щелчок — развернуть /
        свернуть, перетаскивание — перенос в другую группу, «↩» — отменить перенос."""
        line, tcol, light = self._color_of(names[0], ab)
        was = [moved[n] for n in names if n in moved]
        b = Border()
        b.CornerRadius = CornerRadius(9)
        b.Padding = Thickness(7, 0, 7, 1)
        b.Margin = Thickness(0, 1, 4, 1)
        b.Background = sys_bg(line, 0.70 if light else 0.80)
        b.BorderBrush = brush("#C27A00") if was else sys_line(line, 0.45)
        b.BorderThickness = Thickness(1.5 if was else 1)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Children.Add(tb(text, size=11, bold=True, color=sys_text(tcol)))
        n_el = sum(cnt.get(n, 0) for n in names)
        lines = [u"{0}: {1} эл.".format(n, cnt.get(n, 0)) for n in names[:40]]
        if len(names) > 40:
            lines.append(u"… ещё {0}".format(len(names) - 40))
        tip = u"\n".join(lines)
        if key is not None:
            tip += u"\n\nЩелчок — " + (u"развернуть" if len(names) > 1 else u"свернуть")
        tip += u"\nПеретащите в другую группу или в пустое место (новая группа) — ADSK_Группирование {0} эл. " \
               u"перепишется при сборке.".format(n_el)
        if was:
            tip = u"Перенесено из {0} — запишется при сборке.\n".format(u", ".join(sorted(set(was)))) + tip
            x = Button()
            x.Content = u"↩"
            x.Padding = Thickness(3, 0, 2, 0)
            x.Margin = Thickness(3, 0, 0, 0)
            x.Background = Brushes.Transparent
            x.BorderThickness = Thickness(0)
            x.Foreground = brush("#C27A00")
            x.ToolTip = u"Отменить перенос"

            def undo(s, e, nn=list(names), gg=g):
                self._undo_moves(nn, gg)
            x.Click += undo
            sp.Children.Add(x)
        b.Child = sp
        b.ToolTip = tip
        st = {}
        pairs = []
        for n in names:
            for u_ in src.get(n) or []:
                pairs.append(u"{0}\t{1}".format(u_, n))

        def down(s, e):
            if ancestor(e.OriginalSource, Button) is not None:
                return
            st["p"] = e.GetPosition(None)
            b.CaptureMouse()
            e.Handled = True

        def move(s, e):
            p0 = st.get("p")
            if p0 is None or e.LeftButton != MouseButtonState.Pressed:
                return
            p = e.GetPosition(None)
            if abs(p.X - p0.X) < SystemParameters.MinimumHorizontalDragDistance and \
                    abs(p.Y - p0.Y) < SystemParameters.MinimumVerticalDragDistance:
                return
            st["p"] = None
            b.ReleaseMouseCapture()
            self.viz.start(b, "SM_PILL", u"\n".join(pairs), text)

        def up(s, e, k=key):
            if st.get("p") is None:
                return
            st["p"] = None
            b.ReleaseMouseCapture()
            e.Handled = True
            if k is not None:
                if k in self._open_pills:
                    self._open_pills.discard(k)
                else:
                    self._open_pills.add(k)
                self._later(self.draw_groups)
        b.PreviewMouseLeftButtonDown += down
        b.PreviewMouseMove += move
        b.PreviewMouseLeftButtonUp += up
        panel.Children.Add(b)

    def _value_unit(self, g):
        """Значение ADSK_Группирование группы-цели: первое её значение (не «по системе» и не «без системы»);
        нет — имя группы (оно становится её значением)."""
        for u_ in g["systems"]:
            if u_ != self.core.D.NO_SYSTEM and not self.core.is_fallback_unit(u_):
                return u_
        if g["name"] not in g["systems"]:
            g["systems"].append(g["name"])
        return g["name"]

    def _drop_pill(self, data, idx):
        """Таблетка брошена на группу idx (< 0 — в пустое место: новая группа, значение — спросить)."""
        pairs = []
        for ln in (data or u"").split(u"\n"):
            if u"\t" in ln:
                u_, sn = ln.split(u"\t", 1)
                pairs.append((u_, sn))
        if not pairs:
            return
        gs = self.cfg["groups"]
        if idx >= 0:
            to = self._value_unit(gs[idx])
        else:
            sysn = sorted(set(sn for u_, sn in pairs))
            dflt = sysn[0] if len(sysn) == 1 else (self.core.abbr_of(sysn[0], getattr(self.core, "AMAP", {}) or {})
                                                     or sysn[0])
            to = ask_text(self.win, u"Новая группа", u"Значение ADSK_Группирование для новой группы (запишется "
                          u"элементам при сборке):", dflt)
            if not to:
                return
            exist = next((i for i, g in enumerate(gs) if to in g["systems"] or g["name"] == to), -1)
            if exist >= 0:
                to = self._value_unit(gs[exist])
            else:
                gs.append({"name": to, "systems": [to], "split": None, "header": False})
        moves = [m for m in (self.cfg.get("moves") or [])]
        for u_, sn in pairs:
            orig = next((m["from"] for m in moves if m.get("to") == u_ and m.get("sys") == sn), u_)
            moves = [m for m in moves if not (m.get("sys") == sn and m.get("from") == orig)]
            if orig != to:
                moves.append({"sys": sn, "from": orig, "to": to})
        self.cfg["moves"] = moves
        self._apply_moves_view()
        n = len(set(sn for u_, sn in pairs))
        self.status(u"Перенос: {0} {1} → {2}. ADSK_Группирование перепишется при сборке; «↩» на таблетке — "
                    u"отменить.".format(n, u"система" if n == 1 else u"систем", to))

    def _undo_moves(self, names, g):
        self.cfg["moves"] = [m for m in (self.cfg.get("moves") or [])
                             if not (m.get("sys") in names and m.get("to") in g["systems"])]
        self._apply_moves_view()
        self.status(u"Перенос отменён: " + u", ".join(names))

    def _apply_moves_view(self):
        """Переносы — в памяти: единицы групп заново (без чтения модели), группы и левый список."""
        c = self.core
        c.set_moves(self.cfg.get("moves"))
        c.set_units(self.infos, "grouping", self.cfg.get("group_fallback", True) is not False)
        self.systems = c.found_systems(self.infos, getattr(c, "AMAP", None) or {})
        self.sysinfo = dict((s[0], s) for s in self.systems)
        units = set(s[0] for s in self.systems)
        for gg in self.cfg["groups"]:
            gg["systems"] = [u_ for u_ in gg["systems"] if u_ in units]
        self._normalize_groups()

    def draw_groups(self):
        self._chip_elems = []
        self.lbGroups.Items.Clear()
        for i, g in enumerate(self.cfg["groups"]):
            self.lbGroups.Items.Add(self._group_card(i, g))

    def _link_numbers(self):
        """id связки -> номер «Связка N» по порядку появления."""
        out = {}
        for g in self.cfg["groups"]:
            k = g.get("link")
            if k and k not in out:
                out[k] = len(out) + 1
        return out

    def _group_card(self, i, g):
        it = ListBoxItem()
        it.Padding = Thickness(0)
        it.Margin = Thickness(0, 0, 0, 6)
        b = Border()
        b.CornerRadius = CornerRadius(6)
        sel = i in self.sel_groups
        link = g.get("link")
        colors = self.core.D.LINK_COLORS
        b.BorderThickness = Thickness(2) if sel else Thickness(1)
        b.Padding = Thickness(9, 6, 9, 6) if sel else Thickness(10, 7, 10, 7)
        b.BorderBrush = C_BLUE if sel else (brush("#B8C2CE") if link else C_LINE)
        b.Background = brush(colors[(int(link) - 1) % len(colors)]) if link else (C_SEL if sel else C_BG)
        outer = StackPanel()
        grid = Grid()
        for w in (GridLength.Auto, GridLength.Auto, GridLength.Auto, GridLength.Auto, GridLength(1, GridUnitType.Star),
                  GridLength.Auto, GridLength.Auto):
            cd = ColumnDefinition()
            cd.Width = w
            grid.ColumnDefinitions.Add(cd)
        grip = tb(u"⋮⋮", color=brush("#8A939E"), margin=Thickness(0, 0, 8, 0))
        grid.Children.Add(grip)
        cb = CheckBox()
        cb.IsChecked = sel
        cb.VerticalAlignment = VerticalAlignment.Center
        cb.Margin = Thickness(0, 0, 8, 0)
        cb.ToolTip = u"Выбрать (то же — щелчок по карточке)"

        def toggle(s, e, idx=i):
            if s.IsChecked:
                self.sel_groups.add(idx)
            else:
                self.sel_groups.discard(idx)
            self.anchor = idx
            self._later(self.draw_groups)
        cb.Click += toggle
        Grid.SetColumn(cb, 1)
        grid.Children.Add(cb)
        num = Border()
        num.Width = 22
        num.Height = 22
        num.CornerRadius = CornerRadius(11)
        num.Background = C_BLUE_BG if sel else brush("#1F2A37", True)
        num.Margin = Thickness(0, 0, 8, 0)
        nt = tb(str(i + 1), bold=True, size=12, color=Brushes.White)
        nt.HorizontalAlignment = HorizontalAlignment.Center
        num.Child = nt
        Grid.SetColumn(num, 2)
        grid.Children.Add(num)
        name = TextBox()
        name.Text = g["name"]
        name.Width = 110
        name.Padding = Thickness(4, 2, 4, 2)
        name.FontWeight = FontWeights.SemiBold
        name.VerticalAlignment = VerticalAlignment.Center
        name.Margin = Thickness(0, 0, 10, 0)

        def rename(s, e, gg=g):
            v = (s.Text or u"").strip()
            if v and v not in [x["name"] for x in self.cfg["groups"] if x is not gg]:
                gg["name"] = v
            else:
                s.Text = gg["name"]
        name.LostFocus += rename
        Grid.SetColumn(name, 3)
        grid.Children.Add(name)
        chips = WrapPanel()
        chips.VerticalAlignment = VerticalAlignment.Center
        for sname in g["systems"]:
            chips.Children.Add(self._chip(sname, i))
        if self._by_grouping():
            self._sys_pills(chips, g)
        Grid.SetColumn(chips, 4)
        grid.Children.Add(chips)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.VerticalAlignment = VerticalAlignment.Center
        sp.Children.Add(tb(u"Делить по", size=12, color=brush("#4A5361"), margin=Thickness(8, 0, 6, 0)))
        combo = ComboBox()
        combo.Width = 190
        combo.IsEditable = True
        combo.IsTextSearchEnabled = True
        combo.MaxDropDownHeight = 380
        combo.ToolTip = u"Закреплённые варианты вверху, ниже — все параметры категорий (можно начать вводить имя)"
        for n_ in self._split_options():
            combo.Items.Add(n_)
        cur_split = P_SYS if g.get("split") == P_MAIN else g.get("split")
        combo.Text = cur_split or NO_SPLIT

        def set_split(s, e, gg=g, gi=i):
            v = (s.Text or u"").strip()
            if s.SelectedItem is not None and (u"%s" % s.SelectedItem).startswith(u"──"):
                s.Text = gg.get("split") or NO_SPLIT
                return
            val = None if (not v or v == NO_SPLIT) else v
            self._set_for_selected(gi, gg, "split", val)
        combo.SelectionChanged += lambda s, e: self._later(lambda: set_split(s, e))
        combo.LostFocus += set_split
        sp.Children.Add(combo)
        Grid.SetColumn(sp, 5)
        grid.Children.Add(sp)
        hd = CheckBox()
        hd.Content = u"Заголовок"
        hd.IsChecked = bool(g.get("header"))
        hd.VerticalAlignment = VerticalAlignment.Center
        hd.Margin = Thickness(10, 0, 0, 0)

        def set_hdr(s, e, gg=g, gi=i):
            self._set_for_selected(gi, gg, "header", bool(s.IsChecked))
        hd.Click += set_hdr
        Grid.SetColumn(hd, 6)
        grid.Children.Add(hd)
        outer.Children.Add(grid)
        # вторая строка: связка, «Выбрано», строка названия системы (высота — на вкладке «Листы»)
        row2 = WrapPanel()
        row2.Margin = Thickness(30, 4, 0, 0)
        if link:
            lb_ = Border()
            lb_.CornerRadius = CornerRadius(9)
            lb_.Padding = Thickness(8, 0, 8, 1)
            lb_.Margin = Thickness(0, 0, 8, 0)
            lb_.Background = brush("#FFFFFF", True)
            lb_.BorderBrush = brush("#B8C2CE")
            lb_.BorderThickness = Thickness(1)
            lb_.Child = tb(u"Связка {0}".format(self._link_numbers().get(link, link)), size=11,
                           color=brush("#3D4652"))
            lb_.ToolTip = u"Группы связки идут подряд: следующая продолжает текущий лист, пока есть место"
            row2.Children.Add(lb_)
        if sel:
            row2.Children.Add(tb(u"✓ Выбрано", bold=True, size=11, color=C_BLUE, margin=Thickness(0, 0, 10, 0)))
        sr = CheckBox()
        sr.Content = u"Строка названия системы"
        sr.IsChecked = bool(g.get("sys_row"))
        sr.FontSize = 12
        sr.VerticalAlignment = VerticalAlignment.Center
        sr.ToolTip = u"Перед первой спецификацией группы — строка с полным названием системы и примечанием"

        def set_sr(s, e, gg=g, gi=i):
            on = bool(s.IsChecked)
            for t in self._selected_targets(gi, gg):
                t["sys_row"] = on
                if on and not t.get("sys_text"):
                    t["sys_text"] = self.core.group_sys_title(t)
            self._later(self.draw_groups)
        sr.Click += set_sr
        row2.Children.Add(sr)
        if g.get("sys_row"):
            for key, w, hint in (("sys_text", 300, u"Полное название, например «Водопровод хозяйственно-питьевой»"),
                                 ("sys_note", 180, u"Примечание, например «Жилой части» (необязательно)")):
                t = TextBox()
                t.Text = g.get(key) or u""
                t.Width = w
                t.Padding = Thickness(4, 1, 4, 1)
                t.Margin = Thickness(8, 0, 0, 0)
                t.FontSize = 12
                t.ToolTip = hint

                def set_t(s, e, gg=g, kk=key):
                    gg[kk] = (s.Text or u"").strip()
                t.LostFocus += set_t
                row2.Children.Add(t)
        outer.Children.Add(row2)
        b.Child = outer

        def card_up(s, e, idx=i):
            self._gdrag = None
            if is_control_source(e.OriginalSource) or self._chip_name(e.OriginalSource):
                return
            self.click_group(idx)

        def card_down(s, e, idx=i):
            self._gdrag = None
            if is_control_source(e.OriginalSource) or self._chip_name(e.OriginalSource):
                return
            self._gdrag = (idx, e.GetPosition(None))

        def card_move(s, e, idx=i):
            d = self._gdrag
            if d is None or d[0] != idx or e.LeftButton != MouseButtonState.Pressed:
                return
            p = e.GetPosition(None)
            if abs(p.X - d[1].X) < SystemParameters.MinimumHorizontalDragDistance and \
                    abs(p.Y - d[1].Y) < SystemParameters.MinimumVerticalDragDistance:
                return
            self._gdrag = None
            block = sorted(self.sel_groups) if idx in self.sel_groups else [idx]
            gs = self.cfg["groups"]
            lab = (u"Группа «{0}»".format(gs[idx]["name"]) if len(block) == 1 else
                   u"{0} {1}".format(len(block), plural(len(block), u"группа", u"группы", u"групп")))
            self.viz.start(b, "SM_GRP", u",".join(str(x) for x in block), lab)
        b.Tag = u"card:%d" % i
        b.PreviewMouseLeftButtonDown += card_down
        b.PreviewMouseMove += card_move
        b.MouseLeftButtonUp += card_up
        it.Content = b
        return it

    def _split_options(self):
        """«Делить по»: «— нет —», закреплённые (ADSK_Группирование, ADSK_Система_Обозначение, ИмяСистемы,
        Комментарии, Марка), затем все параметры категорий модели."""
        if getattr(self, "_split_cache", None) is None:
            fixed = list(self.core.D.SPLIT_PARAMS)
            rest = set()
            for lst in (getattr(self.core, "SFIELDS", None) or {}).values():
                for f in lst:
                    if f.get("name") and f["name"] not in fixed:
                        rest.add(f["name"])
            self._split_cache = [NO_SPLIT] + fixed + ([u"────────"] if rest else []) + sorted(
                rest, key=lambda x: (not x.startswith(u"ADSK"), x.lower()))
        return self._split_cache

    def _chip_name(self, src):
        """Имя системы, если щелчок по чипу (не по его кнопке ×)."""
        el = src
        while el is not None:
            tag = getattr(el, "Tag", None)
            if isinstance(el, Border) and tag and (u"%s" % tag).startswith(u"chip:"):
                return (u"%s" % tag)[5:]
            if isinstance(el, Button) or isinstance(el, ListBoxItem):
                return None
            p = None
            try:
                p = VisualTreeHelper.GetParent(el)
            except Exception:
                p = None
            if p is None:
                try:
                    p = LogicalTreeHelper.GetParent(el)
                except Exception:
                    p = None
            el = p
        return None

    def _selected_targets(self, gi, gg):
        """Карточка входит в выбранные (их больше одной) — менять все выбранные, иначе только её."""
        gs = self.cfg["groups"]
        if gi in self.sel_groups and len(self.sel_groups) > 1:
            return [gs[k] for k in sorted(self.sel_groups) if 0 <= k < len(gs)]
        return [gg]

    def _set_for_selected(self, gi, gg, key, val):
        """«Делить по», «Заголовок» — одно значение всем выбранным группам; одна отмена Ctrl+Z."""
        targets = self._selected_targets(gi, gg)
        changed = [t for t in targets if t.get(key) != val]
        for t in targets:
            t[key] = val
        if len(targets) > 1 and changed:
            self._later(self.draw_groups)
            self.status(u"Изменено у выбранных групп: {0}".format(len(targets)))

    def _card_index(self, src):
        el = src
        while el is not None:
            tag = getattr(el, "Tag", None)
            if isinstance(el, Border) and tag and (u"%s" % tag).startswith(u"card:"):
                return int((u"%s" % tag)[5:])
            try:
                el = VisualTreeHelper.GetParent(el)
            except Exception:
                el = None
        return -1

    # ---------------- выделение и связки ----------------
    def click_group(self, idx):
        mods = Keyboard.Modifiers
        ctrl = (mods & ModifierKeys.Control) == ModifierKeys.Control
        shift = (mods & ModifierKeys.Shift) == ModifierKeys.Shift
        if shift and self.anchor is not None and 0 <= self.anchor < len(self.cfg["groups"]):
            a, b = sorted((self.anchor, idx))
            rng = set(range(a, b + 1))
            self.sel_groups = (self.sel_groups | rng) if ctrl else rng
        elif ctrl:
            if idx in self.sel_groups:
                self.sel_groups.discard(idx)
            else:
                self.sel_groups.add(idx)
            self.anchor = idx
        else:
            self.sel_groups = set([idx])
            self.anchor = idx
            self.sel_chips = set()
        self._later(self.draw_groups)

    def clear_selection(self):
        if self.sel_groups or self.sel_chips or self.lbSystems.SelectedItems.Count:
            self.sel_groups = set()
            self.sel_chips = set()
            self.lbSystems.SelectedItems.Clear()
            self.draw_groups()
            return True
        return False

    # ---------------- рамка (Ctrl + ЛКМ) ----------------
    def mq_down(self, s, e):
        if (Keyboard.Modifiers & ModifierKeys.Control) != ModifierKeys.Control:
            return
        src = e.OriginalSource
        for typ in (TextBox, ComboBox, Button, CheckBox, RadioButton):
            if ancestor(src, typ) is not None:
                return
        self._mq = {"p0": e.GetPosition(self.page0), "moved": False, "src": src,
                    "list": set(it.Tag for it in self.lbSystems.SelectedItems if it.Tag),
                    "chips": set(self.sel_chips)}
        self.page0.CaptureMouse()
        e.Handled = True

    def _mq_rect(self, p):
        p0 = self._mq["p0"]
        return Rect(min(p0.X, p.X), min(p0.Y, p.Y), abs(p.X - p0.X), abs(p.Y - p0.Y))

    def _bounds(self, el):
        try:
            if not el.IsVisible:
                return None
            return el.TransformToAncestor(self.page0).TransformBounds(Rect(0, 0, el.ActualWidth, el.ActualHeight))
        except Exception:
            return None

    def _mq_apply(self, rect):
        m = self._mq
        hit_list, hit_chips = set(), set()
        for it in self.lbSystems.Items:
            if not getattr(it, "Tag", None):
                continue
            bb = self._bounds(it)
            if bb is not None and bb.IntersectsWith(rect):
                hit_list.add(it.Tag)
        for b, n in self._chip_elems:
            bb = self._bounds(b)
            if bb is not None and bb.IntersectsWith(rect):
                hit_chips.add(n)
        want = m["list"] | hit_list
        for it in self.lbSystems.Items:
            if getattr(it, "Tag", None):
                v = it.Tag in want
                if it.IsSelected != v:
                    it.IsSelected = v
        self.sel_chips = m["chips"] | hit_chips
        for b, n in self._chip_elems:
            on = n in self.sel_chips
            line = self._sys_color(n)[0]
            b.BorderBrush = C_BLUE if on else sys_line(line, 0.55)
            b.BorderThickness = Thickness(2) if on else Thickness(1)

    def mq_move(self, s, e):
        m = self._mq
        if m is None:
            return
        p = e.GetPosition(self.page0)
        if not m["moved"]:
            if abs(p.X - m["p0"].X) < 4 and abs(p.Y - m["p0"].Y) < 4:
                return
            m["moved"] = True
            self.marqRect.Visibility = Visibility.Visible
        rect = self._mq_rect(p)
        Canvas.SetLeft(self.marqRect, rect.X)
        Canvas.SetTop(self.marqRect, rect.Y)
        self.marqRect.Width = rect.Width
        self.marqRect.Height = rect.Height
        self._mq_apply(rect)

    def mq_up(self, s, e):
        m = self._mq
        if m is None:
            return
        self._mq = None
        self.page0.ReleaseMouseCapture()
        self.marqRect.Visibility = Visibility.Collapsed
        e.Handled = True
        if m["moved"]:
            n = len(self.sel_chips) + self.lbSystems.SelectedItems.Count
            self.status(u"Выделено систем: {0} — перетащите в группу или в пустое место".format(n))
            return
        # Ctrl+щелчок без рамки
        src = m["src"]
        cn = self._chip_name(src)
        if cn:
            if cn in self.sel_chips:
                self.sel_chips.discard(cn)
            else:
                self.sel_chips.add(cn)
            self._later(self.draw_groups)
            return
        li = ancestor(src, ListBoxItem)
        if li is not None and getattr(li, "Tag", None) and ancestor(li, ListBox) is self.lbSystems:
            li.IsSelected = not li.IsSelected
            return
        ci = self._card_index(src)
        if ci >= 0:
            self.click_group(ci)

    def mq_cancel(self):
        m = self._mq
        if m is None:
            return False
        self._mq = None
        self.page0.ReleaseMouseCapture()
        self.marqRect.Visibility = Visibility.Collapsed
        for it in self.lbSystems.Items:
            if getattr(it, "Tag", None):
                it.IsSelected = it.Tag in m["list"]
        self.sel_chips = set(m["chips"])
        self.draw_groups()
        return True

    def _cleanup_links(self):
        cnt = {}
        for g in self.cfg["groups"]:
            if g.get("link"):
                cnt[g["link"]] = cnt.get(g["link"], 0) + 1
        for g in self.cfg["groups"]:
            if g.get("link") and cnt.get(g["link"], 0) < 2:
                g.pop("link", None)

    def link_selected(self):
        idx = sorted(i for i in self.sel_groups if i < len(self.cfg["groups"]))
        gs = self.cfg["groups"]
        if len(idx) < 2:
            self.status(u"Для связки выберите две группы или больше (Ctrl+щелчок, Shift+щелчок)")
            return
        links = set(gs[i].get("link") for i in idx)
        if len(links) == 1 and None not in links:
            members = set(k for k, g in enumerate(gs) if g.get("link") in links)
            if members == set(idx):
                return                                   # та же полная связка — без дубликата
        new = max([int(g.get("link") or 0) for g in gs] + [0]) + 1
        for i in idx:
            gs[i]["link"] = new
        self._cleanup_links()
        gap = any(b - a > 1 for a, b in zip(idx, idx[1:]))
        self.status(u"Связка: {0}{1}".format(u", ".join(gs[i]["name"] for i in idx),
                    u" — действует для групп, стоящих подряд; переставьте их рядом" if gap else u""))
        self.draw_groups()

    def unlink_selected(self):
        gs = self.cfg["groups"]
        n = 0
        for i in self.sel_groups:
            if i < len(gs) and gs[i].pop("link", None):
                n += 1
        self._cleanup_links()
        if n:
            self.status(u"Из связок извлечено групп: {0}".format(n))
        self.draw_groups()

    def _chip(self, sname, gi):
        line, text, light = self._sys_color(sname)
        sel = sname in self.sel_chips
        b = Border()
        b.Tag = u"chip:" + sname
        b.CornerRadius = CornerRadius(11)                 # прежняя форма: «таблетка»
        b.Background = sys_bg(line, 0.78 if light else 0.84)
        b.BorderBrush = C_BLUE if sel else sys_line(line, 0.55)
        b.BorderThickness = Thickness(2) if sel else Thickness(1)
        b.Padding = Thickness(7, 0, 1, 0) if sel else Thickness(8, 1, 2, 1)
        b.Margin = Thickness(0, 2, 4, 2)
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Children.Add(tb(sname, size=12, bold=sel, color=sys_text(text)))
        x = Button()
        x.Content = u"×"
        x.Padding = Thickness(4, 0, 4, 0)
        x.Margin = Thickness(2, 0, 0, 0)
        x.Background = Brushes.Transparent
        x.BorderThickness = Thickness(0)
        x.Foreground = sys_text(text)
        x.ToolTip = u"Убрать из группы"

        def remove(s, e, n=sname):
            self.move_systems([n], None)
        x.Click += remove
        sp.Children.Add(x)
        b.Child = sp
        b.ToolTip = u"Щелчок — выбрать, Ctrl+щелчок — добавить. Перетащите в другую группу, в пустое место (новая " \
                    u"группа) или в левый список (убрать из группы)"
        st = {}

        def down(s, e, n=sname):
            if ancestor(e.OriginalSource, Button) is not None:
                return
            if (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control:
                return                                   # Ctrl — щелчок/рамка обрабатывает страница
            st["p"] = e.GetPosition(None)
            b.CaptureMouse()
            e.Handled = True

        def move(s, e, n=sname):
            p0 = st.get("p")
            if p0 is None or e.LeftButton != MouseButtonState.Pressed:
                return
            p = e.GetPosition(None)
            if abs(p.X - p0.X) < SystemParameters.MinimumHorizontalDragDistance and \
                    abs(p.Y - p0.Y) < SystemParameters.MinimumVerticalDragDistance:
                return
            st["p"] = None
            b.ReleaseMouseCapture()
            names = self._ordered(self.sel_chips) if n in self.sel_chips else [n]
            self.viz.start(b, "SM_SYSCHIP", u"\n".join(names))

        def up(s, e, n=sname):
            if st.get("p") is None:
                return
            st["p"] = None
            b.ReleaseMouseCapture()
            self.sel_chips = set([n])
            self.lbSystems.SelectedItems.Clear()
            e.Handled = True
            self._later(self.draw_groups)
        b.PreviewMouseLeftButtonDown += down
        b.PreviewMouseMove += move
        b.PreviewMouseLeftButtonUp += up
        self._chip_elems.append((b, sname))
        return b

    def move_systems(self, names, target):
        """target: индекс группы, -1 — новая группа в конце списка, None — убрать из групп (исключить: в skip_units,
        при следующем запуске сама не вернётся). В группу — снова специфицируется (из skip_units убирается)."""
        skip = [n for n in (self.cfg.get("skip_units") or []) if n not in names]
        if target is None:
            skip += [n for n in names if n not in skip]
        self.cfg["skip_units"] = skip
        src = -1
        for i, g in enumerate(self.cfg["groups"]):
            if src < 0 and any(n in g["systems"] for n in names):
                src = i
        for g in self.cfg["groups"]:
            g["systems"] = [s for s in g["systems"] if s not in names]
        if target == -1:
            ng = {"name": self._new_name(names), "systems": list(names), "split": None, "header": False}
            if len(names) > 1:
                ng["split"], ng["header"] = P_SYS, True
            self.cfg["groups"].append(ng)
        elif target is not None and 0 <= target < len(self.cfg["groups"]):
            self.cfg["groups"][target]["systems"].extend(names)
        self._normalize_groups()

    def _new_name(self, names):
        base = self._merge_name(names) if names else u"Группа"
        used = set(g["name"] for g in self.cfg["groups"])
        n, k = base, 2
        while n in used:
            n = u"{0} ({1})".format(base, k)
            k += 1
        return n

    def _normalize_groups(self):
        order = [s[0] for s in self.systems]
        groups = []
        for g in self.cfg["groups"]:
            g["systems"] = sorted(set(g["systems"]), key=lambda s: order.index(s) if s in order else 999)
            if g["systems"]:
                if len(g["systems"]) == 1 and g.get("split") in (P_MAIN, P_SYS):
                    g["split"], g["header"] = None, False
                groups.append(g)
        self.cfg["groups"] = groups
        self._cleanup_links()
        self.sel_groups = set(i for i in self.sel_groups if i < len(groups))
        self.draw_groups()
        self.draw_systems()

    def on_group_drop(self, s, e):
        idx = self._card_index(e.OriginalSource)
        if e.Data.GetDataPresent("SM_PILL"):
            self.viz.end()
            e.Handled = True
            self._drop_pill(u"%s" % e.Data.GetData("SM_PILL"), idx)
            return
        fmt = "SM_SYS" if e.Data.GetDataPresent("SM_SYS") else ("SM_SYSCHIP" if e.Data.GetDataPresent("SM_SYSCHIP")
                                                                  else None)
        if fmt:
            names = [n for n in (e.Data.GetData(fmt) or u"").split(u"\n") if n]
            if idx >= 0 and all(n in self.cfg["groups"][idx]["systems"] for n in names):
                e.Handled = True
                return                                   # брошено в ту же группу
            self.sel_chips = set()
            self.move_systems(names, idx if idx >= 0 else -1)   # в пустое место — новая группа в конце
            if idx < 0:
                self.status(u"Новая группа «{0}» — в конце списка".format(self.cfg["groups"][-1]["name"]))
        elif e.Data.GetDataPresent("SM_GRP"):
            block = [int(x) for x in (u"%s" % e.Data.GetData("SM_GRP")).split(u",") if x.strip()]
            self.move_group_block(block, DragViz.drop_index(self.lbGroups, e))
        self.viz.end()
        e.Handled = True

    def move_group_block(self, block, pos):
        """Перенести группы block (индексы) на место pos (0..n — по линии вставки; < 0 — в конец)."""
        gs = self.cfg["groups"]
        block = [i for i in sorted(set(block)) if 0 <= i < len(gs)]
        if not block:
            return
        if pos < 0 or pos > len(gs):
            pos = len(gs)
        moving = [gs[i] for i in block]
        rest = [g for k, g in enumerate(gs) if k not in block]
        pos -= sum(1 for i in block if i < pos)
        if [id(g) for g in rest[:pos] + moving + rest[pos:]] == [id(g) for g in gs]:
            return
        self.cfg["groups"] = rest[:pos] + moving + rest[pos:]
        self.sel_groups = set(range(pos, pos + len(moving)))
        self.anchor = pos
        self._normalize_groups()

    def on_systems_drop(self, s, e):
        """Чип, брошенный в левый список, — убрать из группы."""
        if e.Data.GetDataPresent("SM_SYSCHIP"):
            names = [n for n in (e.Data.GetData("SM_SYSCHIP") or u"").split(u"\n") if n]
            self.sel_chips = set()
            self.move_systems(names, None)
            self.status(u"Исключено (не специфицируется): " + u", ".join(names))
        self.viz.end()
        e.Handled = True

    def on_to_new(self, s, e):
        names = [it.Tag for it in self.lbSystems.SelectedItems if it.Tag]
        if names:
            self.move_systems(names, -1)

    def on_to_sel(self, s, e):
        names = [it.Tag for it in self.lbSystems.SelectedItems if it.Tag]
        if names and self.sel_groups:
            self.move_systems(names, min(self.sel_groups))

    def on_skip(self, s, e):
        """«Исключить»: выделенное слева (и выделенные чипы) — не специфицировать."""
        names = [it.Tag for it in self.lbSystems.SelectedItems if it.Tag]
        names += [n for n in self._ordered(self.sel_chips) if n not in names]
        if not names:
            self.status(u"Выделите слева, что исключить из спецификаций")
            return
        self.sel_chips = set()
        self.move_systems(names, None)
        self.status(u"Исключено (не специфицируется): " + u", ".join(names) +
                    u". Вернуть — «В новую группу» или перетащить в группу")

    def on_merge(self, s, e):
        idx = sorted(self.sel_groups)
        if len(idx) < 2:
            return
        gs = self.cfg["groups"]
        first = gs[idx[0]]
        for i in idx[1:]:
            first["systems"].extend(gs[i]["systems"])
            gs[i]["systems"] = []
        first["split"], first["header"] = P_SYS, True
        first["name"] = self._merge_name(first["systems"])
        self.sel_groups = set([idx[0]])
        self._normalize_groups()

    def _merge_name(self, systems):
        order = [s[0] for s in self.systems]
        systems = sorted(systems, key=lambda x: order.index(x) if x in order else 999)
        parts = [s.replace(u" ", u".") for s in systems]
        name = parts[0] + u"–" + parts[-1] if len(parts) > 1 else parts[0]
        used = set(g["name"] for g in self.cfg["groups"] if g["systems"] != systems)
        n, k = name, 2
        while n in used:
            n = u"{0} ({1})".format(name, k)
            k += 1
        return n

    def on_split(self, s, e):
        gs = self.cfg["groups"]
        new = []
        for i, g in enumerate(gs):
            if i in self.sel_groups and len(g["systems"]) > 1:
                for sname in g["systems"]:
                    new.append({"name": sname.replace(u" ", u"."), "systems": [sname], "split": None, "header": False})
            else:
                new.append(g)
        self.cfg["groups"] = new
        self.sel_groups = set()
        self._normalize_groups()

    def on_auto(self, s, e):
        self.cfg["groups"] = self.core.default_groups(self.systems, self.cfg.get("skip_units"))
        self.sel_groups = set()
        self._normalize_groups()

    def move_groups(self, d):
        """Выбранные группы (одна или несколько) — на одну позицию выше / ниже."""
        gs = self.cfg["groups"]
        idx = sorted(i for i in self.sel_groups if i < len(gs))
        if not idx:
            return
        if (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(gs) - 1):
            return
        for i in (idx if d < 0 else reversed(idx)):
            gs[i], gs[i + d] = gs[i + d], gs[i]
        self.sel_groups = set(i + d for i in idx)
        if self.anchor is not None:
            self.anchor += d
        self.draw_groups()
        self.draw_systems()

    # ---------------- 2. что специфицируем ----------------
    def _init_page1(self):
        self.btnFillQty.Click += lambda s, e: self.on_fill_qty()
        self.btnExpand.Click += lambda s, e: self._expand_all(True)
        self.btnCollapse.Click += lambda s, e: self._expand_all(False)
        self.tbSearch.TextChanged += self.on_search

    def _groups_by_system(self):
        m = {}
        for g in self.cfg["groups"]:
            for s in g["systems"]:
                m.setdefault(s, g["name"])
        return m

    def build_tree(self):
        hidden = self.cfg.get("hidden") or {}
        hc = set(hidden.get("cats") or [])
        hf = set(tuple(x) for x in (hidden.get("fams") or []))
        hn = set(tuple(x) for x in (hidden.get("names") or []))
        gmap = self._groups_by_system()
        data = {}
        for it in self.infos:
            d = data.setdefault(it.key, {})
            f = d.setdefault(it.fam, {})
            n = f.setdefault(it.name, [0, set(), [0, 0, 0]])
            n[0] += 1
            zq = getattr(it, "zq", None)
            if zq in ZQ_IDX:
                n[2][ZQ_IDX[zq]] += 1
            for s in self.core.units_of(it):
                if s in gmap:
                    n[1].add(gmap[s])
                    break
        self.tvCats.Items.Clear()
        self.tree_nodes = []
        for key, bname, title, order in sorted(self.core.D.CATS, key=lambda c: c[3]):
            if key not in data:
                continue
            fams = data[key]
            total = sum(v[0] for f in fams.values() for v in f.values())
            zsum = lambda vs: [sum(v[2][i] for v in vs) for i in range(3)]
            cz = zsum([v for f in fams.values() for v in f.values()])
            cnode = self._node(None, u"cat", key, None, None, u"{0}".format(title), total, None, key not in hc, bold=True,
                               zero=cz)
            for fam in sorted(fams.keys(), key=lambda x: x.lower()):
                names = fams[fam]
                ftotal = sum(v[0] for v in names.values())
                fgroups = set()
                for v in names.values():
                    fgroups |= v[1]
                fnode = self._node(cnode, u"fam", key, fam, None, fam or u"(без семейства)", ftotal, fgroups,
                                   (key, fam) not in hf and key not in hc, zero=zsum(names.values()))
                for nm in sorted(names.keys(), key=lambda x: x.lower()):
                    v = names[nm]
                    self._node(fnode, u"name", key, fam, nm, nm or u"(пустое наименование)", v[0], v[1],
                               (key, fam, nm) not in hn and (key, fam) not in hf and key not in hc, zero=v[2])
                self._refresh_state(fnode)
            self._refresh_state(cnode)
            self.tvCats.Items.Add(cnode["item"])
        self._tree_info()

    def _node(self, parent, kind, key, fam, name, text, count, groups, checked, bold=False, zero=None):
        item = TreeViewItem()
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        zc = list(zero or [0, 0, 0])
        cb = CheckBox()
        cb.IsChecked = bool(checked)
        cb.VerticalAlignment = VerticalAlignment.Center
        cb.Margin = Thickness(0, 1, 6, 1)
        sp.Children.Add(cb)
        sp.Children.Add(tb(text, bold=bold))
        sp.Children.Add(tb(u"   {0}".format(count), size=12, color=C_MUTED))
        if groups:
            gl = sorted(groups)
            sp.Children.Add(tb(u"   · " + u", ".join(gl[:4]) + (u"…" if len(gl) > 4 else u""), size=12, color=C_MUTED))
        if sum(zc):
            zb = Border()
            zb.Background = C_ZERO
            zb.BorderBrush = brush("#E9C46A")
            zb.BorderThickness = Thickness(1)
            zb.CornerRadius = CornerRadius(4)
            zb.Padding = Thickness(6, 0, 6, 1)
            zb.Margin = Thickness(10, 1, 0, 1)
            parts = [u"{0}: {1}".format(t, zc[i]) for i, t in enumerate(ZQ_LABELS) if zc[i]]
            zb.Child = tb(u"ADSK_Количество — " + u", ".join(parts), size=11, color=brush("#5C3900"))
            zb.ToolTip = (u"У специфицируемых изделий количество должно быть заполнено (экземпляр, иначе тип). Сборка "
                          u"его не дописывает. «Заполнить количество…» — 1 шт. там, где пусто или 0; где параметра "
                          u"нет — записать некуда.")
            sp.Children.Add(zb)
        item.Header = sp
        node = {"item": item, "cb": cb, "kind": kind, "key": key, "fam": fam, "name": name, "children": [],
                "parent": parent, "text": text}
        cb.Click += lambda s, e, nd=node: self._on_check(nd)
        if parent is not None:
            parent["children"].append(node)
            parent["item"].Items.Add(item)
        self.tree_nodes.append(node)
        return node

    def _set_sub(self, node, v):
        node["cb"].IsChecked = v
        for c in node["children"]:
            self._set_sub(c, v)

    def _refresh_state(self, node):
        if not node["children"]:
            return node["cb"].IsChecked
        vals = set()
        for c in node["children"]:
            vals.add(self._refresh_state(c) if c["children"] else c["cb"].IsChecked)
        node["cb"].IsChecked = list(vals)[0] if len(vals) == 1 else None
        return node["cb"].IsChecked

    def _on_check(self, node):
        v = node["cb"].IsChecked
        v = True if v is None else bool(v)
        self._set_sub(node, v)
        p = node["parent"]
        while p is not None:
            vals = set(c["cb"].IsChecked for c in p["children"])
            p["cb"].IsChecked = list(vals)[0] if len(vals) == 1 else None
            p = p["parent"]
        self._tree_info()

    def collect_hidden(self):
        if not self.tree_nodes:
            return
        cats, fams, names = [], [], []
        for n in self.tree_nodes:
            st = n["cb"].IsChecked
            if n["kind"] == u"cat" and st is False:
                cats.append(n["key"])
        for n in self.tree_nodes:
            st = n["cb"].IsChecked
            if n["kind"] == u"fam" and st is False and n["key"] not in cats:
                fams.append([n["key"], n["fam"]])
        fset = set((a, b) for a, b in fams)
        for n in self.tree_nodes:
            if n["kind"] == u"name" and n["cb"].IsChecked is False and n["key"] not in cats and (n["key"], n["fam"]) not in fset:
                names.append([n["key"], n["fam"], n["name"]])
        self.cfg["hidden"] = {"cats": cats, "fams": fams, "names": names}

    def _tree_info(self):
        nc = sum(1 for n in self.tree_nodes if n["kind"] == u"cat" and n["cb"].IsChecked is False)
        nf = sum(1 for n in self.tree_nodes if n["kind"] == u"fam" and n["cb"].IsChecked is False)
        nn = sum(1 for n in self.tree_nodes if n["kind"] == u"name" and n["cb"].IsChecked is False)
        txt = (u"Снято: категорий {0}, семейств {1}, наименований {2}. Снятое не попадёт в спецификации "
               u"(ADSK_Система_Обозначение пусто, ADSK_Позиция_Сортировка = −1).").format(nc, nf, nn)
        zc = [sum(1 for i in self.infos if getattr(i, "zq", None) == k) for k in ("none", "empty", "zero")]
        if sum(zc):
            txt += (u"\nADSK_Количество не заполнено (жёлтым): {0} — сборка количество не дописывает; кнопка "
                    u"«Заполнить количество…» пишет 1 шт. где пусто или 0.").format(
                u", ".join(u"{0} — {1} эл.".format(t, zc[i]) for i, t in enumerate(ZQ_LABELS) if zc[i]))
        self.treeInfo.Text = txt
        self.btnFillQty.IsEnabled = bool(zc[1] or zc[2])

    def _scope_infos(self):
        """Охват кнопки «Заполнить количество»: выделенный узел дерева (категория / семейство / наименование);
        без выделения — все."""
        sel = self.tvCats.SelectedItem
        node = next((n for n in self.tree_nodes if n["item"] is sel), None) if sel is not None else None
        if node is None:
            return self.infos, u"все жёлтые"
        k, f, nm = node["key"], node["fam"], node["name"]
        lst = [i for i in self.infos if i.key == k and (f is None or i.fam == f) and (nm is None or i.name == nm)]
        return lst, u"выделено: «{0}»".format(node["text"])

    def on_fill_qty(self):
        """Кнопка «Заполнить количество»: список (что и куда), затем запись одним шагом Ctrl+Z."""
        its, scope = self._scope_infos()
        try:
            plan = self.core.qty_fill_plan(its)
        except Exception as ex:
            MessageBox.Show(self.win, u"Не удалось собрать список:\n{0}".format(ex), u"Заполнить количество",
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        if not plan["write"] and not plan["skip"]:
            self.status(u"Пустых и нулевых ADSK_Количество нет ({0})".format(scope))
            return
        title = dict((k, t) for k, b, t, o in self.core.D.CATS)
        w = Window()
        T.dress(w)
        w.Title = u"Заполнить количество — {0}".format(scope)
        w.Width = 760
        w.Height = 560
        w.WindowStartupLocation = WindowStartupLocation.CenterOwner
        w.Owner = self.win
        w.FontFamily = self.win.FontFamily
        w.FontSize = 13
        dp = DockPanel()
        dp.Margin = Thickness(14, 12, 14, 12)
        head = tb(u"Изделиям с пустым или нулевым ADSK_Количество (в экземпляре) будет записано 1 шт. Заполненные "
                  u"вручную не меняются. Отменить — Ctrl+Z в Revit (одним шагом).", wrap=True,
                  color=brush("#4A5361"), margin=Thickness(0, 0, 0, 8))
        DockPanel.SetDock(head, Dock.Top)
        dp.Children.Add(head)
        bt = StackPanel()
        bt.Orientation = Orientation.Horizontal
        bt.HorizontalAlignment = HorizontalAlignment.Right
        bt.Margin = Thickness(0, 10, 0, 0)
        DockPanel.SetDock(bt, Dock.Bottom)
        dp.Children.Add(bt)
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        lst = StackPanel()
        sv.Content = lst
        dp.Children.Add(sv)
        by = {}
        for it in plan["write"]:
            by.setdefault(it.key, []).append(it)
        lst.Children.Add(tb(u"Будет записано 1 шт.: {0} эл.".format(len(plan["write"])), bold=True,
                            color=brush("#174A87"), margin=Thickness(0, 0, 0, 4)))
        for k in sorted(by, key=lambda x: title.get(x, x)):
            names = {}
            for it in by[k]:
                names[it.name or it.fam] = names.get(it.name or it.fam, 0) + 1
            lst.Children.Add(tb(u"{0} — {1} эл.".format(title.get(k, k), len(by[k])), bold=True, size=12,
                                margin=Thickness(8, 4, 0, 0)))
            for nm in sorted(names)[:30]:
                lst.Children.Add(tb(u"«{0}» — {1}".format(nm, names[nm]), size=12, wrap=True,
                                    margin=Thickness(22, 0, 0, 0)))
        if plan["skip"]:
            why = {}
            for it, r in plan["skip"]:
                why.setdefault(r, {}).setdefault(title.get(it.key, it.key), 0)
                why[r][title.get(it.key, it.key)] += 1
            lst.Children.Add(tb(u"Пропущено: {0} эл.".format(len(plan["skip"])), bold=True, color=brush("#8A5A00"),
                                margin=Thickness(0, 10, 0, 4)))
            for r in sorted(why):
                lst.Children.Add(tb(u"{0}: {1}".format(r, u", ".join(u"{0} — {1}".format(c, n)
                                                                     for c, n in sorted(why[r].items()))),
                                    size=12, wrap=True, margin=Thickness(8, 0, 0, 2)))
        res = {}

        def ok(s, e):
            res["ok"] = True
            w.DialogResult = True
        b = Button()
        b.Content = u"Записать"
        b.Padding = Thickness(14, 4, 14, 4)
        b.IsDefault = True
        b.IsEnabled = bool(plan["write"])
        b.Click += ok
        bt.Children.Add(b)
        c = Button()
        c.Content = u"Отмена"
        c.Padding = Thickness(14, 4, 14, 4)
        c.Margin = Thickness(8, 0, 0, 0)
        c.IsCancel = True
        bt.Children.Add(c)
        w.Content = dp
        w.ShowDialog()
        if not res.get("ok"):
            return
        try:
            n, bad = self.core.qty_fill_apply(self.core.doc, plan["write"])
        except Exception as ex:
            MessageBox.Show(self.win, u"Количество не записано, модель не изменена:\n{0}".format(ex),
                            u"Заполнить количество", MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        self.collect_hidden()
        self.build_tree()
        self.status(u"ADSK_Количество = 1 записано: {0} эл.{1} Отменить — Ctrl+Z в Revit.".format(
            n, u"; не записано: {0}".format(len(bad)) if bad else u""))

    def _expand_all(self, v):
        for n in self.tree_nodes:
            if n["children"]:
                n["item"].IsExpanded = v

    def on_search(self, s, e):
        q = (self.tbSearch.Text or u"").strip().lower()
        for n in self.tree_nodes:
            if n["kind"] == u"cat":
                any_vis = False
                for f in n["children"]:
                    fm = (not q) or q in (f["fam"] or u"").lower()
                    vis_names = 0
                    for c in f["children"]:
                        cm = fm or q in (c["name"] or u"").lower()
                        c["item"].Visibility = Visibility.Visible if cm else Visibility.Collapsed
                        vis_names += 1 if cm else 0
                    fv = fm or vis_names > 0
                    f["item"].Visibility = Visibility.Visible if fv else Visibility.Collapsed
                    f["item"].IsExpanded = bool(q) and vis_names > 0 and not fm
                    any_vis = any_vis or fv
                n["item"].Visibility = Visibility.Visible if any_vis else Visibility.Collapsed
                n["item"].IsExpanded = bool(q) and any_vis

    # ---------------- 3. материалы и типы ----------------
    def _init_page2(self):
        self.cbOrderOn.IsChecked = bool(self.cfg.get("order_on", True))
        self.cbOrderOn.Click += lambda s, e: self._set_order_on(bool(self.cbOrderOn.IsChecked))
        self._build_order_tabs()
        self.tabOrder.SelectionChanged += self.on_order_tab
        self.rbTypeDiam.Click += lambda s, e: self._set_inner("type")
        self.rbDiamType.Click += lambda s, e: self._set_inner("diam")
        if self.tabOrder.Items.Count:
            self.tabOrder.SelectedIndex = 0
        self._order_info()

    def _cat_title(self, key):
        return next((t for k, b, t, o in self.core.D.CATS if k == key), key)

    def _order_info(self):
        on = bool(self.cfg.get("order_on", True))
        if on:
            off = [self._cat_title(k) for k in self.cfg.get("order_off") or []]
            self.tOrderInfo.Text = (u"Сортировка по спискам ниже. " + (u"Выключено для: " + u", ".join(off) + u" — там «по имени»."
                                    if off else u"Категорию можно выключить галкой на её вкладке."))
        else:
            on_ = [self._cat_title(k) for k in self.cfg.get("order_cats_on") or []]
            self.tOrderInfo.Text = (u"Шаг выключен — «по имени»: ADSK_Наименование → диаметр числом → марка → код. "
                                    u"Списки сохранены. Насосы «номер по системе» работают. " +
                                    (u"Включено для: " + u", ".join(on_) + u"." if on_ else u""))

    def _set_order_on(self, v):
        self.cfg["order_on"] = v
        self._order_info()
        self.refresh_order_tabs()

    def _cat_on(self, key):
        return self.core.order_on(self.cfg, key)

    def _set_cat_on(self, key, v):
        if self.cfg.get("order_on", True):
            off = [k for k in self.cfg.get("order_off") or [] if k != key]
            if not v:
                off.append(key)
            self.cfg["order_off"] = off
        else:
            on = [k for k in self.cfg.get("order_cats_on") or [] if k != key]
            if v:
                on.append(key)
            self.cfg["order_cats_on"] = on
        self._order_info()
        self.refresh_order_tabs()

    def _build_order_tabs(self):
        keep = self._cur_order_key() if self.tabOrder.Items.Count else None
        self.tabOrder.Items.Clear()
        self.order_tabs = {}
        sel = 0
        present = set(i.key for i in self.infos)
        for key in self.core.D.ORDER_TAB_KEYS:
            if key not in present:
                continue
            ti = TabItem()
            ti.Header = self._cat_title(key)
            ti.Tag = key
            ti.Content = self._order_tab(key)
            if key == keep:
                sel = self.tabOrder.Items.Count
            self.tabOrder.Items.Add(ti)
        if self.tabOrder.Items.Count:
            self.tabOrder.SelectedIndex = sel
        self.refresh_order_tabs()

    def _cur_order_key(self):
        ti = self.tabOrder.SelectedItem
        return ti.Tag if ti is not None else None

    def on_order_tab(self, s, e):
        if e.OriginalSource is not self.tabOrder:
            return
        k = self._cur_order_key()
        if k:
            inner = (self.cfg["order"].get(k) or {}).get("inner", "type")
            self.rbTypeDiam.IsChecked = inner != "diam"
            self.rbDiamType.IsChecked = inner == "diam"

    def _set_inner(self, v):
        k = self._cur_order_key()
        if k:
            self.cfg["order"].setdefault(k, {})["inner"] = v

    def _disc_code(self):
        d = disc_by_key(self.core.D, self.cfg.get("discipline"))
        return (d or {}).get("code") or u"ВК"

    def _order_set_disc(self, key):
        """Кнопка «Набор раздела»: материалы и типы категории — готовым списком раздела (с подтверждением).
        «Внутри материала» (тип → диаметр / диаметр → тип) сохраняется. Ctrl+Z окна не нужен: без сборки
        настройки проекта не меняются (закрыть окно — всё как было)."""
        import copy
        title = self._cat_title(key)
        r = MessageBox.Show(self.win, u"Заменить материалы и типы категории «{0}» готовым списком раздела {1}?\n\n"
                                      u"Перетащенные в эту категорию семейства и типы снимутся. Настройки проекта "
                                      u"запомнятся только при сборке.".format(title, self._disc_code()),
                            u"Набор раздела", MessageBoxButton.YesNo, MessageBoxImage.Question)
        if r != MessageBoxResult.Yes:
            return
        new = self.core.order_set_for(self.cfg, key)
        old = self.cfg["order"].get(key) or {}
        if old.get("inner"):
            new["inner"] = old["inner"]
        self.cfg["order"][key] = new
        self.cfg.setdefault("_order_auto", {})[key] = copy.deepcopy(new)
        self.refresh_order_tabs()
        self.status(u"«{0}»: подставлен набор раздела {1}".format(title, self._disc_code()))

    def _order_tab(self, key):
        D = self.core.D
        self.cfg["order"].setdefault(key, {"inner": "type", "materials": [], "types": []})
        outer = DockPanel()
        st = {"key": key}
        # верх: шаг для категории
        top = Border()
        top.CornerRadius = CornerRadius(6)
        top.Padding = Thickness(10, 4, 10, 4)
        top.Margin = Thickness(4, 8, 4, 0)
        tw = WrapPanel()
        cb = CheckBox()
        cb.Content = u"распределять в этой категории"
        cb.VerticalAlignment = VerticalAlignment.Center
        cb.Click += lambda s, e, k=key: self._set_cat_on(k, bool(s.IsChecked))
        tw.Children.Add(cb)
        note = tb(u"", size=12, color=brush("#5C3900"), margin=Thickness(12, 0, 0, 0))
        tw.Children.Add(note)
        dset = self.core.order_set_for(self.cfg, key)
        if dset.get("materials") or dset.get("types"):
            # 0.10.0: готовые списки раздела (ВК / ОВ) — только по кнопке, сохранённое в проекте само не меняется
            bt = Button()
            bt.Content = u"Набор раздела {0}".format(self._disc_code())
            bt.Padding = Thickness(8, 1, 8, 1)
            bt.Margin = Thickness(14, 0, 0, 0)
            bt.ToolTip = (u"Заменить материалы и типы этой категории готовым списком раздела проекта. "
                          u"Перетащенные сюда семейства и типы снимутся.")
            bt.Click += lambda s, e, k=key: self._order_set_disc(k)
            tw.Children.Add(bt)
        top.Child = tw
        DockPanel.SetDock(top, Dock.Top)
        outer.Children.Add(top)
        st["cb_on"], st["on_note"], st["on_bd"] = cb, note, top
        grid = Grid()
        grid.Margin = Thickness(4, 8, 4, 4)
        show_mat = key in D.ORDER_MAT_KEYS
        show_typ = key in D.ORDER_TYPE_KEYS
        for w in ((1.0 if show_mat else 0), 0.0, (1.4 if show_typ else 0), 0.0, 0.9):
            cd = ColumnDefinition()
            cd.Width = GridLength(w, GridUnitType.Star) if w else GridLength(12 if show_mat or show_typ else 0)
            grid.ColumnDefinitions.Add(cd)
        isk = key in D.INS_KEYS
        if show_mat:
            title = u"1. Тип изоляции" if isk else u"1. Материал"
            p, lb = self._order_list(st, "materials", title, edit_keys=not isk, fams=not isk)
            Grid.SetColumn(p, 0)
            grid.Children.Add(p)
            st["lbm"] = lb
        if show_typ:
            p, lb = self._order_list(st, "types", u"2. Тип изделия", edit_keys=True, fams=True)
            Grid.SetColumn(p, 2)
            grid.Children.Add(p)
            st["lbt"] = lb
        dp = DockPanel()
        if key == "equip":
            dp.Children.Add(self._dock(self._sysnum_panel(st), Dock.Top))
        dp.Children.Add(self._dock(tb(u"Не распределено", bold=True, margin=Thickness(0, 0, 0, 4)), Dock.Top))
        hint = tb((u"Перетащите тип изоляции в строку слева (несколько — Ctrl+щелчок или Ctrl+рамка). Ошиблись — "
                   u"перетащите плашку обратно или нажмите ×. Нераспределённые встают в конец.") if isk else
                  (u"Перетащите семейство (или его тип — ▸ раскрывает типы) на материал и на тип слева; несколько — "
                   u"Ctrl+щелчок или Ctrl+рамка. Тип главнее семейства. Ошиблись — перетащите плашку в другую строку, "
                   u"сюда обратно или нажмите ×. Нераспределённые встают в конец."),
                  size=11, color=brush("#6B4200"), wrap=True, margin=Thickness(0, 4, 0, 0))
        dp.Children.Add(self._dock(hint, Dock.Bottom))
        bts = WrapPanel()
        bts.Margin = Thickness(0, 6, 0, 0)
        for txt, fld, on in ((u"→ в выбранный материал", "materials", show_mat),
                             (u"→ в выбранный тип", "types", show_typ)):
            if not on:
                continue
            bt = Button()
            bt.Content = txt
            bt.Padding = Thickness(8, 3, 8, 3)
            bt.Margin = Thickness(0, 0, 6, 0)
            bt.Click += lambda s, e, stt=st, f=fld: self._assign_selected(stt, f)
            bts.Children.Add(bt)
        dp.Children.Add(self._dock(bts, Dock.Bottom))
        lbu = ListBox()
        lbu.BorderBrush = brush("#E3D3B5")
        lbu.Background = brush("#FFFAF0")
        lbu.SelectionMode = SelectionMode.Extended
        lbu.HorizontalContentAlignment = HorizontalAlignment.Stretch
        ScrollViewer.SetHorizontalScrollBarVisibility(lbu, 0)

        def drop_back(s, e, k=key):
            if e.Data.GetDataPresent("SM_CHIP"):
                for ck, cf, tag in self._chips_of(e.Data.GetData("SM_CHIP")):
                    if ck == k:
                        self._unassign(k, tag, cf, refresh=False)
                self.sel_fchips = set()
                self.refresh_order_tabs()
            self.viz.end()
            e.Handled = True
        lbu.Drop += drop_back
        self.viz.target(lbu, ["SM_CHIP"])
        dp.Children.Add(lbu)
        st["lbu"] = lbu

        def payload(i, l=lbu):
            if not (0 <= i < l.Items.Count) or not l.Items[i].Tag:
                return None
            tags = [x.Tag for x in l.SelectedItems if x.Tag]
            if l.Items[i].Tag not in tags:
                tags = [l.Items[i].Tag]
            return ("SM_FAM", u"\n".join(tags), self._tag_text(tags[0]) if len(tags) == 1 else None)
        Dragger(lbu, payload, self.viz)
        Grid.SetColumn(dp, 4)
        grid.Children.Add(dp)
        outer.Children.Add(grid)
        self.viz.marquee(grid, lambda r, state, stt=st: self._order_mq(stt, r, state),
                         lambda stt=st: self._order_mq_state(stt))
        self.order_tabs[key] = st
        return outer

    # рамка на вкладке 3: строки «Не распределено» и плашки
    def _order_mq_state(self, st):
        return {"sel": set(x.Tag for x in st["lbu"].SelectedItems if x.Tag), "chips": set(self.sel_fchips)}

    def _order_mq(self, st, rect, state):
        hit = set()
        for it in st["lbu"].Items:
            b = self.viz.bounds(it)
            if b is not None and b.IntersectsWith(rect) and it.Tag:
                hit.add(it.Tag)
        want = state["sel"] | hit
        for it in st["lbu"].Items:
            if it.Tag:
                v = it.Tag in want
                if it.IsSelected != v:
                    it.IsSelected = v
        chips = set()
        for b, key in st.get("chip_elems") or []:
            r = self.viz.bounds(b)
            if r is not None and r.IntersectsWith(rect):
                chips.add(key)
        self.sel_fchips = state["chips"] | chips
        self._paint_fchips(st)

    def _fchip_restore(self, state):
        if not state:
            return
        self.sel_fchips = set(state.get("chips") or [])
        k = self._cur_order_key()
        st = self.order_tabs.get(k)
        if st is not None:
            for it in st["lbu"].Items:
                if it.Tag:
                    it.IsSelected = it.Tag in state.get("sel", set())
            self._paint_fchips(st)

    def _paint_fchips(self, st):
        for b, key in st.get("chip_elems") or []:
            on = key in self.sel_fchips
            b.BorderBrush = C_BLUE if on else brush("#B9CDE8")
            b.BorderThickness = Thickness(2) if on else Thickness(1)

    def _clear_order_selection(self):
        k = self._cur_order_key()
        st = self.order_tabs.get(k)
        if st is None:
            return False
        had = bool(self.sel_fchips) or st["lbu"].SelectedItems.Count > 0
        self.sel_fchips = set()
        st["lbu"].SelectedItems.Clear()
        self._paint_fchips(st)
        return had

    def _tag_text(self, tag):
        p = (tag or u"").split(u"\t")
        if p[0] == "T" and len(p) >= 3:
            return u"{0}: {1}".format(p[1], p[2])
        return p[-1] if p else u""

    def _chips_of(self, data):
        out = []
        for line in (u"%s" % (data or u"")).split(u"\n"):
            parts = line.split(u"\t", 2)
            if len(parts) == 3:
                out.append((parts[0], parts[1], parts[2]))
        return out

    def _sysnum_panel(self, st):
        b = Border()
        b.BorderBrush = brush("#B9CDE8")
        b.Background = brush("#F3F8FE")
        b.BorderThickness = Thickness(1)
        b.CornerRadius = CornerRadius(6)
        b.Padding = Thickness(10, 8, 10, 8)
        b.Margin = Thickness(0, 0, 0, 10)
        sp = StackPanel()
        sp.Children.Add(tb(u"Номер по системе — как будет пронумеровано", bold=True))
        row = WrapPanel()
        row.Margin = Thickness(0, 4, 0, 4)
        row.Children.Add(tb(u"Формат ", size=12, color=C_MUTED, margin=Thickness(0, 3, 4, 0)))
        fm = TextBox()
        fm.Width = 110
        fm.Padding = Thickness(3, 1, 3, 1)
        fm.Text = (self.cfg.get("pos") or {}).get("sysnum_fmt") or self.core.D.SYSNUM_FMT
        row.Children.Add(fm)
        row.Children.Add(tb(u"  {сист} — сокращение системы, {n} — номер", size=11, color=C_MUTED, margin=Thickness(0, 3, 0, 0)))
        sp.Children.Add(row)
        sp.Children.Add(tb(u"Свой формат и начальный номер для типа системы (пусто — общий формат, с 1). "
                           u"Одинаковые насосы на разных системах группы — одна позиция.", size=11,
                           color=C_MUTED, wrap=True, margin=Thickness(0, 4, 0, 2)))
        per = StackPanel()
        sp.Children.Add(per)
        st["sysper"] = per
        out = StackPanel()
        out.Margin = Thickness(0, 6, 0, 0)
        sp.Children.Add(out)
        b.Child = sp

        def changed(s, e):
            self.cfg.setdefault("pos", {})["sysnum_fmt"] = (fm.Text or u"").strip() or self.core.D.SYSNUM_FMT
            self._draw_sysnum(st)
        fm.TextChanged += changed
        st["sysprev"] = out
        self._draw_sysper(st)
        return b

    def _draw_sysper(self, st):
        """Строки «тип системы → формат, с номера» для насосов."""
        per = st.get("sysper")
        if per is None:
            return
        per.Children.Clear()
        try:
            abbrs = self.core.sysnum_systems(self.infos, self.cfg)
        except Exception:
            abbrs = []
        by = self.cfg.setdefault("pos", {}).setdefault("sysnum_by", {})
        if not abbrs:
            per.Children.Add(tb(u"(насосов по системам пока нет)", size=11, color=C_MUTED))
            return
        for ab in abbrs:
            o = by.get(ab) or {}
            row = WrapPanel()
            row.Margin = Thickness(0, 1, 0, 1)
            lab = tb(ab, bold=True, color=brush("#174A87"))
            lab.Width = 60
            row.Children.Add(lab)
            row.Children.Add(tb(u"формат ", size=11, color=C_MUTED))
            f = TextBox()
            f.Width = 110
            f.Padding = Thickness(3, 1, 3, 1)
            f.Text = o.get("fmt") or u""
            row.Children.Add(f)
            row.Children.Add(tb(u"   с номера ", size=11, color=C_MUTED))
            n = TextBox()
            n.Width = 40
            n.Padding = Thickness(3, 1, 3, 1)
            n.Text = u"%d" % int(o.get("start") or 1)
            row.Children.Add(n)

            def upd(s, e, a=ab, ff=f, nn=n):
                d = {}
                if (ff.Text or u"").strip():
                    d["fmt"] = ff.Text.strip()
                try:
                    k = int((nn.Text or u"1").strip())
                    if k > 1:
                        d["start"] = k
                except Exception:
                    pass
                if d:
                    by[a] = d
                else:
                    by.pop(a, None)
                self._draw_sysnum(st)
            f.LostFocus += upd
            n.LostFocus += upd
            per.Children.Add(row)

    def _draw_sysnum(self, st):
        out = st.get("sysprev")
        if out is None:
            return
        out.Children.Clear()
        pv = self.core.sysnum_preview(self.infos, self.cfg)
        if not pv:
            out.Children.Add(tb(u"Нет оборудования в типах с галочкой «номер по системе».", size=12, color=C_MUTED, wrap=True))
            return
        for lab, name, sysname, n in pv[:8]:
            line = StackPanel()
            line.Orientation = Orientation.Horizontal
            line.Children.Add(tb(lab, bold=True, color=brush("#174A87"), margin=Thickness(0, 1, 8, 1)))
            short = name if len(name) <= 70 else name[:68].rstrip() + u"…"
            t = tb(u"{0}  ({1}{2})".format(short, sysname, u", {0} шт.".format(n) if n > 1 else u""), size=12)
            t.ToolTip = name
            line.Children.Add(t)
            out.Children.Add(line)
        if len(pv) > 8:
            out.Children.Add(tb(u"… ещё {0}".format(len(pv) - 8), size=12, color=C_MUTED))

    def _dock(self, el, d):
        DockPanel.SetDock(el, d)
        return el

    def _order_list(self, st, field, title, edit_keys=True, fams=False):
        key = st["key"]
        dp = DockPanel()
        dp.Children.Add(self._dock(tb(title, bold=True, margin=Thickness(0, 0, 0, 4)), Dock.Top))
        tools = WrapPanel()
        tools.Margin = Thickness(0, 6, 0, 0)
        for txt, fn, tip in ((u"↑", lambda s, e: self._move_entry(st, field, -1), u"Выше (Ctrl+↑)"),
                             (u"↓", lambda s, e: self._move_entry(st, field, 1), u"Ниже (Ctrl+↓)"),
                             (u"+", lambda s, e: self._add_entry(st, field), u"Добавить строку"),
                             (u"−", lambda s, e: self._del_entry(st, field), u"Удалить строку (Ctrl+Z — вернуть)")):
            b = Button()
            b.Content = txt
            b.Width = 30
            b.Margin = Thickness(0, 0, 4, 0)
            b.ToolTip = tip
            b.Click += fn
            tools.Children.Add(b)
        edit = StackPanel()
        edit.Margin = Thickness(0, 6, 0, 0)
        en = TextBox()
        en.Padding = Thickness(3, 2, 3, 2)
        ek = TextBox()
        ek.Padding = Thickness(3, 2, 3, 2)
        ek.Margin = Thickness(0, 4, 0, 0)
        ap = Button()
        ap.Content = u"Применить"
        ap.Padding = Thickness(8, 2, 8, 2)
        ap.Margin = Thickness(0, 4, 0, 0)
        ap.HorizontalAlignment = HorizontalAlignment.Left
        ap.ToolTip = u"То же — Enter в поле"
        edit.Children.Add(tb(u"Название (двойной щелчок по строке — переименовать на месте)", size=11, color=C_MUTED))
        edit.Children.Add(en)
        if edit_keys:
            edit.Children.Add(tb(u"Признаки в наименовании (через запятую)", size=11, color=C_MUTED, margin=Thickness(0, 4, 0, 0)))
            edit.Children.Add(ek)
        es = None
        if key == "equip" and field == "types":
            es = CheckBox()
            es.Content = u"номер по системе (как насосы: В1.1.1)"
            es.Margin = Thickness(0, 6, 0, 0)
            edit.Children.Add(es)

            def set_sys(s, e):
                i = lb.SelectedIndex
                lst = self.cfg["order"][key].get(field) or []
                if 0 <= i < len(lst):
                    lst[i]["sysnum"] = bool(es.IsChecked)
                    self.refresh_order_tabs(keep=(field, i))
            es.Click += set_sys
        edit.Children.Add(ap)
        bottom = StackPanel()
        bottom.Children.Add(tools)
        bottom.Children.Add(edit)
        dp.Children.Add(self._dock(bottom, Dock.Bottom))
        lb = ListBox()
        lb.HorizontalContentAlignment = HorizontalAlignment.Stretch
        lb.BorderBrush = C_LINE
        ScrollViewer.SetHorizontalScrollBarVisibility(lb, 0)
        dp.Children.Add(lb)
        st[field + "_edit"] = (en, ek)

        def on_sel(s, e):
            i = lb.SelectedIndex
            lst = self.cfg["order"][key].get(field) or []
            if 0 <= i < len(lst):
                en.Text = lst[i].get("name", u"")
                ek.Text = u", ".join(lst[i].get("keys") or [])
                if es is not None:
                    es.IsChecked = bool(lst[i].get("sysnum"))
            st["last_list"] = field
        lb.SelectionChanged += on_sel

        def apply_():
            i = lb.SelectedIndex
            lst = self.cfg["order"][key].get(field) or []
            if 0 <= i < len(lst):
                lst[i]["name"] = (en.Text or u"").strip() or lst[i]["name"]
                if edit_keys:
                    lst[i]["keys"] = [x.strip() for x in (ek.Text or u"").split(u",") if x.strip()]
                self.refresh_order_tabs(keep=(field, i))
        ap.Click += lambda s, e: apply_()
        self._enter_actions.append((en, apply_))
        self._enter_actions.append((ek, apply_))
        fmt_row = "SM_ROW_" + key + field
        Dragger(lb, lambda i: (fmt_row, str(i), (self.cfg["order"][key].get(field) or [{}])[i].get("name")
                               if 0 <= i < len(self.cfg["order"][key].get(field) or []) else None), self.viz)

        def drop(s, e):
            lst = self.cfg["order"][key].setdefault(field, [])
            idx = item_index(lb, e.OriginalSource)
            if e.Data.GetDataPresent(fmt_row):
                src = int(e.Data.GetData(fmt_row))
                pos = DragViz.drop_index(lb, e)
                if 0 <= src < len(lst):
                    x = lst.pop(src)
                    if pos > src:
                        pos -= 1
                    lst.insert(max(0, min(pos, len(lst))), x)
                    self.refresh_order_tabs(keep=(field, lst.index(x)))
            elif e.Data.GetDataPresent("SM_FAM") and 0 <= idx < len(lst):
                for tag in (u"%s" % e.Data.GetData("SM_FAM")).split(u"\n"):
                    if tag:
                        self._assign_tag(key, tag, idx, field, refresh=False)
                self.refresh_order_tabs(keep=(field, idx))
            elif e.Data.GetDataPresent("SM_CHIP") and 0 <= idx < len(lst):
                for ck, cf, tag in self._chips_of(e.Data.GetData("SM_CHIP")):
                    if ck == key:
                        if cf != field:
                            self._unassign(key, tag, cf, refresh=False)
                        self._assign_tag(key, tag, idx, field, refresh=False)
                self.sel_fchips = set()
                self.refresh_order_tabs(keep=(field, idx))
            self.viz.end()
            e.Handled = True
        lb.Drop += drop

        def can(fmt, idx):
            if fmt in ("SM_FAM", "SM_CHIP"):
                return idx >= 0 and (fams or key in self.core.D.INS_KEYS)
            return True
        self.viz.target(lb, [fmt_row, "SM_FAM", "SM_CHIP"], reorder=(fmt_row,), on_item=can)
        return dp, lb

    def _entry_bind_lists(self, key, entry, tag):
        """(список в строке, значение) для тега: F — fams, T — ftypes, I — fams (имена типов изоляции)."""
        p = tag.split(u"\t")
        if p[0] == "T" and len(p) >= 3:
            return entry.setdefault("ftypes", []), self.core.ftype_key(p[1], p[2])
        return entry.setdefault("fams", []), p[-1]

    def _assign_tag(self, key, tag, idx, field="types", refresh=True):
        """Семейство / тип / тип изоляции — в строку idx; из других строк того же списка убирается."""
        lst = self.cfg["order"][key].setdefault(field, [])
        if not (0 <= idx < len(lst)):
            return
        for t in lst:
            arr, val = self._entry_bind_lists(key, t, tag)
            while val in arr:
                arr.remove(val)
        arr, val = self._entry_bind_lists(key, lst[idx], tag)
        arr.append(val)
        if refresh:
            self.refresh_order_tabs(keep=(field, idx))

    def _unassign(self, key, tag, field, refresh=True):
        for t in self.cfg["order"][key].get(field) or []:
            arr, val = self._entry_bind_lists(key, t, tag)
            while val in arr:
                arr.remove(val)
        if refresh:
            self.refresh_order_tabs()

    def _assign_selected(self, st, field="types"):
        lbu = st.get("lbu")
        lb = st.get("lbm" if field == "materials" else "lbt")
        if lbu is None or lb is None or lb.SelectedIndex < 0:
            return
        tags = [x.Tag for x in lbu.SelectedItems if x.Tag]
        for tag in tags:
            self._assign_tag(st["key"], tag, lb.SelectedIndex, field, refresh=False)
        self.refresh_order_tabs(keep=(field, lb.SelectedIndex))

    def _fam_chip(self, st, field, tag):
        """Плашка привязанного семейства / типа: × — убрать; Ctrl+щелчок — выбрать; перетащить (все выбранные) —
        в другую строку или в «Не распределено»."""
        key = st["key"]
        ck = (key, field, tag)
        b = Border()
        b.Tag = CHIP_TAG
        b.CornerRadius = CornerRadius(4)
        b.Background = brush("#E8EEF6") if not tag.startswith(u"T\t") else brush("#EEF4E8")
        b.BorderBrush = C_BLUE if ck in self.sel_fchips else brush("#B9CDE8")
        b.BorderThickness = Thickness(2) if ck in self.sel_fchips else Thickness(1)
        b.Padding = Thickness(6, 0, 1, 0)
        b.Margin = Thickness(0, 2, 4, 0)
        b.ToolTip = (u"Тип (главнее семейства). " if tag.startswith(u"T\t") else u"") + \
            u"Перетащите в другую строку или обратно в «Не распределено»; Ctrl+щелчок — выбрать несколько; × — убрать"
        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal
        sp.Children.Add(tb(self._tag_text(tag), size=11, color=brush("#174A87")))
        x = Button()
        x.Content = u"×"
        x.Padding = Thickness(4, 0, 4, 0)
        x.Margin = Thickness(4, 0, 0, 0)
        x.Background = Brushes.Transparent
        x.BorderThickness = Thickness(0)
        x.ToolTip = u"Убрать «{0}» отсюда".format(self._tag_text(tag))
        x.Click += lambda s, e: self._unassign(key, tag, field)
        sp.Children.Add(x)
        b.Child = sp
        state = {"p": None}

        def down(s, e):
            if ancestor(e.OriginalSource, Button) is not None:
                state["p"] = None
                return
            if (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control:
                state["p"] = None
                state["ctrl"] = True
                return
            state["ctrl"] = False
            state["p"] = e.GetPosition(None)

        def up(s, e):
            if state.get("ctrl") and ancestor(e.OriginalSource, Button) is None:
                state["ctrl"] = False
                if ck in self.sel_fchips:
                    self.sel_fchips.discard(ck)
                else:
                    self.sel_fchips.add(ck)
                self._paint_fchips(st)
                e.Handled = True

        def move(s, e):
            p0 = state["p"]
            if p0 is None or e.LeftButton != MouseButtonState.Pressed:
                return
            p = e.GetPosition(None)
            if abs(p.X - p0.X) < SystemParameters.MinimumHorizontalDragDistance and \
                    abs(p.Y - p0.Y) < SystemParameters.MinimumVerticalDragDistance:
                return
            state["p"] = None
            sel = [c for c in self.sel_fchips if c[0] == key] if ck in self.sel_fchips else [ck]
            data = u"\n".join(u"\t".join(c) for c in sel)
            self.viz.start(b, "SM_CHIP", data, self._tag_text(tag) if len(sel) == 1 else None)
            e.Handled = True
        b.PreviewMouseLeftButtonDown += down
        b.PreviewMouseLeftButtonUp += up
        b.PreviewMouseMove += move
        st.setdefault("chip_elems", []).append((b, ck))
        return b

    def _move_entry(self, st, field, d):
        lb = st.get("lbm" if field == "materials" else "lbt")
        lst = self.cfg["order"][st["key"]].get(field) or []
        i = lb.SelectedIndex if lb is not None else -1
        j = i + d
        if 0 <= i < len(lst) and 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.refresh_order_tabs(keep=(field, j))

    def _move_focused_entry(self, d):
        st = self.order_tabs.get(self._cur_order_key())
        if st is None:
            return
        field = st.get("last_list") or ("materials" if st.get("lbm") is not None else "types")
        self._move_entry(st, field, d)

    def _add_entry(self, st, field):
        lst = self.cfg["order"][st["key"]].setdefault(field, [])
        lst.append({"name": u"Новый", "keys": [], "fams": []})
        self.refresh_order_tabs(keep=(field, len(lst) - 1))
        lb = st.get("lbm" if field == "materials" else "lbt")
        if lb is not None and lb.Items.Count:
            self._later(lambda: self._rename_inline(st, field, len(lst) - 1))

    def _del_entry(self, st, field):
        lb = st.get("lbm" if field == "materials" else "lbt")
        lst = self.cfg["order"][st["key"]].get(field) or []
        i = lb.SelectedIndex if lb is not None else -1
        if 0 <= i < len(lst):
            lst.pop(i)
            self.refresh_order_tabs()

    def _rename_inline(self, st, field, i):
        """Переименование строки на месте: Enter и щелчок мимо — сохранить, Esc — отмена."""
        lb = st.get("lbm" if field == "materials" else "lbt")
        lst = self.cfg["order"][st["key"]].get(field) or []
        if lb is None or not (0 <= i < len(lst)) or i >= lb.Items.Count:
            return
        li = lb.Items[i]
        sp = li.Content
        if not isinstance(sp, StackPanel) or not sp.Children.Count:
            return
        old = sp.Children[0]
        box = TextBox()
        box.Text = lst[i].get("name") or u""
        box.Padding = Thickness(3, 1, 3, 1)
        box.FontWeight = FontWeights.SemiBold
        done = {"v": False}

        def commit(s=None, e=None):
            if done["v"]:
                return
            done["v"] = True
            v = (box.Text or u"").strip()
            if v:
                lst[i]["name"] = v
            self._later(lambda: self.refresh_order_tabs(keep=(field, i)))
        box.LostFocus += commit
        sp.Children.RemoveAt(0)
        sp.Children.Insert(0, box)
        self._later(lambda: (box.Focus(), box.SelectAll()))

    def refresh_order_tabs(self, keep=None):
        D = self.core.D
        order = self.cfg["order"]
        for key, st in self.order_tabs.items():
            o = order.get(key) or {}
            its = [i for i in self.infos if i.key == key]
            for i in its:
                self.core.classify(i, order)
            mats = o.get("materials") or []
            types = o.get("types") or []
            on = self._cat_on(key)
            st["cb_on"].IsChecked = on
            st["on_bd"].Background = brush("#F3F8FE") if on else C_ZERO
            st["on_note"].Text = (u"" if on else u"Выключено — «по имени»: ADSK_Наименование → диаметр → марка → код. "
                                  u"Списки сохранены, действуют при включении.")
            st["chip_elems"] = []
            isk = key in D.INS_KEYS
            if st.get("lbm") is not None:
                self._fill(st, st["lbm"], [(m.get("name"), u", ".join(m.get("keys") or [])) for m in mats],
                           [sum(1 for i in its if i.mat == n) for n in range(len(mats))], "materials",
                           [self._entry_tags(key, m) for m in mats])
            if st.get("lbt") is not None:
                rows = []
                for t in types:
                    extra = u", ".join(t.get("keys") or [])
                    if key == "equip" and t.get("sysnum"):
                        extra += (u" | " if extra else u"") + u"номер по системе"
                    rows.append((t.get("name"), extra))
                self._fill(st, st["lbt"], rows, [sum(1 for i in its if i.tp == n) for n in range(len(types))],
                           "types", [self._entry_tags(key, t) for t in types])
            no_mat = st.get("lbm") is not None
            no_typ = bool(types) and st.get("lbt") is not None
            if isk:
                un = {}
                for i in its:
                    if i.mat >= len(mats):
                        un[i.typ or u"(без типа)"] = un.get(i.typ or u"(без типа)", 0) + 1
                fams = dict((u"I\t" + t, (t, n, [u"строка"], [])) for t, n in un.items())
            else:
                fams = {}
                for i in its:
                    if i.parent_id is not None:
                        continue            # вложенные идут за родителем
                    m_bad = no_mat and bool(mats) and i.mat >= len(mats)
                    t_bad = no_typ and i.tp >= len(types)
                    if not (m_bad or t_bad):
                        continue
                    f = fams.setdefault(u"F\t" + i.fam, [i.fam, 0, set(), {}])
                    f[1] += 1
                    if m_bad:
                        f[2].add(u"материал")
                    if t_bad:
                        f[2].add(u"тип")
                    tt = f[3].setdefault(i.typ, [0, set()])
                    tt[0] += 1
                    if m_bad:
                        tt[1].add(u"материал")
                    if t_bad:
                        tt[1].add(u"тип")
            if st.get("sysprev") is not None:
                self._draw_sysper(st)
                self._draw_sysnum(st)
            lbu = st["lbu"]
            keep_sel = set(x.Tag for x in lbu.SelectedItems if x.Tag)
            lbu.Items.Clear()
            for tag in sorted(fams.keys(), key=lambda x: x.lower()):
                v = fams[tag]
                if isk:
                    lbu.Items.Add(self._un_item(tag, u"⋮⋮  {0}   ×{1}".format(v[0], v[1]), None, keep_sel))
                    continue
                fam, n, miss, types_ = v
                opened = (key, fam) in self._fam_open
                need = [x for x in (u"материал", u"тип") if x in miss]
                li = self._un_item(tag, u"{0}  {1}   ×{2}".format(u"▾" if opened else u"▸", fam, n),
                                   u"нет: " + u", ".join(need), keep_sel)
                li.Tag = tag
                li.MouseDoubleClick += lambda s, e, k=key, f_=fam: self._toggle_fam(k, f_)
                li.PreviewMouseLeftButtonDown += lambda s, e, k=key, f_=fam: self._fam_arrow(s, e, k, f_)
                lbu.Items.Add(li)
                if opened:
                    for typ in sorted(types_.keys(), key=lambda x: (x or u"").lower()):
                        c, ms = types_[typ]
                        ti = self._un_item(u"T\t{0}\t{1}".format(fam, typ), u"    {0}   ×{1}".format(typ or u"(тип)", c),
                                           u"нет: " + u", ".join(x for x in (u"материал", u"тип") if x in ms),
                                           keep_sel, indent=True)
                        lbu.Items.Add(ti)
        if keep is not None:
            k = self._cur_order_key()
            st = self.order_tabs.get(k)
            if st is not None:
                lb = st.get("lbm" if keep[0] == "materials" else "lbt")
                if lb is not None and 0 <= keep[1] < lb.Items.Count:
                    lb.SelectedIndex = keep[1]
        k = self._cur_order_key()
        if k:
            inner = (order.get(k) or {}).get("inner", "type")
            self.rbTypeDiam.IsChecked = inner != "diam"
            self.rbDiamType.IsChecked = inner == "diam"

    def _un_item(self, tag, text, sub, keep_sel, indent=False):
        li = ListBoxItem()
        li.Tag = tag
        sp = StackPanel()
        sp.Children.Add(tb(text, size=12 if not indent else 11.5, wrap=True,
                           color=brush("#3D4652") if indent else None))
        if sub and sub != u"нет: ":
            sp.Children.Add(tb(sub, size=10.5, color=brush("#8A5A00"), margin=Thickness(36 if indent else 22, 0, 0, 0)))
        li.Content = sp
        if indent:
            li.ToolTip = u"Тип — перетащите отдельно; привязка типа главнее семейства"
        elif tag.startswith(u"F\t"):
            li.ToolTip = u"▸ — типы семейства; тащите семейство целиком или его тип"
        if tag in keep_sel:
            li.IsSelected = True
        return li

    def _fam_arrow(self, s, e, key, fam):
        """Щелчок по ▸ / ▾ в начале строки — раскрыть / свернуть типы семейства."""
        try:
            if e.GetPosition(s).X <= 20:
                self._toggle_fam(key, fam)
                e.Handled = True
        except Exception:
            pass

    def _toggle_fam(self, key, fam):
        k = (key, fam)
        if k in self._fam_open:
            self._fam_open.discard(k)
        else:
            self._fam_open.add(k)
        self._later(self.refresh_order_tabs)

    def _entry_tags(self, key, entry):
        """Привязки строки -> теги плашек: семейства, типы («семейство: тип»), типы изоляции."""
        if key in self.core.D.INS_KEYS:
            return [u"I\t" + f for f in entry.get("fams") or []]
        out = [u"F\t" + f for f in entry.get("fams") or []]
        sep = getattr(self.core, "FT_SEP", u"␟")
        for ft in entry.get("ftypes") or []:
            fam, _, typ = ft.partition(sep)
            out.append(u"T\t{0}\t{1}".format(fam, typ))
        return out

    def _fill(self, st, lb, rows, counts, field, chips):
        lb.Items.Clear()
        for n, (name, extra) in enumerate(rows):
            li = ListBoxItem()
            sp = StackPanel()
            sp.Children.Add(tb(u"⋮⋮  {0}. {1}   ×{2}".format(n + 1, name, counts[n] if n < len(counts) else 0), bold=True))
            if extra:
                sp.Children.Add(tb(extra, size=11, color=C_MUTED, wrap=True, margin=Thickness(22, 0, 0, 0)))
            tags = chips[n] if chips is not None and n < len(chips) else []
            if tags:
                wp = WrapPanel()
                wp.Margin = Thickness(22, 1, 0, 1)
                for tag in tags:
                    wp.Children.Add(self._fam_chip(st, field, tag))
                sp.Children.Add(wp)
            li.Content = sp
            li.Padding = Thickness(4, 3, 4, 3)
            li.MouseDoubleClick += lambda s, e, i=n: (self._rename_inline(st, field, i), setattr(e, "Handled", True))
            lb.Items.Add(li)

    # ---------------- 4. сортировка ----------------
    def _init_page3(self):
        self.sort_keys = [("common", u"Общая (все категории)")]
        for key, bname, title, order in sorted(self.core.D.CATS, key=lambda c: c[3]):
            if any(i.key == key for i in self.infos):
                self.sort_keys.append((key, title))
        for k, t in self.sort_keys:
            self.cbSortFor.Items.Add(t)
        self.cbSortFor.SelectionChanged += self.on_sort_for
        self.btnSortReset.Click += lambda s, e: self.on_sort_reset()
        self.btnSortDraft.Click += lambda s, e: self.on_sort_draft()
        self._spec_prev = None
        self.tbQty.Text = (u"%g" % float(self.cfg.get("qty_min", self.core.D.QTY_MIN))).replace(u".", u",")
        self.cbDelSheets.IsChecked = bool(self.cfg.get("delete_empty_sheets"))
        self.add_specs = {}
        self.btnQtyRows.Click += lambda s, e: self.on_qty_rows()
        self._qty_info()
        self.btnAddParam.Click += self.on_add_param
        self.btnSUp.Click += lambda s, e: self._move_sort(-1)
        self.btnSDown.Click += lambda s, e: self._move_sort(1)
        self._fill_rank_params()
        self.cbSortParam.LostFocus += lambda s, e: self._set_rank_params()
        self.cbKitParam.LostFocus += lambda s, e: self._set_rank_params()
        self.cbSortParam.SelectionChanged += lambda s, e: self._later(self._set_rank_params)
        self.cbKitParam.SelectionChanged += lambda s, e: self._later(self._set_rank_params)

        def payload(i):
            rows, own = self._sort_rows()
            if not (0 <= i < len(rows)):
                return None
            sel = sorted(self.lbSort.Items.IndexOf(x) for x in self.lbSort.SelectedItems)
            if i not in sel:
                sel = [i]
            return ("SM_SORT", u"\n".join(str(x) for x in sel),
                    (rows[i].get("label") or rows[i]["param"]) if len(sel) == 1 else None)
        Dragger(self.lbSort, payload, self.viz)
        self.lbSort.Drop += self.on_sort_drop
        self.viz.target(self.lbSort, ["SM_SORT"], reorder=("SM_SORT",))
        self.cbSortFor.SelectedIndex = 0

    def _all_param_names(self):
        names = set()
        for lst in (getattr(self.core, "SFIELDS", None) or {}).values():
            for f in lst:
                if f.get("name"):
                    names.add(f["name"])
        return sorted(names, key=lambda x: (not x.startswith(u"ADSK"), x.lower()))

    def _fill_rank_params(self):
        names = self._all_param_names()
        for cb_, cur, extra in ((self.cbSortParam, self.core.sort_param(self.cfg), []),
                                (self.cbKitParam, self.core.kit_param(self.cfg), [NO_WRITE])):
            cb_.Items.Clear()
            for n in extra + names:
                cb_.Items.Add(n)
            cb_.Text = cur or (NO_WRITE if extra else u"")

    def _set_rank_params(self):
        sp = (self.cbSortParam.Text or u"").strip()
        kp = (self.cbKitParam.Text or u"").strip()
        self.cfg["sort_param"] = sp or self.core.D.SORT_PARAM
        self.cfg["kit_param"] = u"" if kp in (u"", NO_WRITE) else kp
        self._sort_warn()

    def _sort_warn(self):
        """Жёлтым — заранее: у каких категорий нет параметров, нужных сортировке."""
        miss = {}
        try:
            miss = self.core.missing_sort_params(self.cfg)
        except Exception:
            miss = {}
        present = set(k for k, t in self.sort_keys if k != "common")
        title = dict(self.sort_keys)
        lines = []
        for prm in sorted(miss):
            cats = [title.get(k, k) for k in miss[prm] if k in present]
            if not cats:
                continue
            if prm == self.core.sort_param(self.cfg):
                hint = u" — выберите другой параметр ниже («Ранг строки»), иначе порядок строк задаст Revit"
            elif prm == self.core.kit_param(self.cfg):
                hint = u" — выберите другой или «— не писать —»"
            elif prm == P_SYS:
                hint = u" — параметр проекта (как Bim2B); без него нет сортировки по системе"
            else:
                hint = u""
            lines.append(u"нет «{0}» у: {1}{2}".format(prm, u", ".join(cats), hint))
        if not self.core.order_on(self.cfg):
            lines.append(u"шаг 3 выключен — «Материал и тип» не действует, порядок «по имени»")
        self.tSortWarn.Text = u"\n".join(lines)
        self.bdSortWarn.Visibility = Visibility.Visible if lines else Visibility.Collapsed

    def _sort_rows(self):
        """-> (строки для показа, своя?). Категория без своей показывает общую."""
        s = self.cfg.setdefault("sort", {})
        if self.sort_key != "common" and self.sort_key in s:
            return s[self.sort_key], True
        return s.setdefault("common", copy.deepcopy(self.core.D.SORT_FIELDS)), self.sort_key == "common"

    def _edit_rows(self):
        """Строки для правки: у категории без своей сортировки «своя» создаётся при первой правке."""
        s = self.cfg.setdefault("sort", {})
        if self.sort_key != "common" and self.sort_key not in s:
            s[self.sort_key] = copy.deepcopy(s.get("common") or self.core.D.SORT_FIELDS)
            self.status(u"Для «{0}» создана своя сортировка (копия общей)".format(dict(self.sort_keys)[self.sort_key]))
        return self._sort_rows()[0]

    def on_sort_for(self, s, e):
        i = self.cbSortFor.SelectedIndex
        self.sort_key = self.sort_keys[i][0] if i >= 0 else "common"
        self.fill_add_params()
        self.draw_sort()

    def _sort_mode_badge(self):
        own = self.sort_key != "common" and self.sort_key in (self.cfg.get("sort") or {})
        if self.sort_key == "common":
            self.tSortMode.Text = u"общая — для категорий без своей"
            self.bdSortMode.Background = brush("#EEF1F4")
        elif own:
            self.tSortMode.Text = u"своя"
            self.bdSortMode.Background = brush("#E3EEFB")
        else:
            self.tSortMode.Text = u"как в общей — правка создаст свою"
            self.bdSortMode.Background = brush("#EEF1F4")
        self.btnSortReset.IsEnabled = own
        self.btnSortDraft.IsEnabled = self.sort_key in self.core.D.SORT_DRAFTS

    def on_sort_reset(self):
        srt = self.cfg.setdefault("sort", {})
        if srt.pop(self.sort_key, None) is not None:
            self.status(u"Сортировка «{0}» — как в общей".format(dict(self.sort_keys)[self.sort_key]))
        self.draw_sort()

    def on_sort_draft(self):
        d = self.core.D.SORT_DRAFTS.get(self.sort_key)
        if d:
            self.cfg.setdefault("sort", {})[self.sort_key] = copy.deepcopy(d)
            self.status(u"«{0}»: набор по умолчанию (черновик) — поправьте под себя".format(
                dict(self.sort_keys)[self.sort_key]))
            self.draw_sort()

    def fill_add_params(self):
        """Все поля «экземпляр»/«тип», которые Revit даёт в спецификацию этой категории (для «Общей» — всех)."""
        sf = getattr(self.core, "SFIELDS", None) or {}
        present = [k for k, t in self.sort_keys if k != "common"]
        keys = present if self.sort_key == "common" else [self.sort_key]
        specs = {}
        for k in keys:
            for f in sf.get(k) or []:
                if f["name"] not in specs:
                    specs[f["name"]] = f
        for p_ in self.core.D.EXTRA_SORT_PARAMS:
            if p_ not in specs:
                specs[p_] = {"name": p_, "param": p_}
        self.add_specs = specs
        names = sorted(specs.keys(), key=lambda x: (not x.startswith(u"ADSK"), x.lower()))
        self.cbAddParam.Items.Clear()
        for n in names:
            self.cbAddParam.Items.Add(n)
        self.cbAddParam.Text = u""
        if not sf:
            self.addInfo.Text = u"(список полей не прочитан — можно вписать имя параметра)"
        elif self.sort_key == "common":
            self.addInfo.Text = u"{0} полей во всех категориях; нет в категории — строка встаёт в конец".format(len(names))
        else:
            self.addInfo.Text = u"{0} полей категории (как в «Свойствах спецификации» Revit)".format(len(names))

    def draw_sort(self, keep=None):
        rows, own = self._sort_rows()
        self._sort_mode_badge()
        self._sort_warn()
        kit_off = not self.core.order_on(self.cfg, None if self.sort_key == "common" else self.sort_key)
        self.lbSort.Items.Clear()
        n = 0
        for i, r in enumerate(rows):
            li = ListBoxItem()
            li.Padding = Thickness(4, 4, 4, 4)
            g = Grid()
            for w in (GridLength(26), GridLength(28), GridLength(30), GridLength(1, GridUnitType.Star), GridLength(260),
                      GridLength(110), GridLength(34)):
                cd = ColumnDefinition()
                cd.Width = w
                g.ColumnDefinitions.Add(cd)
            g.Children.Add(tb(u"⋮⋮", color=brush("#8A939E")))
            gray = kit_off and r["param"] == self.core.P_KIT
            on = CheckBox()
            on.IsChecked = bool(r.get("on"))
            on.VerticalAlignment = VerticalAlignment.Center

            def set_on(s, e, idx=i):
                self._edit_rows()[idx]["on"] = bool(s.IsChecked)
                self.draw_sort(keep=idx)
            on.Click += set_on
            Grid.SetColumn(on, 1)
            g.Children.Add(on)
            if r.get("on"):
                n += 1
            num = tb(str(n) if r.get("on") else u"–", color=C_MUTED)
            Grid.SetColumn(num, 2)
            g.Children.Add(num)
            lab = StackPanel()
            lab.Children.Add(tb(r.get("label") or r["param"], bold=True,
                                color=C_TEXT if r.get("on") and not gray else C_MUTED))
            sub = []
            if gray:
                sub.append(u"шаг 3 пропущен — не действует, порядок «по имени»")
            elif r.get("label") and r.get("label") != r["param"]:
                sub.append(u"расчёт кнопки" if r["param"] in (self.core.P_KIT, self.core.P_SORT) else r["param"])
            if r.get("ftype") == "type":
                sub.append(u"параметр типа")
            elif r.get("pid") is not None and r.get("pid") < 0:
                sub.append(u"параметр Revit")
            if sub:
                lab.Children.Add(tb(u" · ".join(sub), size=11, color=C_MUTED))
            Grid.SetColumn(lab, 3)
            g.Children.Add(lab)
            od = StackPanel()
            od.Orientation = Orientation.Horizontal
            for asc, txt in ((True, u"↑ по возрастанию"), (False, u"↓ по убыванию")):
                rb = RadioButton()
                rb.Content = txt
                rb.GroupName = u"ord{0}_{1}".format(self.sort_key, i)
                rb.IsChecked = bool(r.get("asc", True)) == asc
                rb.Margin = Thickness(0, 0, 10, 0)
                rb.VerticalAlignment = VerticalAlignment.Center

                def set_asc(s, e, idx=i, a=asc):
                    self._edit_rows()[idx]["asc"] = a
                    self._sort_mode_badge()
                rb.Click += set_asc
                od.Children.Add(rb)
            Grid.SetColumn(od, 4)
            g.Children.Add(od)
            hd = CheckBox()
            hd.Content = u"заголовок"
            hd.IsChecked = bool(r.get("header"))
            hd.VerticalAlignment = VerticalAlignment.Center
            if r["param"] != P_GRP:
                hd.IsEnabled = False
                hd.ToolTip = u"Заголовок возможен только для ADSK_Группирование (по системе — «Делить по» в окне «Системы»)"

            def set_hd(s, e, idx=i):
                self._edit_rows()[idx]["header"] = bool(s.IsChecked)
                self._sort_mode_badge()
            hd.Click += set_hd
            Grid.SetColumn(hd, 5)
            g.Children.Add(hd)
            x = Button()
            x.Content = u"×"
            x.Width = 26
            x.Background = Brushes.Transparent
            x.BorderThickness = Thickness(0)
            x.ToolTip = u"Убрать строку (Ctrl+Z — вернуть)"

            def rem(s, e, idx=i):
                self._edit_rows().pop(idx)
                self.draw_sort()
            x.Click += rem
            Grid.SetColumn(x, 6)
            g.Children.Add(x)
            li.Content = g
            if gray:
                li.Background = brush("#F1F3F5")
            self.lbSort.Items.Add(li)
        if keep is not None:
            for k in (keep if isinstance(keep, (list, tuple, set)) else [keep]):
                if 0 <= k < self.lbSort.Items.Count:
                    self.lbSort.Items[k].IsSelected = True

    def _move_sort(self, d):
        sel = sorted(self.lbSort.Items.IndexOf(x) for x in self.lbSort.SelectedItems)
        rows = self._sort_rows()[0]
        if not sel or (d < 0 and sel[0] == 0) or (d > 0 and sel[-1] == len(rows) - 1):
            return
        rows = self._edit_rows()
        for i in (sel if d < 0 else reversed(sel)):
            rows[i], rows[i + d] = rows[i + d], rows[i]
        self.draw_sort(keep=[i + d for i in sel])

    def on_sort_drop(self, s, e):
        if e.Data.GetDataPresent("SM_SORT"):
            src = [int(x) for x in (u"%s" % e.Data.GetData("SM_SORT")).split(u"\n") if x.strip()]
            pos = DragViz.drop_index(self.lbSort, e)
            rows = self._edit_rows()
            src = [i for i in src if 0 <= i < len(rows)]
            if src:
                moving = [rows[i] for i in src]
                rest = [r for k, r in enumerate(rows) if k not in src]
                pos -= sum(1 for i in src if i < pos)
                pos = max(0, min(pos, len(rest)))
                rows[:] = rest[:pos] + moving + rest[pos:]
                self.draw_sort(keep=list(range(pos, pos + len(moving))))
        self.viz.end()
        e.Handled = True

    def on_add_param(self, s, e):
        txt = (self.cbAddParam.Text or u"").strip()
        if not txt:
            return
        f = self.add_specs.get(txt)
        if f is None:                                   # вписано вручную
            low = txt.lower()
            f = next((v for k, v in self.add_specs.items() if k.lower() == low), None) or {"name": txt, "param": txt}
        rows = self._sort_rows()[0]
        if any(r["param"] == f["param"] and r.get("pid") == f.get("pid") for r in rows):
            return
        rows = self._edit_rows()
        r = {"param": f["param"], "label": f["name"], "on": True, "asc": True, "header": False}
        if f.get("pid") is not None:
            r["pid"] = f["pid"]
            r["ftype"] = f.get("ftype")
        rows.append(r)
        self.draw_sort(keep=len(rows) - 1)

    def draw_pos_preview(self):
        mode = (self.cfg.get("pos") or {}).get("mode", "group")
        if self._spec_prev is None:
            self._spec_prev = self.core.spec_preview(self.infos, self.cfg, self.mat_items)
        sp = self._spec_prev
        if not sp:
            self.posPreview.Text = u""
            return
        first = sp[0]
        same = [x for x in sp if x[3] == first[3]]
        nxt = same[1] if len(same) > 1 else None
        other = next((x for x in sp if x[3] != first[3]), None)
        nm = lambda x: u"«{0}.{1} {2}»".format(x[0], x[1], x[2])
        parts = []
        if mode == "group_prefix":
            gl = [g["name"] for g in (self.cfg.get("groups") or [])]
            for gi, gname in enumerate(gl[:3]):
                parts.append(u"{0}: {1}.1, {1}.2 …".format(gname, gi + 1))
        elif mode == "spec_dot":
            parts.append(u"{0}: {1}.1, {1}.2 …".format(nm(first), first[0]))
            if nxt:
                parts.append(u"{0}: {1}.1 …".format(nm(nxt), nxt[0]))
            if other:
                parts.append(u"{0}: {1}.1 …".format(nm(other), other[0]))
        else:
            parts.append(u"{0}: 1, 2 …".format(nm(first)))
            if nxt:
                parts.append(u"{0}: продолжение".format(nm(nxt)))
            if other:
                parts.append(u"{0}: {1}".format(nm(other), u"снова с 1" if mode == "group" else u"продолжение, без сброса"))
        self.posPreview.Text = u"Пример: " + u"  →  ".join(parts)
        fmt = (self.cfg.get("pos") or {}).get("sysnum_fmt") or self.core.D.SYSNUM_FMT
        pv = self.core.sysnum_preview(self.infos, self.cfg)
        labs = [x[0] for x in pv[:5]] or [self.core.sysnum_label(u"В1.1", 1, fmt)]
        self.posNote.Text = (u"Насосы (номер по системе, вне общего счёта): {0}{1} — список и формат в окне «Материалы и "
                             u"типы» → Оборудование. Начинка оборудования: 10 → 10.1, 10.2; вложенная арматура — "
                             u"следующими номерами. Таблица материалов продолжает нумерацию связки.").format(
            u", ".join(labs), u" …" if len(pv) > 5 else u"")

    def _qty_info(self):
        n = len(self.cfg.get("qty_hide") or [])
        self.qtyInfo.Text = (u"Скрыть отмечено строк: {0}. Остальные малые строки остаются в спецификации.".format(n) if n
                             else u"Малые строки сами не скрываются. Нажмите, чтобы посмотреть их и отметить, что скрыть.")

    def on_qty_rows(self):
        """Окно: строки спецификаций с количеством меньше порога, суммы по единицам, галка — скрыть."""
        self.collect_hidden()
        self.collect_sort_extras()
        qmin = float(self.cfg.get("qty_min", self.core.D.QTY_MIN))
        try:
            rows = self.core.small_rows_preview(self.infos, self.cfg)
        except Exception as ex:
            MessageBox.Show(self.win, u"Не удалось посчитать строки:\n{0}".format(ex), u"Строки < порога",
                            MessageBoxButton.OK, MessageBoxImage.Warning)
            return
        hide = set(self.cfg.get("qty_hide") or [])
        w = Window()
        T.dress(w)
        w.Title = u"Строки с количеством меньше {0:g}".format(qmin)
        w.Width = 900
        w.Height = 620
        w.WindowStartupLocation = WindowStartupLocation.CenterOwner
        w.Owner = self.win
        w.FontFamily = self.win.FontFamily
        w.FontSize = 13
        dp = DockPanel()
        dp.Margin = Thickness(14, 12, 14, 12)
        head = tb(u"Отмеченные строки не попадут в спецификацию; без галки — остаются. Сами строки не скрываются. "
                  u"Количество — сумма строки, как её посчитает Revit (трубам без количества — длина). "
                  u"Найдено строк: {0}.".format(len(rows)), wrap=True, color=brush("#4A5361"),
                  margin=Thickness(0, 0, 0, 8))
        DockPanel.SetDock(head, Dock.Top)
        dp.Children.Add(head)
        bottom = StackPanel()
        DockPanel.SetDock(bottom, Dock.Bottom)
        sums = tb(u"", wrap=True, size=12, color=brush("#174A87"), margin=Thickness(0, 8, 0, 0))
        bottom.Children.Add(sums)
        bt = StackPanel()
        bt.Orientation = Orientation.Horizontal
        bt.HorizontalAlignment = HorizontalAlignment.Right
        bt.Margin = Thickness(0, 10, 0, 0)
        bottom.Children.Add(bt)
        dp.Children.Add(bottom)
        sv = ScrollViewer()
        sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        lst = StackPanel()
        sv.Content = lst
        dp.Children.Add(sv)
        boxes = []

        def fmtq(v):
            return (u"%g" % round(v, 4)).replace(u".", u",")

        def recount(*a):
            hid, show = {}, {}
            for cb_, r_ in boxes:
                d = hid if cb_.IsChecked else show
                d[r_["unit"]] = d.get(r_["unit"], 0.0) + r_["qty"]
            txt = lambda d: u"; ".join(u"{0} {1}".format(fmtq(v), k or u"(без ед.)") for k, v in sorted(d.items())) or u"—"
            sums.Text = u"Скрыть: {0}     Оставить: {1}".format(txt(hid), txt(show))
        if not rows:
            lst.Children.Add(tb(u"Строк с количеством меньше {0:g} нет.".format(qmin), color=C_MUTED))
        last = None
        for r_ in rows:
            if r_["group"] != last:
                lst.Children.Add(tb(u"Группа {0}".format(r_["group"]), bold=True, color=brush("#174A87"),
                                    margin=Thickness(0, 8, 0, 2)))
                last = r_["group"]
            g = Grid()
            for wd in (GridLength(28), GridLength(270), GridLength(1, GridUnitType.Star), GridLength(110), GridLength(60)):
                cd = ColumnDefinition()
                cd.Width = wd
                g.ColumnDefinitions.Add(cd)
            cb_ = CheckBox()
            cb_.IsChecked = r_["sig"] in hide
            cb_.VerticalAlignment = VerticalAlignment.Center
            cb_.Click += recount
            g.Children.Add(cb_)
            cat_ = r_["cat"] + (u" · " + r_["sys"] if r_.get("sys") else u"")
            for col, (txt_, kw) in enumerate(((cat_, {"color": C_MUTED, "size": 12, "wrap": True}),
                                             (r_["name"], {"wrap": True}),
                                             (u"{0} {1}".format(fmtq(r_["qty"]), r_["unit"]), {"bold": True}),
                                             (u"{0} эл.".format(r_["n"]), {"color": C_MUTED, "size": 12})), 1):
                t_ = tb(txt_, **kw)
                Grid.SetColumn(t_, col)
                g.Children.Add(t_)
            g.Margin = Thickness(0, 1, 0, 1)
            lst.Children.Add(g)
            boxes.append((cb_, r_))
        recount()
        res = {}

        def set_all(v):
            for cb_, r_ in boxes:
                cb_.IsChecked = v
            recount()

        def ok(s, e):
            res["ok"] = True
            w.DialogResult = True
        for text, fn, default in ((u"Отметить все", lambda s, e: set_all(True), False),
                                  (u"Снять все", lambda s, e: set_all(False), False),
                                  (u"Готово", ok, True)):
            b = Button()
            b.Content = text
            b.Padding = Thickness(14, 4, 14, 4)
            b.Margin = Thickness(8, 0, 0, 0)
            b.IsDefault = default
            b.Click += fn
            bt.Children.Add(b)
        cancel = Button()
        cancel.Content = u"Отмена"
        cancel.Padding = Thickness(14, 4, 14, 4)
        cancel.Margin = Thickness(8, 0, 0, 0)
        cancel.IsCancel = True
        bt.Children.Add(cancel)
        w.Content = dp
        w.ShowDialog()
        if not res.get("ok"):
            return
        shown = set(r_["sig"] for r_ in rows)
        hide = set(k for k in hide if k not in shown)       # строки вне списка (другой порог) — как были
        hide |= set(r_["sig"] for cb_, r_ in boxes if cb_.IsChecked)
        self.cfg["qty_hide"] = sorted(hide)
        self._qty_info()
        self._queue_check()

    def collect_sort_extras(self):
        for k, rb in getattr(self, "pos_radios", []):
            if rb.IsChecked:
                self.cfg.setdefault("pos", {})["mode"] = k
        try:
            v = float((self.tbQty.Text or u"").replace(u",", u"."))
            self.cfg["qty_min"] = v if v >= 0 else self.core.D.QTY_MIN
        except Exception:
            self.cfg["qty_min"] = self.core.D.QTY_MIN

    # ---------------- 5. материалы (покраска, крепёж, прочее) ----------------
    def _init_page4(self):
        try:
            self.mat_items = self.core.load_materials(self.cfg)
        except Exception as ex:
            self.mat_items = []
            self.status(u"Справочник материалов не прочитан: {0}".format(ex))
        self.mat_run = set(self.cfg.get("_mat_run") or [])
        root = self.page4
        top = DockPanel()
        top.Margin = Thickness(0, 0, 0, 8)
        btm = StackPanel()
        btm.Orientation = Orientation.Horizontal
        btm.VerticalAlignment = VerticalAlignment.Top
        DockPanel.SetDock(btm, Dock.Right)
        for txt, fn, tip in ((u"Отметить все", lambda s, e: self._mat_mark(True), None),
                             (u"Снять все", lambda s, e: self._mat_mark(False), None),
                             (u"Менеджер дополнительных материалов…", lambda s, e: self.open_mat_manager(),
                              u"Справочник строк (личный, для всех проектов): добавить, изменить, порядок, экспорт XLSX")):
            b = Button()
            b.Content = txt
            b.Padding = Thickness(10, 4, 10, 4)
            b.Margin = Thickness(6, 0, 0, 0)
            if tip:
                b.ToolTip = tip
            b.Click += fn
            btm.Children.Add(b)
        top.Children.Add(btm)
        hs = StackPanel()
        hs.Children.Add(tb(u"Что входит в комплект (отмечается при каждом запуске)", bold=True, size=14))
        hs.Children.Add(tb(u"Одна таблица на связку групп (группа без связки — своя), последней в связке: спецификация "
                           u"пустой категории «Комплекты мебели», вид — как у спецификации трубопроводов. Количество = "
                           u"база (поверхность / длина / площадь) × норма × слои × (1 + запас). Порядок строк — как в "
                           u"справочнике (менеджер: перетаскивание).", size=12, color=C_MUTED, wrap=True,
                           margin=Thickness(0, 2, 0, 0)))
        top.Children.Add(hs)
        root.Children.Add(self._dock(top, Dock.Top))
        pv = Border()
        pv.BorderBrush = brush("#B9CDE8")
        pv.Background = brush("#F3F8FE")
        pv.BorderThickness = Thickness(1)
        pv.CornerRadius = CornerRadius(6)
        pv.Padding = Thickness(10, 8, 10, 8)
        pv.Margin = Thickness(0, 10, 0, 0)
        pv.MaxHeight = 240
        sv = ScrollViewer()
        self.paintPrev = StackPanel()
        sv.Content = self.paintPrev
        pv.Child = sv
        root.Children.Add(self._dock(pv, Dock.Bottom))
        self.lbMat = ListBox()
        self.lbMat.HorizontalContentAlignment = HorizontalAlignment.Stretch
        self.lbMat.BorderBrush = C_LINE
        ScrollViewer.SetHorizontalScrollBarVisibility(self.lbMat, 0)
        root.Children.Add(self.lbMat)
        self.draw_mat_list()

    def _mat_mark(self, v):
        self.mat_run = set(m["id"] for m in self.mat_items) if v else set()
        self.collect_paint()
        self.draw_mat_list()
        self.draw_paint()

    def _mat_line(self, m):
        D = self.core.D
        bases = dict((k, t) for k, t, u in D.MAT_BASES)
        bunit = dict((k, u) for k, t, u in D.MAT_BASES).get(m["base"], u"")
        parts = [dict(D.MAT_KINDS).get(m["kind"], m["kind"]), m["unit"], bases.get(m["base"], m["base"])]
        if not (m["unit"] == bunit and m["norm"] == 1.0):
            parts.append(u"{0:g} {1}/{2}".format(m["norm"], m["unit"], bunit))
        if m["layers"] > 1:
            parts.append(u"слоёв {0}".format(m["layers"]))
        if m["reserve"]:
            parts.append(u"запас {0:g} %".format(m["reserve"]))
        parts.append(u"привязка: " + (u", ".join(m["bind"]) or u"все"))
        return u" · ".join(parts)

    def draw_mat_list(self):
        self.lbMat.Items.Clear()
        if not self.mat_items:
            self.lbMat.Items.Add(tb(u"Справочник пуст — откройте менеджер и добавьте строки.", color=C_MUTED))
            return
        for m in self.mat_items:
            li = ListBoxItem()
            li.Padding = Thickness(4, 3, 4, 3)
            g = Grid()
            for w in (GridLength(28), GridLength(1, GridUnitType.Star)):
                cd = ColumnDefinition()
                cd.Width = w
                g.ColumnDefinitions.Add(cd)
            cb = CheckBox()
            cb.IsChecked = m["id"] in self.mat_run
            cb.VerticalAlignment = VerticalAlignment.Center

            def tog(s, e, mid=m["id"]):
                if s.IsChecked:
                    self.mat_run.add(mid)
                else:
                    self.mat_run.discard(mid)
                self.collect_paint()
                self.draw_paint()
            cb.Click += tog
            g.Children.Add(cb)
            sp = StackPanel()
            head = WrapPanel()
            head.Children.Add(tb(u"{0}{1}".format(m["name"] or u"(без названия)", u"  " + m["mark"] if m["mark"] else u""),
                                 bold=True))
            if m.get("example"):
                eb = Border()
                eb.Background = C_ZERO
                eb.CornerRadius = CornerRadius(4)
                eb.Padding = Thickness(5, 0, 5, 1)
                eb.Margin = Thickness(8, 1, 0, 1)
                eb.Child = tb(self.core.D.EXAMPLE_NOTE, size=11, color=brush("#5C3900"))
                head.Children.Add(eb)
            sp.Children.Add(head)
            sp.Children.Add(tb(self._mat_line(m), size=11.5, color=C_MUTED, wrap=True))
            Grid.SetColumn(sp, 1)
            g.Children.Add(sp)
            li.Content = g
            self.lbMat.Items.Add(li)

    def collect_paint(self):
        """Галочки материалов — в cfg на время окна (не запоминаются между запусками)."""
        self.cfg["_mat_run"] = [m["id"] for m in self.mat_items if m["id"] in self.mat_run]
        self._spec_prev = None

    def draw_paint(self):
        out = self.paintPrev
        out.Children.Clear()
        out.Children.Add(tb(u"Что получится по связкам (по текущим группам систем)", bold=True,
                            margin=Thickness(0, 0, 0, 4)))
        if not self.mat_run:
            out.Children.Add(tb(u"Ничего не отмечено — таблиц материалов не будет.", size=12, color=C_MUTED))
            return
        try:
            res = self.core.mat_preview(self.infos, self.cfg, self.mat_items, self.mat_run)
        except Exception as ex:
            out.Children.Add(tb(u"Не посчиталось: {0}".format(ex), size=12, color=brush("#8B1E1E"), wrap=True))
            return
        if not res:
            out.Children.Add(tb(u"Нет труб / воздуховодов, подходящих под привязку отмеченных строк.", size=12,
                                color=C_MUTED))
            return
        for lab, rows in res:
            out.Children.Add(tb(u"{0} — «…{1} {0}»".format(lab, self.core.D.MAT_TITLE), bold=True, size=12,
                                color=brush("#174A87"), margin=Thickness(0, 4, 0, 1)))
            for r in rows:
                out.Children.Add(tb(u"{0}   {1:g} {2}   (база {3:g}, элементов {4}){5}".format(
                    r["name"], r["qty"], r["unit"], r["base"], r["n"], u"  · норма — пример" if r["example"] else u""),
                    size=12, wrap=True, margin=Thickness(12, 0, 0, 0)))

    def _bind_names(self):
        """Названия материалов и типов с вкладки 3 (трубы, воздуховоды и их детали) — для привязки строк."""
        out = []
        for k in ("pipe", "flex", "duct", "fduct"):
            o = self.cfg["order"].get(k) or {}
            for e in (o.get("materials") or []) + (o.get("types") or []):
                n = e.get("name")
                if n and n not in out:
                    out.append(n)
        return out

    def open_mat_manager(self):
        """Окно «Менеджер дополнительных материалов»: личный справочник (для всех проектов)."""
        items = [dict(m) for m in self.mat_items]
        mgr = MatManager(self, items)
        res = mgr.show()
        if res is None:
            return
        self.mat_items = res
        ids = set(m["id"] for m in res)
        self.mat_run = set(i for i in self.mat_run if i in ids)
        self.collect_paint()
        self.draw_mat_list()
        self.draw_paint()
        self.status(u"Справочник материалов сохранён: {0}".format(self.core.materials_path()))

    # ---------------- 6. листы ----------------
    def _init_page5(self):
        upd = lambda s, e: (self.collect_layout(), self.draw_layout_prev())
        self.num_radios = []
        for k, t, hint in self.core.D.SHEET_NUM_MODES:
            rb = RadioButton()
            rb.GroupName = u"sheetnum"
            rb.Margin = Thickness(0, 2, 0, 2)
            sp = StackPanel()
            sp.Orientation = Orientation.Horizontal
            sp.Children.Add(tb(t, bold=True))
            hint_tb = tb(u"   " + hint, size=12, color=C_MUTED)
            sp.Children.Add(hint_tb)
            rb.Content = sp
            rb.Tag = hint_tb
            rb.Click += upd
            self.numModes.Children.Add(rb)
            self.num_radios.append((k, rb))
        self._init_pos()
        for c in (self.rbGrpNew, self.rbGrpSame, self.cbTail, self.cbDelSheets, self.cbNumStamp, self.rbRow5,
                  self.rbRow8, self.rbRowCustom, self.rbRowTpl, self.cbCount, self.cbCountOwn, self.rbPosRenum,
                  self.rbPosKeep, self.cbSysBold, self.rbSysL, self.rbSysC, self.rbSysR, self.rbSysAbove,
                  self.rbSysBelow, self.cbTitleTpl, self.cbTitleBold, self.rbTitleL, self.rbTitleC, self.rbTitleR):
            c.Click += upd
        for t in (self.tbTailPct, self.tbGrpGap, self.tbSpecGap, self.tbMinRows, self.tbLeft, self.tbTop,
                  self.tbNumStart, self.tbNumPrefix, self.tbNumStampParam, self.tbNumSuffix, self.tbNumStep,
                  self.tbRowMm, self.tbTitleMm, self.tbSysRowMm, self.tbCountValue, self.tbSecFolder):
            t.LostFocus += upd
        # живая схема и пример номеров — при каждом изменении поля
        for t in (self.tbRowMm, self.tbTitleMm, self.tbSysRowMm, self.tbNumStart, self.tbNumPrefix,
                  self.tbNumSuffix, self.tbNumStep):
            t.TextChanged += lambda s, e: self._live_layout()
        self._init_rows()
        self.cbFolder.LostFocus += lambda s, e: self._folder_changed()
        self.cbFolder.SelectionChanged += lambda s, e: self._later(self._folder_changed)
        self._layout_fill()

    def _live_layout(self):
        if getattr(self, "_filling", False):
            return
        self.collect_layout()
        self.draw_layout_prev()

    def _init_pos(self):
        pos = self.cfg.setdefault("pos", {})
        cur = pos.get("mode", "group")
        if cur == "group_dot":
            cur = "group"
        if cur not in [m[0] for m in self.core.D.POS_MODES]:
            cur = "group"
        pos["mode"] = cur
        self.pos_radios = []
        for k, t, hint in self.core.D.POS_MODES:
            rb = RadioButton()
            rb.GroupName = u"posmode"
            rb.Margin = Thickness(0, 2, 0, 2)
            sp = StackPanel()
            sp.Orientation = Orientation.Horizontal
            sp.Children.Add(tb(t, bold=True))
            sp.Children.Add(tb(u"   " + hint, size=12, color=C_MUTED))
            rb.Content = sp
            rb.IsChecked = k == cur

            def set_mode(s, e, kk=k):
                self.cfg.setdefault("pos", {})["mode"] = kk
                self.draw_pos_preview()
            rb.Click += set_mode
            self.posModes.Children.Add(rb)
            self.pos_radios.append((k, rb))

    def _load_sheet_data(self, force=False):
        """Листы и коллекции читаются один раз — при первом открытии вкладки (и при смене коллекции)."""
        if self._sheet_snap is not None and not force:
            return
        lo = self._lo()
        folder = (lo.get("sheet_folder") or u"").strip() or u"ВК.С"
        try:
            if not force or self.cbFolder.Items.Count == 0:
                self._folders = self.core.L.list_sheet_folders()
                cur = self.cbFolder.Text
                self.cbFolder.Items.Clear()
                for n, c in self._folders:
                    self.cbFolder.Items.Add(n)
                self.cbFolder.Text = cur or folder
            self._sheet_snap = self.core.sheet_snapshot(folder)
            self._stamp = self.core.stamp_params(folder)
            self._frame = self.core.safe(lambda: self.core.sheet_frame(folder))
            if self._metrics is None and getattr(self.core.D, "SHEET_ESTIMATE", True):    # нужны только оценке
                self._metrics = self.core.safe(self.core.template_metrics, {}) or {}
        except Exception as ex:
            self._sheet_snap = {"mine": [], "others": {}}
            self._frame = None
            self._stamp = (u"", u"")
            self.status(u"Листы не прочитаны: {0}".format(ex))
        n = len(self._sheet_snap.get("mine") or [])
        cnt = dict(getattr(self, "_folders", None) or [])
        self.tFolderInfo.Text = (u"листов в «{0}»: {1}".format(folder, n) if n else
                                 u"«{0}» нет или пустая — при сборке будет создана, первый лист — Форма 5, "
                                 u"штамп пустой".format(folder))
        self.tFolderInfo.Foreground = C_MUTED if n else brush("#8A5A00")
        if not n and cnt:
            self.tFolderInfo.Text += u" (есть: " + u", ".join(list(cnt.keys())[:6]) + u")"

    def _folder_changed(self):
        lo = self._lo()
        v = (self.cbFolder.Text or u"").strip()
        if v and v != (lo.get("sheet_folder") or u""):
            lo["sheet_folder"] = v
            self._load_sheet_data(force=True)
            self.draw_layout_prev()

    def _lo(self):
        return self.core.layout_cfg(self.cfg)

    def _sheets_need(self, lo):
        """Сколько листов займёт сборка — всегда расчёт по модели (vks_core.estimate_*): строки спецификаций с
        переносом текста по ширине граф шаблонов, высоты из «Листов», раскладка по правилам vks_layout.
        -> (число, "est"), (0, "fail") или (0, "off") — оценка выключена (vks_defaults.SHEET_ESTIMATE). Строки
        считаются один раз на набор групп/скрытия/сортировки, поля «Листов» меняют только быструю раскладку."""
        if not getattr(self.core.D, "SHEET_ESTIMATE", True):
            return 0, "off"
        if self._sheet_snap is None:          # вкладка «Листы» ещё не открывалась — не считать при запуске окна
            return 0, "fail"
        try:
            key = self.core.layout_sig(self.cfg, rows_only=True)
            if self._est_rows is None or self._est_rows[0] != key:
                self._est_rows = (key, self.core.estimate_specs(self.infos, self.cfg, self.mat_items, self._metrics))
            return self.core.estimate_sheets(self._est_rows[1], self.cfg, self._frame), "est"
        except Exception as ex:
            self.status(u"Число листов не посчиталось: {0}".format(ex))
            return 0, "fail"

    def _layout_fill(self):
        self._filling = True
        try:
            lo = self._lo()
            f = lambda v: (u"%g" % float(v)).replace(u".", u",")
            self.rbGrpNew.IsChecked = bool(lo.get("group_new_sheet", True))
            self.rbGrpSame.IsChecked = not bool(lo.get("group_new_sheet", True))
            self.cbTail.IsChecked = bool(lo.get("tail_on", True))
            self.tbTailPct.Text = f(lo.get("tail_pct", 33))
            self.tbGrpGap.Text = f(lo.get("group_gap", 0))
            self.tbSpecGap.Text = f(lo.get("spec_gap", 0))
            self.tbMinRows.Text = u"%d" % int(lo.get("min_rows", 4))
            self.tbLeft.Text = f(lo.get("left", 20))
            self.tbTop.Text = f(lo.get("top", 37))
            self.cbDelSheets.IsChecked = bool(self.cfg.get("delete_empty_sheets"))
            mode = lo.get("num_mode", "keep")
            if mode == "from":
                mode = "prefix"
            for k, rb in self.num_radios:
                rb.IsChecked = (k == mode)
            self.tbNumStart.Text = u"%d" % int(lo.get("num_start", 1) or 1)
            self.tbNumStep.Text = u"%d" % int(lo.get("num_step", 1) or 1)
            self.tbNumPrefix.Text = lo.get("num_prefix") or u""
            self.cbNumStamp.IsChecked = bool(lo.get("num_stamp_on"))
            self.tbNumStampParam.Text = lo.get("num_stamp_param") or u""
            self.tbNumSuffix.Text = lo.get("num_suffix") or u""
            self.cbFolder.Text = lo.get("sheet_folder") or u"ВК.С"
            self.tbSecFolder.Text = lo.get("section_folder") or u"{секция}-Спецификации"
            rm = lo.get("row_mode", "5")
            self.rbRow5.IsChecked = rm == "5"
            self.rbRow8.IsChecked = rm == "8"
            self.rbRowCustom.IsChecked = rm == "custom"
            self.rbRowTpl.IsChecked = rm == "tpl"
            self.tbRowMm.Text = f(lo.get("row_mm", 5))
            self._rows_fill(lo, f)
            self.cbCount.IsChecked = bool(lo.get("count_on"))
            self.cbCountOwn.IsChecked = bool(lo.get("count_own"))
            self.tbCountValue.Text = u"%d" % int(lo.get("count_value") or 0) if lo.get("count_value") else u""
            self.rbPosKeep.IsChecked = lo.get("pos_update") == "keep"
            self.rbPosRenum.IsChecked = lo.get("pos_update") != "keep"
        finally:
            self._filling = False
        self.draw_layout_prev()

    def collect_layout(self):
        lo = self._lo()

        def num(t, key, lo_=0.0, hi=10000.0):
            try:
                lo[key] = max(lo_, min(hi, float((t.Text or u"").replace(u",", u"."))))
            except Exception:
                pass
        lo["group_new_sheet"] = bool(self.rbGrpNew.IsChecked)
        lo["tail_on"] = bool(self.cbTail.IsChecked)
        num(self.tbTailPct, "tail_pct", 1, 100)
        num(self.tbGrpGap, "group_gap", 0, 200)
        num(self.tbSpecGap, "spec_gap", 0, 200)
        num(self.tbMinRows, "min_rows", 1, 50)
        lo["min_rows"] = int(lo.get("min_rows", 4))
        num(self.tbLeft, "left", 0, 500)
        num(self.tbTop, "top", 0, 500)
        self.cfg["delete_empty_sheets"] = bool(self.cbDelSheets.IsChecked)
        for k, rb in self.num_radios:
            if rb.IsChecked:
                lo["num_mode"] = k
        num(self.tbNumStart, "num_start", 1, 100000)
        lo["num_start"] = int(lo.get("num_start", 1))
        num(self.tbNumStep, "num_step", 1, 1000)
        lo["num_step"] = int(lo.get("num_step", 1))
        lo["num_prefix"] = self.tbNumPrefix.Text or u""
        lo["num_stamp_on"] = bool(self.cbNumStamp.IsChecked)
        lo["num_stamp_param"] = (self.tbNumStampParam.Text or u"").strip()
        lo["num_suffix"] = self.tbNumSuffix.Text or u""
        for rb, k in ((self.rbRow5, "5"), (self.rbRow8, "8"), (self.rbRowCustom, "custom"), (self.rbRowTpl, "tpl")):
            if rb.IsChecked:
                lo["row_mode"] = k
        num(self.tbRowMm, "row_mm", 1, 100)
        num(self.tbSysRowMm, "sys_row_mm", 1, 100)
        self._rows_collect(lo, num)
        lo["count_on"] = bool(self.cbCount.IsChecked)
        lo["count_own"] = bool(self.cbCountOwn.IsChecked)
        try:
            lo["count_value"] = max(0, int((self.tbCountValue.Text or u"0").strip() or 0))
        except Exception:
            pass
        lo["pos_update"] = "keep" if self.rbPosKeep.IsChecked else "renum"
        lo["section_folder"] = (self.tbSecFolder.Text or u"").strip() or u"{секция}-Спецификации"

    # ---- блок «Строки таблицы»: название системы, название спецификации, обычная строка + схема в масштабе ----
    ROWS_SAMPLE = [
        (u"", u"Трубы стальные водогазопроводные оцинкованные Ø15×2,8", u"ГОСТ 3262-75*", u"", u"", u"м",
         u"24,5", u"1,28", u""),
        (u"", u"Трубы стальные водогазопроводные оцинкованные Ø20×2,8", u"ГОСТ 3262-75*", u"", u"", u"м",
         u"38,2", u"1,66", u""),
        (u"", u"Трубы стальные водогазопроводные оцинкованные Ø25×3,2", u"ГОСТ 3262-75*", u"", u"", u"м",
         u"12,0", u"2,39", u""),
        (u"", u"Трубы напорные из полипропилена PP-R PN20 Ø20×3,4", u"ГОСТ 32415-2013", u"", u"", u"м",
         u"56,0", u"0,17", u""),
        (u"", u"Трубы напорные из полипропилена PP-R PN20 Ø25×4,2", u"ГОСТ 32415-2013", u"", u"", u"м",
         u"41,3", u"0,27", u""),
    ]
    ROWS_ALIGN = ("left", "center", "left", "center", "center", "center", "center", "center", "center")
    ROWS_LINE_K = 1.45      # шаг строк текста к высоте шрифта (как EST_LINE_K)
    ROWS_PAD = 0.6          # поля ячейки по высоте: 2,5 × 1,45 + 0,6 = 4,23 мм — высота строки шаблона
    ROWS_CAP = 0.7          # высота прописной к кеглю шрифта на экране
    ROWS_BODY_FONT = 2.5    # шрифт тела на схеме (в Revit — из шаблона)

    def _row_fonts(self):
        return list(getattr(self.core.D, "ROW_FONTS", (1.8, 2.5, 3.5, 5.0, 7.0)))

    def _init_rows(self):
        for cb in (self.cbSysFont, self.cbTitleFont):
            cb.Items.Clear()
            for v in self._row_fonts():
                cb.Items.Add((u"%g" % v).replace(u".", u","))
            cb.SelectionChanged += lambda s, e: self._live_layout()
        self._sys_show = None           # показать строку системы на схеме: None — как у групп
        self._rdrag = None
        self._row_handles = []

        def show(s, e):
            self._sys_show = bool(self.cbSysShow.IsChecked)
            self.draw_rows_scheme()
        self.cbSysShow.Click += show
        self.cvRows.SizeChanged += lambda s, e: self.draw_rows_scheme()
        self.cvRows.MouseLeftButtonDown += self._rows_down
        self.cvRows.MouseMove += self._rows_move
        self.cvRows.MouseLeftButtonUp += self._rows_up

    def _font_index(self, v):
        fs = self._row_fonts()
        try:
            v = float(v)
        except Exception:
            v = fs[0]
        return min(range(len(fs)), key=lambda i: abs(fs[i] - v))

    def _sys_on(self):
        if self._sys_show is not None:
            return self._sys_show
        return any(g.get("sys_row") for g in self.cfg.get("groups") or [])

    def _rows_fill(self, lo, f):
        """Поля блока из настроек (вызов внутри _layout_fill, под _filling)."""
        self.tbSysRowMm.Text = f(lo.get("sys_row_mm", 8))
        self.cbSysFont.SelectedIndex = self._font_index(lo.get("sys_font", 3.5))
        self.cbSysBold.IsChecked = bool(lo.get("sys_bold"))
        al = lo.get("sys_align", "center")
        self.rbSysL.IsChecked = al == "left"
        self.rbSysC.IsChecked = al not in ("left", "right")
        self.rbSysR.IsChecked = al == "right"
        self.rbSysAbove.IsChecked = lo.get("sys_pos", "above") != "below"
        self.rbSysBelow.IsChecked = lo.get("sys_pos", "above") == "below"
        self.cbSysShow.IsChecked = self._sys_on()
        t = float(lo.get("title_mm") or 0)
        self.cbTitleTpl.IsChecked = t <= 0
        self.tbTitleMm.Text = f(t if t > 0 else (lo.get("title_mm_last") or 8))
        self.tbTitleMm.IsEnabled = t > 0
        self.cbTitleFont.SelectedIndex = self._font_index(lo.get("title_font", 5.0))
        self.cbTitleBold.IsChecked = bool(lo.get("title_bold", True))
        al = lo.get("title_align", "center")
        self.rbTitleL.IsChecked = al == "left"
        self.rbTitleC.IsChecked = al not in ("left", "right")
        self.rbTitleR.IsChecked = al == "right"

    def _rows_collect(self, lo, num):
        """Настройки из полей блока (вызов внутри collect_layout)."""
        fs = self._row_fonts()
        i = self.cbSysFont.SelectedIndex
        if 0 <= i < len(fs):
            lo["sys_font"] = fs[i]
        lo["sys_bold"] = bool(self.cbSysBold.IsChecked)
        lo["sys_align"] = "left" if self.rbSysL.IsChecked else ("right" if self.rbSysR.IsChecked else "center")
        lo["sys_pos"] = "below" if self.rbSysBelow.IsChecked else "above"
        i = self.cbTitleFont.SelectedIndex
        if 0 <= i < len(fs):
            lo["title_font"] = fs[i]
        lo["title_bold"] = bool(self.cbTitleBold.IsChecked)
        lo["title_align"] = "left" if self.rbTitleL.IsChecked else ("right" if self.rbTitleR.IsChecked else "center")
        try:
            v = max(1.0, min(100.0, float((self.tbTitleMm.Text or u"").replace(u",", u"."))))
            lo["title_mm_last"] = v
        except Exception:
            v = float(lo.get("title_mm_last") or 8)
        lo["title_mm"] = 0.0 if self.cbTitleTpl.IsChecked else v
        self.tbTitleMm.IsEnabled = not self.cbTitleTpl.IsChecked
        lo["head_mm"] = 0.0             # шапки граф нет (решение 02.11.2026)

    def _rows_text(self, x, y, w_mm, h_mm, text, font, bold, al, s):
        """Текст ячейки схемы с переносом по словам; -> число строк текста."""
        cv = self.cvRows
        lh = font * self.ROWS_LINE_K * s
        t = TextBlock()
        t.Text = text or u""
        t.FontFamily = FontFamily(u"GOST Common, ISOCPEUR, Arial Narrow, Arial")
        t.FontSize = max(1.0, font / self.ROWS_CAP * s)
        t.FontWeight = FontWeights.Bold if bold else FontWeights.Normal
        t.Foreground = pbrush("#1A1F26")
        t.TextWrapping = TextWrapping.Wrap
        t.TextAlignment = (TextAlignment.Left if al == "left" else
                           (TextAlignment.Right if al == "right" else TextAlignment.Center))
        t.LineStackingStrategy = LineStackingStrategy.BlockLineHeight
        t.LineHeight = max(1.0, lh)
        t.VerticalAlignment = VerticalAlignment.Center
        inner = max(1.0, (w_mm - 2.0) * s)
        t.Width = inner
        n = 1
        if text:
            t.Measure(Size(inner, float("inf")))
            n = max(1, int(round(t.DesiredSize.Height / max(1.0, lh))))
        b = Border()
        b.Width = max(1.0, w_mm * s)
        b.Height = max(1.0, h_mm * s)
        b.Padding = Thickness(s, 0, s, 0)
        b.ClipToBounds = True
        b.Child = t
        Canvas.SetLeft(b, x)
        Canvas.SetTop(b, y)
        cv.Children.Add(b)
        return n

    def _rows_line(self, x1, y1, x2, y2, color, th=1.0):
        ln = Line()
        ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
        ln.Stroke = pbrush(color)
        ln.StrokeThickness = th
        self.cvRows.Children.Add(ln)

    def _rows_label(self, text, x, y, w, al, size=10.0):
        t = TextBlock()
        t.Text = text
        t.FontSize = size
        t.Foreground = pbrush("#1F5FAD")
        t.Width = max(1.0, w)
        t.TextAlignment = TextAlignment.Right if al == "right" else TextAlignment.Center
        Canvas.SetLeft(t, x)
        Canvas.SetTop(t, y)
        self.cvRows.Children.Add(t)

    def draw_rows_scheme(self):
        """Схема строк в масштабе, как на листе: [название системы] → название спецификации (или наоборот) →
        строка группирования → 5 обычных строк; графы — COLUMN_WIDTHS_MM; слева и сверху размеры, мм.
        «Как в шаблоне» — значение шаблона «О_…», если он уже прочитан, иначе 8 / 4,23 мм."""
        cv = self.cvRows
        cv.Children.Clear()
        lo = self._lo()
        fmt = lambda v: (u"%.2f" % v).rstrip(u"0").rstrip(u".").replace(u".", u",")
        widths = [float(w) for w in (getattr(self.core.D, "COLUMN_WIDTHS_MM", None) or
                                     [20, 130, 60, 35, 45, 20, 20, 25, 40])]
        tot = sum(widths)
        GL, GT, GR, GB = 56.0, 24.0, 8.0, 6.0
        W = cv.ActualWidth if cv.ActualWidth and cv.ActualWidth > 100 else 640.0
        s = max(0.8, min(4.0, (W - GL - GR) / tot))
        mt = self._metrics or {}
        m = mt.get("pipe") or (list(mt.values())[0] if mt else {})
        hdr = list(m.get("hdr") or [])
        t_title = hdr[0] if hdr else 8.0
        t_row = m.get("row") or 4.23
        groups = self.cfg.get("groups") or []
        g0 = next((g for g in groups if g.get("sys_row")), groups[0] if groups else {})
        sys_text = (g0.get("sys_text") or u"").strip() if g0 else u""
        if not sys_text and g0:
            sys_text = self.core.safe(lambda: self.core.group_sys_title(g0)) or u""
        sys_text = sys_text or u"Система В1. Водопровод хозяйственно-питьевой"
        grp_text = (groups[0].get("name") if groups else None) or u"В1"
        title_mm = float(lo.get("title_mm") or 0)
        rm = self.core.row_mm(lo)
        bh = rm or t_row
        rows = []
        r_sys = {"id": "sys", "name": u"Название системы", "h": float(lo.get("sys_row_mm") or 8), "tpl": False,
                 "text": sys_text, "font": float(lo.get("sys_font") or 3.5), "bold": bool(lo.get("sys_bold")),
                 "al": lo.get("sys_align", "center"), "hdr": True}
        r_title = {"id": "title", "name": u"Название спецификации", "h": title_mm if title_mm > 0 else t_title,
                   "tpl": title_mm <= 0, "text": u"Трубопроводы", "font": float(lo.get("title_font") or 5),
                   "bold": bool(lo.get("title_bold", True)), "al": lo.get("title_align", "center"), "hdr": True}
        if self._sys_on():
            rows += [r_sys, r_title] if lo.get("sys_pos", "above") != "below" else [r_title, r_sys]
        else:
            rows.append(r_title)
        rows.append({"id": "body", "name": u"Строка группирования", "h": bh, "tpl": rm is None, "text": grp_text,
                     "font": self.ROWS_BODY_FONT, "bold": False, "al": "left", "hdr": False, "label": True})
        for i, d in enumerate(self.ROWS_SAMPLE):
            rows.append({"id": "body", "name": u"Обычная строка", "h": bh, "tpl": rm is None, "cells": d,
                         "font": self.ROWS_BODY_FONT, "bold": False, "hdr": False, "label": i == 0})
        total = sum(r["h"] for r in rows)
        need_h = GT + total * s + GB
        if abs((cv.Height or 0) - need_h) > 0.5:
            cv.Height = need_h
        xs = [GL]
        for w in widths:
            xs.append(xs[-1] + w * s)
        x_end = xs[-1]
        # размеры граф сверху
        yd = GT - 8
        self._rows_line(GL, yd, x_end, yd, "#1F5FAD")
        for x in xs:
            self._rows_line(x, yd - 4, x, GT - 1, "#1F5FAD")
        for i, w in enumerate(widths):
            self._rows_label(fmt(w), xs[i], yd - 15, w * s, "center", 9.5 if w * s < 28 else 10.5)
        y = GT
        over = {}
        self._row_handles = []
        thick = 1.4
        for r in rows:
            rh = r["h"] * s
            if "cells" in r:
                cells = [(xs[i], widths[i], r["cells"][i], self.ROWS_ALIGN[i]) for i in range(len(widths))
                         if i < len(r["cells"])]
            else:
                cells = [(GL, tot, r["text"], r["al"])]
            for cx, cw, ct, cal in cells:
                n = self._rows_text(cx, y, cw, r["h"], ct, r["font"], r["bold"], cal, s)
                need = n * r["font"] * self.ROWS_LINE_K + self.ROWS_PAD
                if ct and need > r["h"] + 0.01:
                    o = over.setdefault(r["name"], [r["h"], 0.0])
                    o[1] = max(o[1], need)
                    mk = Rectangle()
                    mk.Width = mk.Height = 5
                    mk.Fill = pbrush("#C2410C")
                    Canvas.SetLeft(mk, cx + cw * s - 5)
                    Canvas.SetTop(mk, y)
                    cv.Children.Add(mk)
            if "cells" in r:
                for x in xs[1:-1]:
                    self._rows_line(x, y, x, y + rh, "#1A1F26", thick)
            self._rows_line(GL, y + rh, x_end, y + rh, "#1A1F26" if r["hdr"] else "#4A535E",
                            thick if r["hdr"] else 1.0)
            # размер строки слева
            xd = GL - 10
            self._rows_line(xd, y, xd, y + rh, "#1F5FAD")
            self._rows_line(xd - 4, y, GL - 1, y, "#1F5FAD")
            if (r["hdr"] or r.get("label")) and rh >= 6:
                lab = (u"шабл. " + fmt(r["h"])) if r["tpl"] else fmt(r["h"])
                self._rows_label(lab, 0, y + rh / 2.0 - 7, xd - 3, "right", 9.0 if (r["tpl"] or rh < 9) else 10.5)
            y += rh
            self._row_handles.append((y, "body" if r["id"] == "body" else r["id"], s))
        self._rows_line(GL - 14, y, GL - 1, y, "#1F5FAD")
        frame = Rectangle()
        frame.Width = max(1.0, x_end - GL)
        frame.Height = max(1.0, y - GT)
        frame.Stroke = pbrush("#1A1F26")
        frame.StrokeThickness = thick
        Canvas.SetLeft(frame, GL)
        Canvas.SetTop(frame, GT)
        cv.Children.Add(frame)
        self._rows_x = (GL, x_end)
        hs = sum(r["h"] for r in rows if r["hdr"])
        seg = float(getattr(self.core.L, "SEGMENT_FRAME_MM", 6.2))
        part = hs + 6 * bh + seg
        self.tRowsSum.Text = (u"«Заголовок» {0} мм · строка {1} мм · часть таблицы из 6 строк на листе — {2} мм "
                              u"(с рамкой {3})".format(fmt(hs), fmt(bh), fmt(part), fmt(seg)))
        msgs = [u"{0}: текст не помещается в {1} мм — нужно не меньше {2} мм.".format(
            k, fmt(v[0]), fmt(math.ceil(v[1] * 10) / 10.0)) for k, v in sorted(over.items())]
        self.tRowsWarn.Text = u"\n".join(msgs)
        self.bdRowsWarn.Visibility = Visibility.Visible if msgs else Visibility.Collapsed

    def _rows_hit(self, p):
        x0, x1 = getattr(self, "_rows_x", (0, 0))
        if p.X < x0 - 2 or p.X > x1 + 2:
            return None
        for yb, rid, s in self._row_handles:
            if abs(p.Y - yb) <= 4:
                return yb, rid, s
        return None

    def _rows_down(self, sender, e):
        p = e.GetPosition(self.cvRows)
        h = self._rows_hit(p)
        if h is None:
            return
        lo = self._lo()
        rid = h[1]
        if rid == "sys":
            v = float(lo.get("sys_row_mm") or 8)
        elif rid == "title":
            v = float(lo.get("title_mm") or 0) or float(lo.get("title_mm_last") or 8)
        else:
            v = self.core.row_mm(lo) or 5.0
        self._rdrag = {"id": rid, "y": p.Y, "v": v, "s": h[2]}
        self.cvRows.CaptureMouse()
        e.Handled = True

    def _rows_move(self, sender, e):
        p = e.GetPosition(self.cvRows)
        d = self._rdrag
        if d is None:
            self.cvRows.Cursor = Cursors.SizeNS if self._rows_hit(p) else None
            return
        v = max(1.0, min(60.0, round((d["v"] + (p.Y - d["y"]) / d["s"]) * 2) / 2.0))
        lo = self._lo()
        f = lambda x: (u"%g" % x).replace(u".", u",")
        self._filling = True
        try:
            if d["id"] == "sys":
                lo["sys_row_mm"] = v
                self.tbSysRowMm.Text = f(v)
            elif d["id"] == "title":
                lo["title_mm"] = v
                lo["title_mm_last"] = v
                self.cbTitleTpl.IsChecked = False
                self.tbTitleMm.IsEnabled = True
                self.tbTitleMm.Text = f(v)
            else:
                lo["row_mode"] = "custom"
                lo["row_mm"] = v
                self.rbRowCustom.IsChecked = True
                self.tbRowMm.IsEnabled = True
                self.tbRowMm.Text = f(v)
        finally:
            self._filling = False
        self.draw_rows_scheme()

    def _rows_up(self, sender, e):
        if self._rdrag is None:
            return
        self._rdrag = None
        self.cvRows.ReleaseMouseCapture()
        self.collect_layout()
        self.draw_layout_prev()

    def draw_layout_prev(self):
        lo = self._lo()
        self.cbTail.IsEnabled = bool(lo.get("group_new_sheet", True))
        self.tbTailPct.IsEnabled = self.cbTail.IsEnabled
        self.tbRowMm.IsEnabled = lo.get("row_mode") == "custom"
        self.draw_rows_scheme()
        gap = u"%g мм" % float(lo.get("group_gap", 0))
        sg = float(lo.get("spec_gap", 0))
        parts = []
        if lo.get("group_new_sheet", True):
            parts.append(u"В1 — с листа 1, Т3 — с нового листа, К1 — с нового листа.")
            if lo.get("tail_on", True):
                parts.append(u"Если от В1 на новый лист перенеслись только несколько строк (до {0:g} % листа), Т3 "
                             u"начнётся на этом же листе через {1}.".format(float(lo.get("tail_pct", 33)), gap))
            else:
                parts.append(u"Даже если от прошлой группы на листе пара строк — следующая группа всё равно с нового листа.")
        else:
            parts.append(u"В1, Т3, К1 — подряд, между группами {0}; новый лист — только когда не влезает.".format(gap))
        parts.append(u"Внутри группы спецификации " + (u"встык." if sg <= 0 else u"через {0:g} мм.".format(sg)))
        links = set(g.get("link") for g in self.cfg.get("groups") or [] if g.get("link"))
        if links:
            parts.append(u"Связанные группы ({0} связки) идут подряд: следующая продолжает лист.".format(len(links)))
        # нумерация листов
        mode = lo.get("num_mode", "keep")
        folder = lo.get("sheet_folder") or u"ВК.С"
        snap = self._sheet_snap
        have = len((snap or {}).get("mine") or [])
        need, how = self._sheets_need(lo)
        approx = u"≈" if how == "est" else u""
        keep_ok = need <= have or not need
        for k, rb in self.num_radios:
            if k == "keep":
                rb.IsEnabled = keep_ok
                rb.Tag.Text = (u"   номера листов комплекта не трогать; новые — следующим номером" if keep_ok else
                               u"   нужно {0}{1}, есть {2} — недоступно: новые листы нужно нумеровать".format(
                                   approx, need, have))
        if not keep_ok and mode == "keep":
            mode = "continue"
            lo["num_mode"] = mode
            for k, rb in self.num_radios:
                rb.IsChecked = (k == mode)
        self.wpNumFields.IsEnabled = mode == "prefix"
        self.wpNumFields.Opacity = 1.0 if mode == "prefix" else 0.45
        self.tbNumStampParam.IsEnabled = bool(lo.get("num_stamp_on"))
        want, busy, msg = ([], [], u"")
        count = max(have, need, 3) if mode != "keep" else have
        if snap is not None:
            try:
                want, busy, msg = self.core.plan_sheet_numbers(lo, snap, count)
            except Exception:
                want, busy, msg = [], [], u""
        self.wpNumExample.Children.Clear()
        if mode != "keep" and want:
            self.wpNumExample.Children.Add(tb(u"Пример: ", size=12, color=C_MUTED))
            busy_n = set(b.split(u" («")[0] for b in busy)
            for n_ in want[:8]:
                self.wpNumExample.Children.Add(self._num_chip(n_, False))
            for b in sorted(busy_n)[:4]:
                self.wpNumExample.Children.Add(self._num_chip(b, True))
            if len(want) > 8:
                self.wpNumExample.Children.Add(tb(u"…", color=C_MUTED))
        if mode == "keep":
            parts.append(u"Номера листов «{0}» не меняются, новые — следующими.".format(folder))
        elif want:
            parts.append(u"Листы «{0}»: {1}{2}".format(folder, u", ".join(want[:4]), u" …" if len(want) > 4 else u"."))
        if lo.get("num_stamp_on") and mode != "keep":
            parts.append(u"В «{0}» — 1, 2, 3 ….".format(lo.get("num_stamp_param") or u"?"))
        # число листов в штамп
        flag, pname = getattr(self, "_stamp", (u"", u"")) or (u"", u"")
        on = bool(lo.get("count_on"))
        self.cbCountOwn.IsEnabled = on
        self.tbCountValue.IsEnabled = on and bool(lo.get("count_own"))
        if snap is None:
            self.tCountParams.Text = u""
        elif pname:
            self.tCountParams.Text = u"Параметры штампа: число — «{0}»{1}.".format(
                pname, u", флаг Да/Нет — «{0}»".format(flag) if flag else u" (флага Да/Нет нет — пишется только число)")
            self.tCountParams.Foreground = C_MUTED
            self.tCountParams.Background = None
        else:
            self.tCountParams.Text = (u"У листа и штампа комплекта не найден параметр числа листов (со словом «лист» в "
                                      u"имени) — число не запишется.")
            self.tCountParams.Foreground = brush("#5C3900")
            self.tCountParams.Background = C_ZERO
        self.tCountAuto.Text = (u"по раскладке: {0}".format(self._need_text(need, how)) if need else
                                u"по раскладке — запишется после сборки" if how == "off" else
                                u"по раскладке — число не посчиталось (см. строку состояния)")
        if on:
            parts.append(u"В штамп — число листов комплекта: {0}.".format(
                int(lo.get("count_value") or 0) if lo.get("count_own") and lo.get("count_value") else
                (u"по раскладке" + (u" ({0}{1})".format(approx, need) if need else u""))))
        if need:
            parts.insert(0, u"Листов: {0}.".format(self._need_text(need, how)))
        self.tLayPrev.Text = u"Как будет: " + u" ".join(parts)
        bad = bool(busy or msg)
        for t in (self.tbNumStart, self.tbNumPrefix, self.tbNumSuffix):
            t.ClearValue(TextBox.BackgroundProperty)
            t.ClearValue(TextBox.BorderBrushProperty)
        if bad and mode != "keep":
            if mode == "prefix":
                for t in (self.tbNumStart, self.tbNumPrefix, self.tbNumSuffix):
                    t.Background = C_WARN_BG
                    t.BorderBrush = C_WARN_LINE
            txt = msg or (u"Номера заняты другими листами проекта: {0}{1}. Они будут пропущены — листы комплекта "
                          u"получат следующие свободные номера. Чтобы номера шли подряд, измените начальный номер, "
                          u"префикс или суффикс.").format(u", ".join(busy[:6]), u" …" if len(busy) > 6 else u"")
            self.tNumWarn.Text = txt
            self.bdNumWarn.Visibility = Visibility.Visible
        else:
            self.bdNumWarn.Visibility = Visibility.Collapsed
        if getattr(self, "pos_radios", None):
            mode_p = (self.cfg.get("pos") or {}).get("mode", "group")
            for k, rb in self.pos_radios:
                rb.IsChecked = (k == mode_p)

    @staticmethod
    def _need_text(need, how):
        return u"≈ {0} (расчёт по модели: строки, переносы, высоты, правила раскладки)".format(need)

    def _num_chip(self, text, busy):
        b = Border()
        b.CornerRadius = CornerRadius(4)
        b.Padding = Thickness(6, 0, 6, 1)
        b.Margin = Thickness(0, 0, 4, 0)
        b.BorderThickness = Thickness(1)
        b.Background = C_WARN_BG if busy else brush("#EEF4FC")
        b.BorderBrush = C_WARN_LINE if busy else brush("#B9CDE8")
        b.Child = tb(text, size=12, color=brush("#8B1E1E") if busy else brush("#174A87"))
        b.ToolTip = u"занят другим листом — будет пропущен" if busy else None
        return b

    # ---------------- шаблоны настроек ----------------
    def _init_presets(self):
        self.presets = []
        self.btnPresetApply.Click += self.on_preset_apply
        self.btnPresetSave.Click += self.on_preset_save
        self.btnPresetMenu.Click += self.on_preset_menu
        self.cbPreset.ToolTip = (u"Шаблон — окна настроек: группы систем, что скрыто, порядок материалов и типов, "
                                 u"сортировка, нумерация, порог количества, листы. Справочник материалов — личный, "
                                 u"не в шаблоне. ★ — подставляется в новых проектах.")
        self.fill_presets(select=self.cfg.get("_preset"))
        if self.cfg.get("_preset_auto") and self.cfg.get("_preset"):
            self.status(u"Проект без своих настроек — подставлен шаблон «{0}»".format(self.cfg["_preset"]))
        self._title()

    def status(self, text):
        self.tStatus.Text = text or u""
        self.tStatus.ToolTip = text or None

    def _title(self):
        t = u"Менеджер спецификаций: настройка"
        if self.cfg.get("_preset"):
            t += u" · шаблон «{0}»".format(self.cfg["_preset"])
        self.win.Title = t

    def fill_presets(self, select=None):
        try:
            self.presets = self.core.list_presets()
        except Exception:
            self.presets = []
        self.cbPreset.Items.Clear()
        self.cbPreset.Items.Add(u"— настройки этого проекта —")
        idx = 0
        for i, (n, path, fn) in enumerate(self.presets):
            self.cbPreset.Items.Add(n + (u"  ★" if fn else u""))
            if select and n == select:
                idx = i + 1
        self.cbPreset.SelectedIndex = idx

    def _sel_preset(self):
        i = self.cbPreset.SelectedIndex
        return self.presets[i - 1] if 1 <= i <= len(self.presets) else None

    def _grab_ui(self):
        """Всё, что сейчас в окнах, — в self.cfg (перед сохранением шаблона)."""
        self.collect_hidden()
        self.collect_sort_extras()
        self.collect_paint()
        self.collect_layout()

    def on_preset_apply(self, s, e):
        p = self._sel_preset()
        old_sys = set(x for g in self.cfg.get("groups") or [] for x in g.get("systems") or [])
        try:
            if p is None:
                new = self.core.full_cfg(self.core.load_cfg(), self.systems, self.infos)
                new.pop("_preset", None)
                label = u"Вернул сохранённые настройки этого проекта"
                miss = []
            else:
                pr = self.core.load_preset(p[1])
                want = set(x for g in (pr.get("settings") or {}).get("groups") or [] for x in g.get("systems") or [])
                have = set(x[0] for x in self.systems)
                miss = sorted(want - have)
                new = self.core.apply_preset(self.cfg, pr, self.systems, self.infos)
                label = u"Шаблон «{0}» применён".format(p[0])
                extra = sorted(have - want)
                if extra:
                    label += u"; новые системы — по умолчанию: " + u", ".join(extra[:6]) + (u"…" if len(extra) > 6 else u"")
        except Exception as ex:
            MessageBox.Show(self.win, u"Не удалось применить шаблон:\n{0}".format(ex), u"Шаблон", MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return
        if miss:
            label += u"; нет в проекте: " + u", ".join(miss[:6]) + (u"…" if len(miss) > 6 else u"")
        self.reload_cfg(new)
        self.status(label)

    def reload_cfg(self, new):
        keep_run = self.cfg.get("_mat_run")
        self.cfg = copy.deepcopy(new)
        if "_mat_run" not in self.cfg and keep_run is not None:
            self.cfg["_mat_run"] = list(keep_run)
        self.sel_groups = set()
        self.sel_chips = set()
        self.tree_nodes = []
        self._sheet_snap = None
        self.draw_systems()
        self.draw_groups()
        self._build_order_tabs()
        mode = self.core.pos_mode(self.cfg)
        for k, rb in self.pos_radios:
            rb.IsChecked = (k == mode)
        self.tbQty.Text = (u"%g" % float(self.cfg.get("qty_min", self.core.D.QTY_MIN))).replace(u".", u",")
        self.cbDelSheets.IsChecked = bool(self.cfg.get("delete_empty_sheets"))
        self._spec_prev = None
        self.cbOrderOn.IsChecked = bool(self.cfg.get("order_on", True))
        self._order_info()
        self._fill_rank_params()
        self.on_sort_for(None, None)
        self.mat_run = set(self.cfg.get("_mat_run") or [])
        self.draw_mat_list()
        self._layout_fill()
        self._qty_info()
        self._title()
        self.go(self.page)

    def ask_name(self, default, for_new):
        w = Window()
        T.dress(w)
        w.Title = u"Сохранить шаблон"
        w.Width = 440
        w.SizeToContent = SizeToContent.Height
        w.ResizeMode = ResizeMode.NoResize
        w.WindowStartupLocation = WindowStartupLocation.CenterOwner
        w.Owner = self.win
        w.FontFamily = self.win.FontFamily
        w.FontSize = 13
        sp = StackPanel()
        sp.Margin = Thickness(16, 14, 16, 14)
        sp.Children.Add(tb(u"Имя шаблона (например, «Типовой жилой 9 эт.»)", color=brush("#4A5361")))
        t = TextBox()
        t.Text = default or u""
        t.Padding = Thickness(4, 3, 4, 3)
        t.Margin = Thickness(0, 4, 0, 8)
        sp.Children.Add(t)
        cb = CheckBox()
        cb.Content = u"подставлять в новых проектах (где кнопку ещё не запускали)"
        cb.IsChecked = bool(for_new)
        sp.Children.Add(cb)
        sp.Children.Add(tb(u"В шаблон попадают окна настроек: группы систем, что скрыто, порядок материалов и типов, "
                           u"сортировка, нумерация, порог количества, листы (справочник материалов — личный, отдельно).",
                           size=11, color=C_MUTED, wrap=True,
                           margin=Thickness(0, 8, 0, 0)))
        bt = StackPanel()
        bt.Orientation = Orientation.Horizontal
        bt.HorizontalAlignment = HorizontalAlignment.Right
        bt.Margin = Thickness(0, 12, 0, 0)
        ok = Button()
        ok.Content = u"Сохранить"
        ok.Padding = Thickness(14, 4, 14, 4)
        ok.Margin = Thickness(0, 0, 8, 0)
        ok.IsDefault = True
        cancel = Button()
        cancel.Content = u"Отмена"
        cancel.Padding = Thickness(14, 4, 14, 4)
        cancel.IsCancel = True
        bt.Children.Add(ok)
        bt.Children.Add(cancel)
        sp.Children.Add(bt)
        w.Content = sp
        res = {}

        def do_ok(s, e):
            res["name"] = (t.Text or u"").strip()
            res["for_new"] = bool(cb.IsChecked)
            w.DialogResult = True
        ok.Click += do_ok
        w.Loaded += lambda s, e: (t.Focus(), t.SelectAll())
        w.ShowDialog()
        return (res.get("name"), res.get("for_new")) if res.get("name") else (None, None)

    def on_preset_save(self, s, e):
        p = self._sel_preset()
        default = p[0] if p else (self.cfg.get("_preset") or u"")
        if not default:
            try:
                default = self.core.doc.Title
            except Exception:
                default = u"Шаблон спецификаций"
        name, for_new = self.ask_name(default, p[2] if p else False)
        if not name:
            return
        if any(n == name for n, path, fn in self.presets):
            r = MessageBox.Show(self.win, u"Шаблон «{0}» уже есть. Заменить?".format(name), u"Сохранить шаблон",
                                MessageBoxButton.YesNo, MessageBoxImage.Question)
            if r != MessageBoxResult.Yes:
                return
        self._grab_ui()
        try:
            self.core.save_preset(self.cfg, name, for_new)
        except Exception as ex:
            MessageBox.Show(self.win, u"Не удалось сохранить:\n{0}".format(ex), u"Шаблон", MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return
        self.cfg["_preset"] = name
        self.fill_presets(select=name)
        self._title()
        self.status(u"Шаблон «{0}» сохранён{1}".format(name, u" и подставляется в новых проектах" if for_new else u""))

    def on_preset_menu(self, s, e):
        p = self._sel_preset()
        cm = T.menu(ContextMenu())

        def item(text, fn, enabled=True, checked=None):
            mi = MenuItem()
            mi.Header = text
            mi.IsEnabled = enabled
            if checked is not None:
                mi.IsCheckable = True
                mi.IsChecked = checked
            mi.Click += lambda a, b: fn()
            cm.Items.Add(mi)
        item(u"Экспорт выбранного шаблона в файл…", self.preset_export, p is not None)
        item(u"Импорт шаблона из файла…", self.preset_import)
        cm.Items.Add(Separator())
        item(u"Подставлять в новых проектах  ★", self.preset_toggle_new, p is not None, bool(p and p[2]))
        item(u"Удалить выбранный шаблон", self.preset_delete, p is not None)
        cm.Items.Add(Separator())
        item(u"Открыть папку шаблонов", self.preset_folder)
        cm.PlacementTarget = self.btnPresetMenu
        cm.IsOpen = True

    def preset_export(self):
        p = self._sel_preset()
        if p is None:
            return
        from Microsoft.Win32 import SaveFileDialog
        d = SaveFileDialog()
        d.Title = u"Экспорт шаблона спецификаций"
        d.Filter = u"Шаблон спецификаций (*.json)|*.json"
        d.FileName = p[0] + u".json"
        if d.ShowDialog(self.win):
            self.core.export_preset(p[0], d.FileName)
            self.status(u"Шаблон «{0}» сохранён в файл {1}".format(p[0], d.FileName))

    def preset_import(self):
        from Microsoft.Win32 import OpenFileDialog
        d = OpenFileDialog()
        d.Title = u"Импорт шаблона спецификаций"
        d.Filter = u"Шаблон спецификаций (*.json)|*.json|Все файлы|*.*"
        if d.ShowDialog(self.win):
            try:
                name = self.core.import_preset(d.FileName)
            except Exception as ex:
                MessageBox.Show(self.win, u"Это не шаблон спецификаций:\n{0}".format(ex), u"Импорт", MessageBoxButton.OK,
                                MessageBoxImage.Warning)
                return
            self.fill_presets(select=name)
            self.status(u"Импортирован шаблон «{0}» — нажмите «Применить»".format(name))

    def preset_toggle_new(self):
        p = self._sel_preset()
        if p is None:
            return
        self.core.set_preset_for_new(None if p[2] else p[0])
        self.fill_presets(select=p[0])
        self.status(u"«{0}» {1}".format(p[0], u"больше не подставляется в новых проектах" if p[2]
                                         else u"будет подставляться в новых проектах"))

    def preset_delete(self):
        p = self._sel_preset()
        if p is None:
            return
        r = MessageBox.Show(self.win, u"Удалить шаблон «{0}»?".format(p[0]), u"Шаблон", MessageBoxButton.YesNo,
                            MessageBoxImage.Question)
        if r == MessageBoxResult.Yes:
            self.core.delete_preset(p[0])
            self.fill_presets()
            self.status(u"Шаблон «{0}» удалён".format(p[0]))

    def preset_folder(self):
        try:
            from System.Diagnostics import Process
            Process.Start(u"explorer.exe", u'"{0}"'.format(self.core.presets_dir()))
        except Exception:
            pass

    # ---------------- запуск / снимки ----------------
    def show(self, owner_handle=None):
        if owner_handle:
            try:
                from System.Windows.Interop import WindowInteropHelper
                WindowInteropHelper(self.win).Owner = owner_handle
            except Exception:
                pass
        self.win.ShowDialog()
        return self.result

    def snapshot(self, path, page, w=1180, h=740):
        """PNG страницы без показа окна (для проверки)."""
        from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
        from System.Windows.Media import PixelFormats
        from System.IO import FileStream, FileMode
        self.go(page)
        root = self.root
        if self.win.Content is root:
            self.win.Content = None
        root.Measure(Size(w, h))
        root.Arrange(Rect(0, 0, w, h))
        root.UpdateLayout()
        bmp = RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32)
        bmp.Render(root)
        enc = PngBitmapEncoder()
        enc.Frames.Add(BitmapFrame.Create(bmp))
        fs = FileStream(path, FileMode.Create)
        try:
            enc.Save(fs)
        finally:
            fs.Close()
        return path


class MatManager(object):
    """Окно «Менеджер дополнительных материалов»: строки справочника, порядок перетаскиванием, правка, стандартный
    набор, экспорт XLSX. Сохраняется в личный файл только по «Сохранить»."""

    def __init__(self, wiz, items):
        self.wiz = wiz
        self.core = wiz.core
        self.D = wiz.core.D
        self.items = [self.core.mat_norm(m) for m in items]
        self.sel = 0 if self.items else -1
        self.result = None
        w = Window()
        T.dress(w)
        w.Title = u"Менеджер дополнительных материалов"
        w.Width = 1060
        w.Height = 700
        w.MinWidth = 860
        w.MinHeight = 520
        w.WindowStartupLocation = WindowStartupLocation.CenterOwner
        w.Owner = wiz.win
        w.FontFamily = wiz.win.FontFamily
        w.FontSize = 13
        try:
            w.Resources.MergedDictionaries.Add(wiz.win.Resources)     # те же стили кнопок
        except Exception:
            pass
        self.win = w
        root = Grid()
        root.Margin = Thickness(14, 12, 14, 12)
        for h in (GridLength.Auto, GridLength(1, GridUnitType.Star), GridLength.Auto):
            rd = RowDefinition()
            rd.Height = h
            root.RowDefinitions.Add(rd)
        w.Content = root
        self.viz = DragViz(w, root)
        head = tb(u"Справочник личный — %APPDATA%\\Spec_Manager\\materials.json, один для всех проектов (не в шаблоне "
                  u"настроек). Порядок строк = порядок в таблице: тяните мышью или ↑↓. Нормы с пометкой «пример» — "
                  u"не норматив: уточните по паспорту материала или проекту.", size=12, color=C_MUTED, wrap=True,
                  margin=Thickness(0, 0, 0, 8))
        root.Children.Add(head)
        mid = Grid()
        Grid.SetRow(mid, 1)
        for wd in (GridLength(1, GridUnitType.Star), GridLength(16), GridLength(420)):
            cd = ColumnDefinition()
            cd.Width = wd
            mid.ColumnDefinitions.Add(cd)
        root.Children.Add(mid)
        left = DockPanel()
        tools = WrapPanel()
        tools.Margin = Thickness(0, 6, 0, 0)
        DockPanel.SetDock(tools, Dock.Bottom)
        for txt, fn, tip in ((u"↑", lambda s, e: self.move(-1), u"Выше"), (u"↓", lambda s, e: self.move(1), u"Ниже"),
                             (u"+ Строка", lambda s, e: self.add(), u"Новая строка"),
                             (u"Дублировать", lambda s, e: self.dup(), None),
                             (u"Удалить", lambda s, e: self.delete(), None),
                             (u"Стандартный набор", lambda s, e: self.std(), u"Добавить недостающие строки стандартного набора"),
                             (u"Экспорт в XLSX…", lambda s, e: self.export(), None)):
            b = Button()
            b.Content = txt
            b.Padding = Thickness(8, 3, 8, 3)
            b.Margin = Thickness(0, 0, 6, 4)
            if tip:
                b.ToolTip = tip
            b.Click += fn
            tools.Children.Add(b)
        left.Children.Add(tools)
        self.lb = ListBox()
        self.lb.HorizontalContentAlignment = HorizontalAlignment.Stretch
        self.lb.BorderBrush = C_LINE
        ScrollViewer.SetHorizontalScrollBarVisibility(self.lb, 0)
        self.lb.SelectionChanged += self.on_sel
        left.Children.Add(self.lb)
        mid.Children.Add(left)
        Dragger(self.lb, lambda i: ("SM_MAT", str(i), self.items[i]["name"]) if 0 <= i < len(self.items) else None,
                self.viz)
        self.lb.Drop += self.on_drop
        self.viz.target(self.lb, ["SM_MAT"], reorder=("SM_MAT",))
        ed = StackPanel()
        esv = ScrollViewer()
        esv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        esv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
        esv.Content = ed
        Grid.SetColumn(esv, 2)
        mid.Children.Add(esv)
        self.f = {}

        def label(t):
            ed.Children.Add(tb(t, size=11, color=C_MUTED, margin=Thickness(0, 6, 0, 1)))

        def text(key, t, w_=None):
            label(t)
            x = TextBox()
            x.Padding = Thickness(3, 2, 3, 2)
            if w_:
                x.Width = w_
                x.HorizontalAlignment = HorizontalAlignment.Left
            ed.Children.Add(x)
            self.f[key] = x
            x.LostFocus += lambda s, e: self.apply()
        def combo(key, t, opts, editable=False):
            label(t)
            c = ComboBox()
            c.IsEditable = editable
            for o in opts:
                c.Items.Add(o)
            ed.Children.Add(c)
            self.f[key] = c
            c.SelectionChanged += lambda s, e: wiz._later(self.apply)
            if editable:
                c.LostFocus += lambda s, e: self.apply()
        combo("kind", u"Вид", [t for k, t in self.D.MAT_KINDS])
        text("name", u"Наименование (как в спецификации)")
        text("mark", u"Марка / ГОСТ")
        text("code", u"Код")
        text("maker", u"Завод-изготовитель")
        combo("unit", u"Единица", self.D.MAT_UNITS, editable=True)
        text("mass", u"Масса (текст, необязательно)", 140)
        combo("base", u"Основание расчёта", [t for k, t, u in self.D.MAT_BASES])
        text("norm", u"Норма расхода на единицу основания (м² на м² — 1)", 110)
        text("layers", u"Слоёв", 60)
        text("reserve", u"Запас, %", 60)
        text("bind", u"Привязка — материалы / типы с вкладки 3 через запятую (пусто — все)")
        names = wiz._bind_names()
        self.tBindHint = tb(u"Есть: " + (u", ".join(names) if names else u"— (списки вкладки 3 пусты)"), size=11,
                            color=brush("#174A87"), wrap=True, margin=Thickness(0, 2, 0, 0))
        ed.Children.Add(self.tBindHint)
        ex = CheckBox()
        ex.Content = u"норма — пример (уточнить по паспорту / проекту)"
        ex.Margin = Thickness(0, 8, 0, 0)
        ex.Click += lambda s, e: self.apply()
        ed.Children.Add(ex)
        self.f["example"] = ex
        bt = StackPanel()
        bt.Orientation = Orientation.Horizontal
        bt.HorizontalAlignment = HorizontalAlignment.Right
        bt.Margin = Thickness(0, 10, 0, 0)
        Grid.SetRow(bt, 2)
        root.Children.Add(bt)
        ok = Button()
        ok.Content = u"Сохранить"
        ok.Padding = Thickness(16, 5, 16, 5)
        ok.Click += lambda s, e: self.save()
        bt.Children.Add(ok)
        cc = Button()
        cc.Content = u"Отмена"
        cc.Padding = Thickness(16, 5, 16, 5)
        cc.Margin = Thickness(8, 0, 0, 0)
        cc.IsCancel = True
        bt.Children.Add(cc)
        w.PreviewKeyDown += self.on_key
        self._loading = False
        self.draw()

    def on_key(self, s, e):
        foc = Keyboard.FocusedElement
        if e.Key in (Key.Return, Key.Enter) and isinstance(foc, TextBox):
            self.apply()
            e.Handled = True

    def draw(self):
        self.lb.Items.Clear()
        for n, m in enumerate(self.items, 1):
            li = ListBoxItem()
            li.Padding = Thickness(4, 3, 4, 3)
            sp = StackPanel()
            sp.Children.Add(tb(u"⋮⋮  {0}. {1}".format(n, m["name"] or u"(без названия)"), bold=True))
            sp.Children.Add(tb(self.wiz._mat_line(m) + (u" · пример" if m.get("example") else u""), size=11,
                               color=C_MUTED, wrap=True, margin=Thickness(22, 0, 0, 0)))
            li.Content = sp
            self.lb.Items.Add(li)
        if 0 <= self.sel < len(self.items):
            self.lb.SelectedIndex = self.sel
        else:
            self.fill(None)

    def on_sel(self, s, e):
        i = self.lb.SelectedIndex
        if 0 <= i < len(self.items):
            self.sel = i
            self.fill(self.items[i])

    def fill(self, m):
        self._loading = True
        try:
            m = m or self.core.mat_norm({})
            kinds = [k for k, t in self.D.MAT_KINDS]
            bases = [k for k, t, u in self.D.MAT_BASES]
            self.f["kind"].SelectedIndex = kinds.index(m["kind"]) if m["kind"] in kinds else 0
            self.f["base"].SelectedIndex = bases.index(m["base"]) if m["base"] in bases else 0
            self.f["unit"].Text = m["unit"]
            for k in ("name", "mark", "code", "maker", "mass"):
                self.f[k].Text = m.get(k) or u""
            for k in ("norm", "reserve"):
                self.f[k].Text = (u"%g" % float(m[k] or 0)).replace(u".", u",")
            self.f["layers"].Text = u"%d" % int(m["layers"])
            self.f["bind"].Text = u", ".join(m["bind"])
            self.f["example"].IsChecked = bool(m.get("example"))
        finally:
            self._loading = False

    def apply(self):
        if self._loading or not (0 <= self.sel < len(self.items)):
            return
        m = self.items[self.sel]

        def fnum(t, d):
            try:
                return float((t or u"").replace(u",", u"."))
            except Exception:
                return d
        kinds = [k for k, t in self.D.MAT_KINDS]
        bases = [k for k, t, u in self.D.MAT_BASES]
        ki, bi = self.f["kind"].SelectedIndex, self.f["base"].SelectedIndex
        m["kind"] = kinds[ki] if ki >= 0 else m["kind"]
        m["base"] = bases[bi] if bi >= 0 else m["base"]
        m["unit"] = (self.f["unit"].Text or u"").strip() or m["unit"]
        for k in ("name", "mark", "code", "maker", "mass"):
            m[k] = (self.f[k].Text or u"").strip()
        m["norm"] = max(0.0, fnum(self.f["norm"].Text, m["norm"]))
        m["layers"] = max(1, int(fnum(self.f["layers"].Text, m["layers"])))
        m["reserve"] = max(0.0, fnum(self.f["reserve"].Text, m["reserve"]))
        m["bind"] = [x.strip() for x in (self.f["bind"].Text or u"").split(u",") if x.strip()]
        m["example"] = bool(self.f["example"].IsChecked)
        i = self.sel
        li = self.lb.Items[i] if i < self.lb.Items.Count else None
        if li is not None:
            sp = li.Content
            sp.Children[0].Text = u"⋮⋮  {0}. {1}".format(i + 1, m["name"] or u"(без названия)")
            sp.Children[1].Text = self.wiz._mat_line(m) + (u" · пример" if m.get("example") else u"")

    def move(self, d):
        i, j = self.sel, self.sel + d
        if 0 <= i < len(self.items) and 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            self.sel = j
            self.draw()

    def on_drop(self, s, e):
        if e.Data.GetDataPresent("SM_MAT"):
            src = int(e.Data.GetData("SM_MAT"))
            pos = DragViz.drop_index(self.lb, e)
            if 0 <= src < len(self.items):
                x = self.items.pop(src)
                if pos > src:
                    pos -= 1
                pos = max(0, min(pos, len(self.items)))
                self.items.insert(pos, x)
                self.sel = pos
                self.draw()
        self.viz.end()
        e.Handled = True

    def add(self):
        self.items.append(self.core.mat_norm({"name": u"Новый материал"}))
        self.sel = len(self.items) - 1
        self.draw()

    def dup(self):
        if 0 <= self.sel < len(self.items):
            m = dict(self.items[self.sel])
            m["id"] = u""
            m = self.core.mat_norm(m)
            m["name"] += u" (копия)"
            self.items.insert(self.sel + 1, m)
            self.sel += 1
            self.draw()

    def delete(self):
        if 0 <= self.sel < len(self.items):
            self.items.pop(self.sel)
            self.sel = min(self.sel, len(self.items) - 1)
            self.draw()

    def std(self):
        have = set(m["id"] for m in self.items)
        add = [m for m in self.core.materials_std() if m["id"] not in have]
        self.items.extend(add)
        self.draw()
        self.win.Title = u"Менеджер дополнительных материалов — добавлено из стандартного набора: {0}".format(len(add))

    def export(self):
        from Microsoft.Win32 import SaveFileDialog
        d = SaveFileDialog()
        d.Title = u"Экспорт справочника материалов"
        d.Filter = u"Книга Excel (*.xlsx)|*.xlsx"
        d.FileName = u"Дополнительные материалы.xlsx"
        if d.ShowDialog(self.win):
            try:
                self.apply()
                self.core.export_materials_xlsx(self.items, d.FileName)
                self.win.Title = u"Менеджер дополнительных материалов — сохранено в {0}".format(d.FileName)
            except Exception as ex:
                MessageBox.Show(self.win, u"Не удалось сохранить:\n{0}".format(ex), u"Экспорт", MessageBoxButton.OK,
                                MessageBoxImage.Warning)

    def save(self):
        self.apply()
        try:
            self.core.save_materials(self.items)
        except Exception as ex:
            MessageBox.Show(self.win, u"Справочник не сохранён:\n{0}".format(ex), u"Материалы", MessageBoxButton.OK,
                            MessageBoxImage.Warning)
            return
        self.result = [self.core.mat_norm(m) for m in self.items]
        self.win.DialogResult = True

    def show(self):
        self.win.ShowDialog()
        return self.result


# ------------------------------------------------------------------
# окно «Раздел проекта» (0.9.3, по HTML-макету): выбор один раз на проект
# ------------------------------------------------------------------
def disc_by_key(D, k):
    for d in getattr(D, "DISCIPLINES", None) or []:
        if d.get("k") == k and not d.get("soon"):
            return d
    return None


def suggest_disc(D, infos):
    """«По модели подходит»: есть воздуховоды и нет сантехприборов — ОВ, иначе ВК (как в макете)."""
    keys = set(getattr(it, "key", None) for it in infos or [])
    ov = any(k in keys for k in getattr(D, "OV_KEYS", ("duct", "dfit", "dacc")))
    return "OV" if ov and "fix" not in keys else "VK"


class DisciplineWindow(object):
    """Карточки разделов в две колонки; под ними — что будет собираться в выбранном разделе. Щелчок — выбрать,
    двойной щелчок или «Выбрать» — подтвердить, Отмена / Esc / × — None."""

    def __init__(self, D, infos, cfg, first=True, ov_info=None, stats_fn=None):
        self.D = D
        self.cfg = cfg
        self.ov_info = ov_info                  # (кратко, [подробно]) — vks_sections.summary
        self.stats_fn = stats_fn                # fallback -> (всего, с ADSK_Группирование, [значения], не определится)
        self.gb = None                          # группы по: "systems" | "grouping" (None — по умолчанию раздела)
        self.fb = cfg.get("group_fallback", True) is not False
        self.result = None
        self.sug = suggest_disc(D, infos)
        self.infos = infos
        cur = cfg.get("discipline")
        self.pick = cur if disc_by_key(D, cur) else self.sug
        if self.pick == cur and cfg.get("group_by") in ("systems", "grouping"):
            self.gb = cfg["group_by"]
        self.cards = {}
        w = Window()
        T.dress(w)
        w.Title = u"Менеджер спецификаций: раздел проекта" if first else u"Сменить раздел проекта"
        w.Width = 780
        w.SizeToContent = SizeToContent.Height
        w.ResizeMode = ResizeMode.NoResize
        w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        w.ShowInTaskbar = False
        w.FontFamily = FontFamily(u"Segoe UI")
        w.FontSize = 13
        w.Background = C_BG
        self.win = w
        root = StackPanel()
        root.Margin = Thickness(16, 12, 16, 14)
        root.Children.Add(tb(u"Раздел выбирается один раз для проекта и запоминается — при следующих запусках не "
                             u"спрашивается. Сменить — кнопка с кодом раздела слева вверху окна мастера.",
                             color=brush("#4A5361"), wrap=True, margin=Thickness(0, 0, 0, 10)))
        grid = UniformGrid()
        grid.Columns = 2
        for d in getattr(D, "DISCIPLINES", None) or []:
            grid.Children.Add(self._card(d))
        root.Children.Add(grid)
        self.box = Border()
        self.box.Background = brush("#FAFBFC")
        self.box.BorderBrush = C_LINE
        self.box.BorderThickness = Thickness(1)
        self.box.CornerRadius = CornerRadius(6)
        self.box.Padding = Thickness(12, 8, 12, 8)
        self.box.Margin = Thickness(4, 10, 4, 0)
        self.boxPanel = StackPanel()
        self.box.Child = self.boxPanel
        root.Children.Add(self.box)
        bar = StackPanel()
        bar.Orientation = Orientation.Horizontal
        bar.HorizontalAlignment = HorizontalAlignment.Right
        bar.Margin = Thickness(0, 14, 4, 0)
        ok = Button()
        ok.Content = u"Выбрать"
        ok.IsDefault = True
        ok.Padding = Thickness(18, 5, 18, 5)
        ok.Margin = Thickness(0, 0, 8, 0)
        ok.Background = C_BLUE_BG
        ok.Foreground = Brushes.White
        ok.FontWeight = FontWeights.SemiBold
        ok.Click += lambda s, e: self._ok()
        cancel = Button()
        cancel.Content = u"Отмена"
        cancel.IsCancel = True
        cancel.Padding = Thickness(18, 5, 18, 5)
        bar.Children.Add(ok)
        bar.Children.Add(cancel)
        root.Children.Add(bar)
        w.Content = root
        self._draw()

    def _card(self, d):
        b = Border()
        b.CornerRadius = CornerRadius(6)
        b.BorderThickness = Thickness(1)
        b.Padding = Thickness(12, 8, 12, 8)
        b.Margin = Thickness(4)
        sp = StackPanel()
        head = TextBlock()
        head.TextWrapping = TextWrapping.Wrap
        r1 = Run(d.get("code") + u"  ")
        r1.FontWeight = FontWeights.Bold
        r1.FontSize = 15
        r2 = Run(d.get("name"))
        r2.FontWeight = FontWeights.SemiBold
        head.Inlines.Add(r1)
        head.Inlines.Add(r2)
        sp.Children.Add(head)
        if d.get("soon"):
            sub = u"предложение · скоро" if d.get("prop") else u"скоро"
        else:
            sub = d.get("desc") or u""
            if d.get("k") == self.sug:
                sub += u" · по модели подходит"
        sp.Children.Add(tb(sub, size=12, color=C_MUTED, wrap=True, margin=Thickness(0, 2, 0, 0)))
        b.Child = sp
        if d.get("soon"):
            b.Background = brush("#F4F6F8")
            b.BorderBrush = brush("#E3E7EC")
            b.Opacity = 0.6
        else:
            b.Cursor = Cursors.Hand
            k = d.get("k")

            def down(s, e, k=k):
                if k != self.pick:
                    self.gb = None              # другой раздел — его умолчание
                self.pick = k
                self._draw()
                if e.ClickCount >= 2:
                    self._ok()
            b.MouseLeftButtonDown += down
            self.cards[k] = (b, head)
        return b

    def _draw(self):
        for k, (b, head) in self.cards.items():
            on = k == self.pick
            b.Background = brush("#EEF4FF") if on else C_BG
            b.BorderBrush = C_BLUE if on else C_LINE
            b.BorderThickness = Thickness(2 if on else 1)
            head.Foreground = C_BLUE if on else brush("#1D2C43")
        self.boxPanel.Children.Clear()
        d = disc_by_key(self.D, self.pick)
        if d is None:
            return
        add = self.boxPanel.Children.Add
        if d.get("mode") == "sections":
            add(tb(u"Как собирается раздел {0}:".format(d["code"]), bold=True, margin=Thickness(0, 0, 0, 4)))
            short, lines = self.ov_info or (u"Разделы ОВ — по шаблонам «О_…» (пресет «ОВ как в 414»).", [])
            add(tb(short, size=12, wrap=True))
            return
        dflt = d.get("group_by") or "systems"
        gb = self.gb or dflt
        add(tb(u"Группы спецификаций в разделе {0} — по:".format(d["code"]), bold=True, margin=Thickness(0, 0, 0, 4)))
        row = StackPanel()
        row.Orientation = Orientation.Horizontal
        for key, text in (("systems", u"системам"), ("grouping", u"ADSK_Группирование")):
            rb = RadioButton()
            rb.Content = text
            rb.GroupName = "discGb"
            rb.IsChecked = gb == key
            rb.Margin = Thickness(0, 0, 18, 0)
            rb.VerticalAlignment = VerticalAlignment.Center

            def pick(s, e, key=key):
                self.gb = key
                self._draw()
            rb.Click += pick
            row.Children.Add(rb)
        row.Children.Add(tb(u"по умолчанию для {0}: {1}".format(
            d["code"], u"ADSK_Группирование" if dflt == "grouping" else u"системам"), size=12, color=C_MUTED))
        add(row)
        cb = CheckBox()
        cb.Content = u"Пусто — брать по сокращению системы (В 0, В 1 → «В»)"
        cb.IsChecked = self.fb
        cb.IsEnabled = gb == "grouping"
        cb.Opacity = 1.0 if gb == "grouping" else 0.45
        cb.Margin = Thickness(22, 4, 0, 0)

        def set_fb(s, e):
            self.fb = bool(s.IsChecked)
            self._draw()
        cb.Click += set_fb
        add(cb)
        if gb == "grouping" and self.stats_fn is not None:
            try:
                tot, filled, vals, unres = self.stats_fn(self.fb)
                txt = u"ADSK_Группирование заполнен у {0} из {1} эл.; значения: {2}{3}.".format(
                    filled, tot, u", ".join(vals[:10]), u" …" if len(vals) > 10 else u"")
                if unres:
                    txt += u" Не определится: {0} эл. (пусто и {1}) — заполните ADSK_Группирование.".format(
                        unres, u"сокращения систем разные" if self.fb else u"есть система")
                add(tb(txt, size=12, wrap=True, color=brush("#8A5A00") if unres else C_MUTED,
                       margin=Thickness(2, 6, 0, 0)))
            except Exception as ex:
                add(tb(u"ADSK_Группирование не прочитан: {0}".format(ex), size=12, wrap=True, color=C_MUTED,
                       margin=Thickness(2, 6, 0, 0)))
        else:
            ng = len(self.cfg.get("groups") or [])
            add(tb(u"Группы систем — на вкладке «Системы» (сейчас групп: {0}). Фильтр спецификаций — "
                   u"ADSK_Система_Обозначение.".format(ng), size=12, wrap=True, color=C_MUTED,
                   margin=Thickness(2, 6, 0, 0)))

    def _ok(self):
        d = disc_by_key(self.D, self.pick)
        if d is not None:
            self.result = self.pick
            self.cfg["group_by"] = self.gb or d.get("group_by") or "systems"
            self.cfg["group_fallback"] = self.fb
            self.win.Close()

    def show(self, owner_handle=None):
        if owner_handle:
            try:
                from System.Windows.Interop import WindowInteropHelper
                WindowInteropHelper(self.win).Owner = owner_handle
                self.win.WindowStartupLocation = WindowStartupLocation.CenterOwner
            except Exception:
                pass
        self.win.ShowDialog()
        return self.result


class ScopeWindow(object):
    """«Что собираем» (ВК, ОВ; перед каждой сборкой): общая на объект / на блок / по всем блокам отдельно.
    Блоки — значения ADSK_Номер секции. -> {"scope": "all"|"one"|"each", "sec": секция} или None (закрыто)."""

    def __init__(self, D, secs, nosec, cfg, main_folder, sec_folder, sec_apply=None):
        self.D = D
        self.sec_apply = sec_apply               # кнопка «Перенести номер секции во вложенные»: () -> (n, текст)
        self.secs = secs                         # [(секция, число элементов)]
        self.nosec = nosec
        self.main_folder = main_folder
        self.sec_folder = sec_folder             # функция: секция -> имя коллекции
        last = cfg.get("build") or {}
        self.scope = last.get("scope") if last.get("scope") in ("all", "one", "each") else "all"
        names = [s for s, n in secs]
        self.sec = last.get("sec") if last.get("sec") in names else (names[0] if names else None)
        self.result = None
        w = Window()
        T.dress(w)
        w.Title = u"Менеджер спецификаций: что собираем"
        w.Width = 620
        w.SizeToContent = SizeToContent.Height
        w.ResizeMode = ResizeMode.NoResize
        w.WindowStartupLocation = WindowStartupLocation.CenterScreen
        w.ShowInTaskbar = False
        w.FontFamily = FontFamily(u"Segoe UI")
        w.FontSize = 13
        w.Background = C_BG
        self.win = w
        root = StackPanel()
        root.Margin = Thickness(16, 12, 16, 14)
        root.Children.Add(tb(u"Блоки — по ADSK_Номер секции: {0}.".format(
            u", ".join(u"{0} ({1} эл.)".format(s, n) for s, n in secs[:12]) + (u" …" if len(secs) > 12 else u"")),
            color=brush("#4A5361"), wrap=True, margin=Thickness(0, 0, 0, 10)))
        self.radios = {}
        for k, t, hint in getattr(D, "BUILD_SCOPES", []):
            rb = RadioButton()
            rb.GroupName = u"buildScope"
            rb.Margin = Thickness(0, 4, 0, 2)
            sp = StackPanel()
            sp.Children.Add(tb(t, bold=True))
            sp.Children.Add(tb(hint, size=12, color=C_MUTED, wrap=True))
            rb.Content = sp
            rb.IsChecked = k == self.scope

            def pick(s, e, k=k):
                self.scope = k
                self._draw()
            rb.Click += pick
            root.Children.Add(rb)
            self.radios[k] = rb
            if k == "one":
                row = StackPanel()
                row.Orientation = Orientation.Horizontal
                row.Margin = Thickness(22, 4, 0, 4)
                row.Children.Add(tb(u"Блок:", margin=Thickness(0, 0, 8, 0)))
                cb = ComboBox()
                cb.Width = 160
                for s, n in secs:
                    cb.Items.Add(s)
                if self.sec is not None:
                    cb.SelectedIndex = names.index(self.sec)

                def sel(s_, e):
                    i = self.cbSec.SelectedIndex
                    if 0 <= i < len(self.secs):
                        self.sec = self.secs[i][0]
                        self.scope = "one"
                        self.radios["one"].IsChecked = True
                        self._draw()
                cb.SelectionChanged += sel
                self.cbSec = cb
                row.Children.Add(cb)
                root.Children.Add(row)
        self.box = Border()
        self.box.Background = brush("#FAFBFC")
        self.box.BorderBrush = C_LINE
        self.box.BorderThickness = Thickness(1)
        self.box.CornerRadius = CornerRadius(6)
        self.box.Padding = Thickness(12, 8, 12, 8)
        self.box.Margin = Thickness(0, 10, 0, 0)
        self.info = tb(u"", size=12, wrap=True)
        self.box.Child = self.info
        root.Children.Add(self.box)
        if sec_apply is not None:
            row2 = StackPanel()
            row2.Orientation = Orientation.Horizontal
            row2.Margin = Thickness(0, 10, 0, 0)
            bt = Button()
            bt.Content = u"Перенести секцию и группирование во вложенные"
            bt.ToolTip = (u"Вложенным общим семействам — ADSK_Номер секции и ADSK_Группирование родителя, изоляции "
                          u"труб и воздуховодов — трубы / воздуховода. Сразу в модель, одним шагом Ctrl+Z. При сборке "
                          u"делается и так.")
            bt.Padding = Thickness(12, 4, 12, 4)
            bt.Click += lambda s_, e: self._sec_apply()
            row2.Children.Add(bt)
            self.tSecApply = tb(u"", size=12, color=C_MUTED, wrap=True, margin=Thickness(10, 0, 0, 0))
            self.tSecApply.VerticalAlignment = VerticalAlignment.Center
            self.tSecApply.MaxWidth = 330
            row2.Children.Add(self.tSecApply)
            root.Children.Add(row2)
        bar = StackPanel()
        bar.Orientation = Orientation.Horizontal
        bar.HorizontalAlignment = HorizontalAlignment.Right
        bar.Margin = Thickness(0, 14, 0, 0)
        ok = Button()
        ok.Content = u"Далее"
        ok.IsDefault = True
        ok.Padding = Thickness(18, 5, 18, 5)
        ok.Margin = Thickness(0, 0, 8, 0)
        ok.Background = C_BLUE_BG
        ok.Foreground = Brushes.White
        ok.FontWeight = FontWeights.SemiBold
        ok.Click += lambda s, e: self._ok()
        cancel = Button()
        cancel.Content = u"Отмена"
        cancel.IsCancel = True
        cancel.Padding = Thickness(18, 5, 18, 5)
        bar.Children.Add(ok)
        bar.Children.Add(cancel)
        root.Children.Add(bar)
        w.Content = root
        self._draw()

    def _draw(self):
        if self.scope == "one" and self.sec:
            n = dict(self.secs).get(self.sec, 0)
            t = (u"Блок {0}: {1} эл. Комплект — в коллекции «{2}»; спецификации и листы других блоков и общего "
                 u"комплекта не меняются.".format(self.sec, n, self.sec_folder(self.sec)))
        elif self.scope == "each":
            t = (u"Комплектов: {0} — коллекции {1}. Позиции в каждом — с 1.".format(
                len(self.secs), u", ".join(u"«{0}»".format(self.sec_folder(s)) for s, n in self.secs[:4]) +
                (u" …" if len(self.secs) > 4 else u"")))
        else:
            t = u"Один комплект на весь объект — коллекция «{0}», секции не разделяются.".format(self.main_folder)
        if self.scope in ("one", "each") and self.nosec:
            t += u" Без ADSK_Номер секции: {0} эл. — в комплекты блоков не попадут.".format(self.nosec)
        if self.scope == "one":
            t += u" Группы — свои у блока: правятся в следующем окне; новый блок — копия общих групп."
        elif self.scope == "each":
            t += (u" Группы — свои у каждого блока (задаются при сборке «На блок»); у блока без своих — копия "
                  u"общих групп из следующего окна.")
        self.info.Text = t

    def _sec_apply(self):
        self.tSecApply.Text = u"переношу…"
        try:
            n, t = self.sec_apply()
            self.tSecApply.Text = t
        except Exception as ex:
            self.tSecApply.Text = u"не вышло, модель не изменена: {0}".format(ex)

    def _ok(self):
        if self.scope == "one" and not self.sec:
            return
        self.result = {"scope": self.scope, "sec": self.sec if self.scope == "one" else None}
        self.win.Close()

    def show(self, owner_handle=None):
        if owner_handle:
            try:
                from System.Windows.Interop import WindowInteropHelper
                WindowInteropHelper(self.win).Owner = owner_handle
                self.win.WindowStartupLocation = WindowStartupLocation.CenterOwner
            except Exception:
                pass
        self.win.ShowDialog()
        return self.result


def choose_scope(core, infos, cfg, owner_handle=None):
    """«Что собираем» перед мастером. -> {"scope", "sec"} или None (закрыто). Нет секций в модели — {"scope": "all"}
    без окна."""
    secs, nosec = core.sections_found(infos)
    if not secs:
        return {"scope": "all", "sec": None}
    theme_init()
    lo = core.layout_cfg(cfg)
    main = (lo.get("sheet_folder") or u"").strip() or u"ВК.С"
    apply_fn = (lambda: core.section_apply(core.doc)) if hasattr(core, "section_apply") else None
    return ScopeWindow(core.D, secs, nosec, cfg, main, lambda s: core.section_folder(cfg, s),
                       apply_fn).show(owner_handle)


def choose_discipline(core, infos, cfg, owner_handle=None, first=True, ov_info=None):
    """-> ключ раздела ("VK", "OV") или None (окно закрыто). Выбор «группы по» и «пусто — по системе» —
    в cfg["group_by"], cfg["group_fallback"] (только при «Выбрать»)."""
    stats = getattr(core, "grouping_stats", None)
    fn = (lambda fb: stats(infos, fb)) if stats else None
    theme_init()
    return DisciplineWindow(core.D, infos, cfg, first, ov_info, fn).show(owner_handle)


def run_wizard(core, infos, systems, cfg, owner_handle=None):
    w = Wizard(core, infos, systems, cfg)
    b = cfg.get("build") or {}
    try:
        if b.get("scope") == "one":
            w.win.Title = u"{0} — блок {1}".format(w.win.Title or u"Менеджер спецификаций", b.get("sec"))
        elif b.get("scope") == "each":
            w.win.Title = u"{0} — по всем блокам".format(w.win.Title or u"Менеджер спецификаций")
    except Exception:
        pass                                   # заголовок окна — только подсказка
    return w.show(owner_handle)
