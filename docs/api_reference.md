# API Reference

Справочник по публичным классам и функциям конвертера OF2FV.

---

## src.model

Промежуточная модель данных (dataclasses).

### `PatchInfo`

Информация о патче из `polyMesh/boundary`.

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | `str` | Имя патча (`inlet`, `outlet`, `walls`) |
| `patch_type` | `str` | Тип (`patch`, `wall`, `empty`, `symmetry`, `cyclic`) |
| `n_faces` | `int` | Количество граней |
| `start_face` | `int` | Индекс первой грани |

### `Substance`

Свойства вещества.

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | `str` | Имя (`Air`, `Water`) |
| `density` | `float` | Плотность, кг/м³ |
| `viscosity` | `float` | Динамическая вязкость, Па·с |
| `cp` | `float \| None` | Удельная теплоёмкость, Дж/(кг·К) |
| `thermal_conductivity` | `float \| None` | Теплопроводность, Вт/(м·К) |
| `agg_state` | `str` | Агрегатное состояние (`Gas`, `Liquid`, `Solid`) |

### `PhysicsModel`

Описание физико-математической модели.

| Поле | Тип | Описание |
|------|-----|----------|
| `case_type` | `str` | `aero`, `vof`, `icing` |
| `turbulence` | `str` | Модель турбулентности OF |
| `is_compressible` | `bool` | Сжимаемость |
| `gravity` | `tuple[float, float, float]` | Вектор g, м/с² |
| `solver` | `str` | Имя солвера OF |

### `BoundaryCondition`

Граничное условие на патче.

| Поле | Тип | Описание |
|------|-----|----------|
| `patch_name` | `str` | Имя патча |
| `of_type` | `str` | Тип BC в OpenFOAM |
| `fv_type` | `str` | Тип BC в FlowVision |
| `velocity` | `tuple \| None` | Вектор скорости |
| `pressure` | `float \| None` | Давление |
| `temperature` | `float \| None` | Температура |
| `turb_k` | `float \| None` | Турбулентная кин. энергия |
| `turb_epsilon` | `float \| None` | Диссипация |
| `turb_omega` | `float \| None` | Удельная диссипация |
| `vof_alpha` | `float \| None` | Объёмная доля (VOF) |

### `CAEProject`

Полное описание проекта.

| Поле | Тип | Описание |
|------|-----|----------|
| `case_path` | `str` | Путь к OF-кейсу |
| `physics` | `PhysicsModel` | Физическая модель |
| `substances` | `list[Substance]` | Вещества |
| `patches` | `list[PatchInfo]` | Патчи из polyMesh |
| `boundary_conditions` | `list[BoundaryCondition]` | Граничные условия |
| `initial_conditions` | `dict[str, Any]` | Начальные условия |
| `tref` | `float` | Референсная температура, К |
| `pref` | `float` | Референсное давление, Па |
| `end_time` | `float` | Время окончания расчёта, с |
| `delta_t` | `float` | Шаг по времени, с |

---

## src.openfoam.dict_parser

Парсер формата словарей OpenFOAM.

### `parse_file(path: Path) -> dict`

Парсит файл формата OpenFOAM dictionary и возвращает вложенный `dict`.
Поддерживает: вложенные блоки `{ }`, списки `( )`, dimensioned values,
комментарии `//` и `/* */`, директивы `#include`.

---

## src.openfoam.case_reader

### `CaseReader(case_path: str | Path)`

Читает проект OpenFOAM.

**Атрибуты:**
- `case_path: Path` — абсолютный путь к кейсу
- `mesh: MeshReader | None` — загруженная сетка (None если нет polyMesh)
- `fields: FieldReader` — читатель полей

**Методы:**
- `read() -> CAEProject` — полный парсинг: тип задачи, физика, вещества, BC, IC

---

## src.openfoam.mesh_reader

### `MeshReader(case_path: str | Path)`

Читает `constant/polyMesh/` — points, faces, boundary.

