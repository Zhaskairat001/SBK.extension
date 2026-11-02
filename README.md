# Менеджер спецификаций — расширение pyRevit

Кнопка **«Менеджер спецификаций»** (вкладка SBK → панель VK) собирает спецификации оборудования, изделий и
материалов по ГОСТ 21.601-2011 для разделов ВК и ОВ: группы систем, порядок строк, позиции, таблица покрасочных и
монтажных материалов, раскладка по листам, сборка по блокам/секциям (`ADSK_Номер секции`). Вся сборка — один шаг
Ctrl+Z; при ошибке модель не меняется, причина — по-русски.

| Требуется | Версия |
|---|---|
| Autodesk Revit | 2025 |
| pyRevit | 5.x |
| Параметры | ADSK (ФОП шаблонов ADSK): ADSK_Наименование, ADSK_Количество, ADSK_Позиция, ADSK_Группирование … |

## Установка (с автообновлением)

1. Закройте Revit.
2. Если кнопка уже стоит из установщика (архив `Менеджер_спецификаций_*.zip`) — переименуйте папку
   `%APPDATA%\pyRevit\Extensions\SBK.extension` в `SBK.extension_old`. Из неё потом понадобятся папки
   `_settings` и `_presets` (настройки ваших проектов).
3. В командной строке:
   ```
   pyrevit extend ui SBK https://github.com/Zhaskairat001/SBK.extension.git
   ```
   или в Revit: вкладка pyRevit → Extensions → «Add custom extension» → ссылка выше.
4. Скопируйте `_settings` и `_presets` из `SBK.extension_old` в новую папку `SBK.extension` (если они были).
5. Запустите Revit.

## Обновление

Вкладка pyRevit → **Update** (или включите в настройках pyRevit проверку обновлений при запуске). pyRevit
подтянет последнюю версию из этого репозитория. Настройки проектов (`_settings`, `_presets`) не затрагиваются.

## Установка без Git

На странице [Releases](https://github.com/Zhaskairat001/SBK.extension/releases) — архив
`Менеджер_спецификаций_<версия>.zip`: распаковать, запустить «Установить.bat» (резервная копия и откат —
«Откатить.bat»). Так обновления ставятся вручную.

## Где что лежит

| Что | Где |
|---|---|
| Кнопка | `SBK.tab\VK.panel\BuildVKS.pushbutton` (`script.py` → `vks_core`, `vks_ui`, `vks_layout`, `vks_defaults`, `vks_fix`, `vks_anim`) |
| История изменений | `SBK.tab\VK.panel\BuildVKS.pushbutton\CHANGELOG.md` |
| Настройки проектов и шаблоны | `_settings`, `_presets` в папке расширения (не в репозитории) |
| Справочник материалов, журналы | `%APPDATA%\Spec_Manager`, `%LOCALAPPDATA%\Spec_Manager\logs` |

Автор — Zhaskairat001.
