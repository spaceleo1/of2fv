# Формат проекта FlowVision

## Структура проекта

```
ProjectName/
├── ProjectName.fvproj         # XML-индекс проекта (UUID'ы)
├── ProjectName_00000.fvinp    # XML препроцессора (физика, BC, IC)
├── ProjectName.fvctrl         # XML решателя (параметры расчёта)
├── ProjectName.fvview         # XML визуализации
├── ProjectName.fvbcs          # бинарная геометрия (BSP-дерево)
├── ProjectName.fvgeom         # бинарная сетка
└── ProjectName.fvgobj         # бинарные геометрические объекты
```

## .fvproj — индекс проекта

Минимальный XML с UUID для идентификации компонентов:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<FVProject FileVersion="2.1">
  <ProjID>XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX</ProjID>
  <VersionID>...</VersionID>
  <SceneID>...</SceneID>
  <CtrlID>...</CtrlID>
  <GeomPrepID>...</GeomPrepID>
</FVProject>
```

## .fvinp — препроцессор

XML-файл ~14 000 строк с сериализованным графом объектов. Ключевые классы:

### Объектная модель

Каждый объект — элемент `<OBJECT>` с атрибутами:
- `class` — тип (например, `CSubstance`, `CPhase`, `CGeneralSettings`)
- `myid` — уникальный числовой ID внутри файла
- `UIName` — отображаемое имя

### CGeneralSettings

Содержит `CFvValueConstant` для глобальных параметров:
- `myid="0"` → Tref (К)
- `myid="1"` → Pref (Па)
- `myid="2"`, `"3"`, `"4"` → компоненты гравитации (gx, gy, gz)

### CSubstance

Свойства вещества — плотность, вязкость, теплоёмкость и т.д.
Вложенные `CSubstancePropertyDens`, `CSubstancePropertyVisc`.

### CBCondition

Граничное условие — тип (Wall, Inlet/Outlet, Symmetry, ...) и параметры.

### CInitialData

Начальные условия — скорость, давление, температура, турб. параметры.

## .fvctrl — параметры решателя

XML с настройками: шаг по времени, число итераций, критерии сходимости.
Обычно копируется из шаблона без изменений.

## Геометрия

FlowVision импортирует геометрию из STL-файлов:
- Binary STL (80 байт заголовок + uint32 count + треугольники)
- Каждый STL-файл = один патч / группа фасеток
- Путь к STL записывается в тег `<Source>` в `.fvinp`

## Типы граничных условий FlowVision

| Тип FV | Описание |
|--------|----------|
| Wall | Стенка (no-slip / slip) |
| Inlet/Outlet | Вход/выход с заданными параметрами |
| Free outlet | Свободный выход (zeroGradient) |
| Symmetry | Плоскость симметрии |
| Non-reflecting | Неотражающее условие (freestream) |
| Connected | Периодическое/циклическое сопряжение |