**Методы:**
- `get_patch_faces(patch_name: str) -> list[list[int]]` — индексы вершин граней
- `get_patch_points(patch_name: str) -> ndarray` — координаты точек патча

**Атрибуты:**
- `patches: list[PatchInfo]` — список патчей
- `points: ndarray` — массив точек (N×3)

---

## src.openfoam.field_reader

### `FieldReader(case_path: str | Path)`

Читает поля из директории `0/`.

**Методы:**
- `read_all() -> dict[str, dict]` — все поля (`U`, `p`, `k`, ...)
- `read_field(name: str) -> dict` — одно поле: `{internal: ..., boundary: ...}`

---

## src.flowvision.model_mapper

Таблицы маппинга и функции конвертации.

### Константы

- `TURBULENCE_MAP: dict[str, str | None]` — OF -> FV модели турбулентности
- `BC_TYPE_MAP: dict[tuple, str]` — OF -> FV типы граничных условий
- `FIELD_MAP: dict[str, str]` — OF -> FV имена полей

### Функции

| Функция | Сигнатура | Описание |
|---------|-----------|----------|
| `map_turbulence` | `(of_model: str) -> str \| None` | Маппинг модели турбулентности |
| `map_bc_type` | `(of_type: str, field: str \| None) -> str` | Маппинг типа BC |
| `map_field_name` | `(of_field: str) -> str` | Маппинг имени поля |
| `convert_pressure` | `(p_of, rho, pref, is_kinematic) -> float` | Конвертация давления |
| `apply_mapping` | `(project: CAEProject) -> CAEProject` | Заполняет `fv_type` во всех BC |

---

## src.flowvision.template_patcher

### `TemplatePatcher(template_path: str | Path)`

Патчит шаблон `.fvinp` через текстовые замены (regex).

**Методы:**

| Метод | Описание |
|-------|----------|
| `patch_from_project(project)` | Применяет все патчи из CAEProject |
| `patch_general_settings(tref, pref, gravity)` | Патчит CGeneralSettings |
| `patch_initial_conditions(dict)` | Патчит CInitialData (velocity, pressure, VOF) |
| `patch_source_path(stl_path)` | Заменяет первый `<Source>` |
| `fix_source_paths(fv_install_dir)` | Исправляет Windows-пути |
| `save(output_path)` | Записывает файл |

---

## src.flowvision.stl_exporter

### `export_patch_stl(mesh, patch_name, output_path) -> int`

Экспортирует один патч в бинарный STL. Возвращает количество треугольников.

### `export_all_patches(mesh, output_dir, skip_empty) -> dict[str, int]`

Экспортирует все патчи. Возвращает `{имя_патча: кол-во_треугольников}`.

---

## src.flowvision.project_writer

### `ProjectWriter(project, output_dir, project_name=None)`

Генерирует полный проект FlowVision.

**Методы:**
- `write() -> dict[str, str]` — выполняет конвертацию, возвращает словарь файлов

**Атрибуты:**
- `warnings: list[str]` — предупреждения

---

## verify

### `compare(of_case_dir, fvinp_path) -> list[tuple[str, str, str, str]]`

Сравнивает параметры OF-кейса и `.fvinp`. Возвращает строки:
`(параметр, значение_OF, значение_FV, статус)`.

Статусы: `OK`, `OK (mapped)`, `FAIL`, `~` (приблизительно), `—`.

---

## src.gui

GUI-модуль на PyQt6.

### `MainWindow`

Главное окно: панели ввода, предпросмотра, лога, верификации.

### Workers (QThread)

| Класс | Сигналы | Назначение |
|-------|---------|------------|
| `CaseReaderWorker` | `finished(CAEProject)`, `error(str)` | Парсинг OF-кейса |
| `ConvertWorker` | `finished(dict)`, `error(str)` | Конвертация |
| `VerifyWorker` | `finished(list)`, `error(str)` | Верификация |
