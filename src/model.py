"""Внутренняя модель данных конвертера OpenFOAM -> FlowVision.

Определяет dataclasses, представляющие CAE-проект в формате,
не зависящем от конкретного пакета программ. Используется как
промежуточное представление между парсером OpenFOAM и генератором
FlowVision.

Example:
    >>> from src.model import CAEProject, Substance, PhysicsModel
    >>> air = Substance(name="Air", density=1.225, viscosity=1.789e-5)
    >>> physics = PhysicsModel(case_type="aero", turbulence="SA")
    >>> project = CAEProject(physics=physics, substances=[air], ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PatchInfo:
    """Информация о патче (граничной поверхности) из polyMesh/boundary.

    Attributes:
        name: Имя патча (например, ``inlet``, ``outlet``, ``walls``).
        patch_type: Тип патча OpenFOAM (``patch``, ``wall``, ``empty``,
            ``symmetry``, ``cyclic``).
        n_faces: Количество граней, принадлежащих патчу.
        start_face: Индекс первой грани патча в массиве ``faces``.
    """

    name: str
    patch_type: str
    n_faces: int
    start_face: int


@dataclass
class Substance:
    """Свойства вещества (аналог Substance в FlowVision).

    Плотность и вязкость обязательны; теплофизические свойства
    заполняются только при наличии в проекте OpenFOAM.

    Attributes:
        name: Человекочитаемое имя (``Air``, ``Water``).
        density: Плотность, кг/м³.
        viscosity: Динамическая вязкость, Па·с (``nu * rho``).
        cp: Удельная теплоёмкость, Дж/(кг·К).
        thermal_conductivity: Теплопроводность, Вт/(м·К).
        agg_state: Агрегатное состояние (``Gas``, ``Liquid``, ``Solid``).
    """

    name: str
    density: float
    viscosity: float
    cp: float | None = None
    thermal_conductivity: float | None = None
    agg_state: str = "Gas"


@dataclass
class PhysicsModel:
    """Описание физико-математической модели задачи.

    Attributes:
        case_type: Тип задачи: ``aero``, ``vof``, ``icing``.
        turbulence: Модель турбулентности OF (``kOmegaSST``,
            ``kEpsilon``, ``SpalartAllmaras``, ``laminar``).
        is_compressible: ``True`` для сжимаемых течений.
        gravity: Вектор ускорения свободного падения (x, y, z), м/с².
        solver: Имя солвера OpenFOAM (``incompressibleFluid``,
            ``interFoam`` и т.д.).
    """

    case_type: str
    turbulence: str = "laminar"
    is_compressible: bool = False
    gravity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    solver: str = ""


@dataclass
class BoundaryCondition:
    """Граничное условие на одном патче для одного или нескольких полей.

    Хранит как исходные типы OpenFOAM, так и сконвертированный тип
    FlowVision (заполняется на этапе маппинга).

    Attributes:
        patch_name: Имя патча из ``polyMesh/boundary``.
        of_type: Тип BC поля ``U`` в OpenFOAM (``fixedValue``, ``zeroGradient``, …).
        p_of_type: Тип BC поля ``p``/``p_rgh`` в OpenFOAM.
        fv_type: Тип BC в FlowVision (``Wall``, ``Inlet/Outlet``, …).
        velocity: Значение скорости (вектор) или ``None``.
        pressure: Значение давления или ``None``.
        temperature: Значение температуры или ``None``.
        turb_k: Турбулентная кинетическая энергия или ``None``.
        turb_epsilon: Диссипация турбулентной энергии или ``None``.
        turb_omega: Удельная диссипация или ``None``.
        turb_intensity: Интенсивность турбулентных пульсаций I_t
            (безразмерная, 0–1), вычисляемая из k и |U|.
        turb_scale: Масштаб турбулентных вихрей L_t (м),
            вычисляемый из k и ε/ω.
        vof_alpha: Объёмная доля жидкой фазы (VOF) или ``None``.
    """

    patch_name: str
    of_type: str = ""
    p_of_type: str = ""
    fv_type: str = ""
    velocity: tuple[float, float, float] | None = None
    pressure: float | None = None
    temperature: float | None = None
    turb_k: float | None = None
    turb_epsilon: float | None = None
    turb_omega: float | None = None
    turb_intensity: float | None = None
    turb_scale: float | None = None
    vof_alpha: float | None = None


@dataclass
class CAEProject:
    """Полное описание CAE-проекта в промежуточном формате.

    Собирается из файлов проекта OpenFOAM модулем ``case_reader``
    и используется модулями ``template_patcher`` / ``project_writer``
    для генерации проекта FlowVision.

    Attributes:
        case_path: Абсолютный путь к директории кейса OpenFOAM.
        physics: Описание физической модели.
        substances: Список веществ задачи.
        patches: Информация о патчах (из ``polyMesh/boundary``).
        boundary_conditions: Граничные условия для всех патчей.
        initial_conditions: Начальные условия — словарь
            ``{имя_поля: значение}``.
        tref: Референсная температура, К (для FlowVision).
        pref: Референсное давление, Па (для FlowVision).
        end_time: Время окончания расчёта, с.
        delta_t: Шаг по времени, с.
    """

    case_path: str = ""
    physics: PhysicsModel = field(default_factory=PhysicsModel)
    substances: list[Substance] = field(default_factory=list)
    patches: list[PatchInfo] = field(default_factory=list)
    boundary_conditions: list[BoundaryCondition] = field(default_factory=list)
    initial_conditions: dict[str, Any] = field(default_factory=dict)
    tref: float = 298.0
    pref: float = 101325.0
    end_time: float = 1.0
    delta_t: float = 0.001
