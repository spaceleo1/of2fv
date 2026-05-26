# Архитектура конвертера OF2FV

## Общая схема

```
OpenFOAM case/               FlowVision project/
  constant/                     project/
    polyMesh/     ──┐              *.fvproj
    physicalProp.   │              *_00000.fvinp  (patched)
    momentumTransp. │              *.fvctrl
  0/                │              *.fvbcs, .fvgeom, ...
    U, p, k, ...    │           geometry/
  system/           │              *.stl
    controlDict     │           conversion_report.txt
                    │
                    ▼
              ┌─────────────┐
              │ CaseReader  │  ── dict_parser
              │             │  ── mesh_reader
              │             │  ── field_reader
              └──────┬──────┘
                     │
                     ▼
              ┌─────────────┐
              │  CAEProject  │  промежуточная модель
              │  (dataclass) │
              └──────┬──────┘
                     │
                     ▼
              ┌─────────────┐
              │model_mapper │  OF -> FV маппинг
              └──────┬──────┘
                     │
            ┌────────┼────────┐
            ▼        ▼        ▼
     stl_exporter  template   project_writer
     (polyMesh →   _patcher   (оркестрация,
      STL)         (regex     копирование
                    патчинг   шаблонов)
                    .fvinp)
```

## Модули и их роли

### Уровень 1: Парсинг OpenFOAM

| Модуль | Файл | Роль |
|--------|------|------|
| `dict_parser` | `src/openfoam/dict_parser.py` | Рекурсивный парсер формата словарей OpenFOAM (вложенные блоки, списки, dimensioned values, `#include`) |
| `mesh_reader` | `src/openfoam/mesh_reader.py` | Чтение `constant/polyMesh/` — точки, грани, boundary-патчи |
| `field_reader` | `src/openfoam/field_reader.py` | Чтение полей из `0/` — `internalField`, `boundaryField` |
| `case_reader` | `src/openfoam/case_reader.py` | Оркестратор: определяет тип задачи, собирает `CAEProject` |

### Уровень 2: Промежуточная модель

Модуль `src/model.py` определяет пять dataclass'ов:

- **`CAEProject`** — корневой контейнер (physics, substances, patches, BCs, ICs, Tref, Pref)
- **`PhysicsModel`** — тип задачи, турбулентность, гравитация, солвер
- **`Substance`** — плотность, вязкость, агрегатное состояние
- **`PatchInfo`** — метаданные патча из `polyMesh/boundary`
- **`BoundaryCondition`** — тип BC (OF и FV), значения полей на границе

Модель не зависит ни от OpenFOAM, ни от FlowVision — чистое промежуточное представление.

### Уровень 3: Генерация FlowVision

| Модуль | Файл | Роль |
|--------|------|------|
| `model_mapper` | `src/flowvision/model_mapper.py` | Таблицы соответствий: турбулентность, типы BC, имена полей, конвертация давления |
| `template_patcher` | `src/flowvision/template_patcher.py` | Regex-патчинг `.fvinp` XML: CGeneralSettings, CInitialData, Source paths |
| `stl_exporter` | `src/flowvision/stl_exporter.py` | Экспорт патчей polyMesh в бинарный STL |
| `project_writer` | `src/flowvision/project_writer.py` | Оркестратор: выбор шаблона, вызов patcher, копирование бинарных файлов |

### Уровень 4: Интерфейсы

| Файл | Роль |
|------|------|
| `convert.py` | CLI-интерфейс (argparse + rich) |
| `gui.py` + `src/gui/` | GUI-интерфейс (PyQt6) |
| `verify.py` | Скрипт верификации (сравнение OF vs FV) |

## Стратегия regex-патчинга XML

FlowVision `.fvinp` — XML-файл (~14000 строк), содержащий сериализованные
объекты C++ с атрибутами `class`, `myid`, `Constant`, `UIName`.

Почему **не** `xml.etree.ElementTree.write()`:
- FlowVision чувствителен к точному форматированию XML
- `ElementTree.write()` нормализует пробелы, порядок атрибутов, кавычки
- Результат не читается парсером FlowVision (crash на загрузке)

Выбранный подход:
1. Загрузка `.fvinp` как строки
2. Поиск нужного блока через `_extract_nested_block()` — счётчик вложенности `<OBJECT>`/`</OBJECT>`
3. Замена `Constant="old_value"` на `Constant="new_value"` через `re.sub`
4. Запись строки обратно — побайтово идентична оригиналу, кроме заменённых значений

## Изоляция FV-файлов

FlowVision падает (`EXCEPTION DURING OPENING A PROJECT!`) при наличии
посторонних файлов или подпапок в директории проекта. Поэтому:

```
output/
  project/              ← только FV-файлы
    NACA0012_3deg.fvproj
    NACA0012_3deg_00000.fvinp
    NACA0012_3deg.fvctrl
    ...бинарные файлы...
  geometry/             ← STL-файлы (отдельно)
  conversion_report.txt ← отчёт (отдельно)
```

## Шаблоны

Директория `templates/` содержит три готовых проекта FlowVision:

| Шаблон | Тип | Файлы |
|--------|-----|-------|
| `aero/NACA0012_3deg` | Аэродинамика | `.fvproj`, `.fvinp`, `.fvctrl`, `.fvbcs`, `.fvgeom`, ... |
| `vof/Boat` | VoF (гидродинамика) | Аналогичный набор |
| `icing/Icing_naca012` | Обледенение | Аналогичный набор |

Шаблон выбирается автоматически по `case_type` из `CAEProject.physics`.
