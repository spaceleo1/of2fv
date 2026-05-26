# Формат проекта OpenFOAM

## Структура директории кейса

```
case/
├── 0/                         # начальные и граничные условия
│   ├── U                      # скорость (volVectorField)
│   ├── p                      # давление (volScalarField)
│   ├── T                      # температура
│   ├── k                      # турб. кин. энергия
│   ├── epsilon / omega        # диссипация
│   ├── nut / nuTilda          # турб. вязкость
│   └── alpha.water            # VOF-фаза (если VoF)
├── constant/
│   ├── polyMesh/              # расчётная сетка
│   │   ├── points             # координаты узлов
│   │   ├── faces              # описание граней
│   │   ├── owner              # принадлежность граней
│   │   ├── neighbour          # соседние ячейки
│   │   └── boundary           # патчи (границы)
│   ├── physicalProperties     # вязкость, плотность (OF 12)
│   ├── momentumTransport      # модель турбулентности (OF 12)
│   └── g                      # вектор гравитации
└── system/
    ├── controlDict            # параметры расчёта
    ├── fvSchemes              # численные схемы
    └── fvSolution             # параметры решателей
```

## Формат foam dictionary

Текстовый формат с C-подобным синтаксисом:

```
FoamFile
{
    format      ascii;
    class       dictionary;
    object      controlDict;
}

application     foamRun;
solver          incompressibleFluid;
endTime         500;
deltaT          1;
```

### Элементы синтаксиса

- **Пара ключ-значение:** `key value;`
- **Вложенный блок:** `key { ... }`
- **Список:** `key ( item1 item2 ... )`
- **Размерность:** `key [0 2 -1 0 0 0 0] value;`
- **Ссылка:** `$internalField`
- **Включение:** `#include "filename"`, `#includeEtc "..."`
- **Комментарии:** `// ...` и `/* ... */`

## polyMesh/points

Формат: количество точек, затем список координат в скобках.

```
21812
(
(-17.5492 0.306481 0)
(-17.5472 0.397851 0)
...
)
```

## polyMesh/faces

Формат: `N(i0 i1 ... iN-1)` — N вершин, затем их индексы.

```
43066
(
4(156 0 78 235)
4(157 236 79 1)
...
)
```

## polyMesh/boundary

Список патчей с метаданными:

```
4
(
inlet
{
    type patch;
    nFaces 134;
    startFace 21254;
}
outlet
{
    type patch;
    nFaces 160;
    startFace 21388;
}
...
)
```

## Файлы полей (0/)

```
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (25.75 3.62 0);
boundaryField
{
    inlet
    {
        type            freestreamVelocity;
        freestreamValue $internalField;
    }
    walls
    {
        type            noSlip;
    }
}
```

## Отличия OpenFOAM 12

- `constant/momentumTransport` вместо `turbulenceProperties`
- `constant/physicalProperties` вместо `transportProperties`
- `solver` в `controlDict` указывает тип физики (`incompressibleFluid`, `incompressibleVoF`)
- `application` обычно `foamRun`
