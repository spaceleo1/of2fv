"""Таблицы маппинга OpenFOAM → FlowVision.

Содержит соответствия моделей турбулентности, типов граничных условий,
а также функции конвертации давления и температуры между системами
отсчёта OpenFOAM и FlowVision.

Источник маппингов: ``flowvision/TASK.md``, раздел 6 и 7.

Example:
    >>> from src.flowvision.model_mapper import map_turbulence, map_bc_type
    >>> map_turbulence("kOmegaSST")
    'SST'
    >>> map_bc_type("noSlip", "U")
    'Wall'
"""

from __future__ import annotations

import logging
import math
from typing import Any

from src.model import BoundaryCondition, CAEProject

logger = logging.getLogger(__name__)


# --- Модели турбулентности (TASK.md §6) ---

TURBULENCE_MAP: dict[str, str | None] = {
    "kOmegaSST":       "SST",
    "kEpsilon":        "KES",
    "realizableKE":    "KEFV",
    "SpalartAllmaras": "SA",
    "Smagorinsky":     "Sm",
    "kOmega":          "SST",      # SST — обобщённая k-omega в FV
    "laminar":         None,
}


# --- Граничные условия (TASK.md §7) ---
# Ключ: (OF_bc_type, field_name | None)
# Значение: FV_bc_type

BC_TYPE_MAP: dict[tuple[str, str | None], str] = {
    ("fixedValue", "U"):                  "Inlet/Outlet",
    ("freestreamVelocity", "U"):          "Non-reflecting",
    ("pressureInletOutletVelocity", "U"): "Inlet/Outlet",
    ("flowRateInletVelocity", "U"):       "Inlet/Outlet",
    ("noSlip", "U"):                      "Wall",
    ("noSlip", None):                     "Wall",
    ("slip", "U"):                        "Symmetry",
    ("zeroGradient", "U"):                "Free outlet",
    ("zeroGradient", None):               "Free outlet",
    ("symmetry", None):                   "Symmetry",
    ("symmetryPlane", None):              "Symmetry",
    ("empty", None):                      "Symmetry",
    ("cyclic", None):                     "Connected",
    ("cyclicAMI", None):                  "Connected",
    ("fixedValue", "T"):                  "Wall",
    ("fixedValue", "p"):                  "Inlet/Outlet",
    ("freestreamPressure", "p"):          "Non-reflecting",
    ("totalPressure", "p"):               "Inlet/Outlet",
    ("freestream", None):                 "Non-reflecting",
}


# --- Переменные FlowVision, соответствующие полям OpenFOAM (TASK.md §8) ---

FIELD_MAP: dict[str, str] = {
    "U":             "Velocity",
    "p":             "Pressure",
    "p_rgh":         "Pressure",
    "T":             "Temperature",
    "k":             "TurbEnergy",
    "epsilon":       "TurbDissipation",
    "omega":         "TurbDissipation specific",
    "alpha.water":   "VOF",
}


def map_turbulence(of_model: str) -> str | None:
    """Преобразует имя модели турбулентности OpenFOAM в FlowVision.

    Args:
        of_model: Имя модели в OpenFOAM (``kOmegaSST``, ``SpalartAllmaras``, …).

    Returns:
        Имя модели в FlowVision (``SST``, ``SA``, …) или ``None`` для
        ламинарного режима.

    Example:
        >>> map_turbulence("kOmegaSST")
        'SST'
        >>> map_turbulence("laminar") is None
        True
    """
    result = TURBULENCE_MAP.get(of_model)
    if result is None and of_model != "laminar":
        logger.warning("Unknown turbulence model '%s' — defaulting to None", of_model)
    return result


def map_bc_type(of_type: str, field: str | None = None) -> str:
    """Преобразует тип граничного условия OpenFOAM в FlowVision.

    Args:
        of_type: Тип BC в OpenFOAM (``fixedValue``, ``noSlip``, …).
        field: Имя поля (``U``, ``p``, ``T``) для уточнения маппинга.

    Returns:
        Тип BC в FlowVision.

    Example:
        >>> map_bc_type("noSlip", "U")
        'Wall'
        >>> map_bc_type("symmetry")
        'Symmetry'
    """
    result = BC_TYPE_MAP.get((of_type, field))
    if result:
        return result

    result = BC_TYPE_MAP.get((of_type, None))
    if result:
        return result

    if "wall" in of_type.lower() or "noSlip" in of_type:
        return "Wall"
    if "slip" in of_type.lower() or "symmetr" in of_type.lower():
        return "Symmetry"
    if "inlet" in of_type.lower() or "outlet" in of_type.lower():
        return "Inlet/Outlet"
    if "freestream" in of_type.lower():
        return "Non-reflecting"

    logger.warning("Unknown BC type '%s' for field '%s' — defaulting to 'Wall'",
                   of_type, field)
    return "Wall"


def map_field_name(of_field: str) -> str:
    """Преобразует имя поля OpenFOAM в имя переменной FlowVision.

    Args:
        of_field: Имя поля OpenFOAM (``U``, ``p``, ``k``, …).

    Returns:
        Имя переменной FlowVision.

    Example:
        >>> map_field_name("k")
        'TurbEnergy'
    """
    return FIELD_MAP.get(of_field, of_field)


def convert_pressure(
    p_of: float,
    rho: float,
    pref: float = 101325.0,
    is_kinematic: bool = True,
) -> float:
    """Конвертирует давление OpenFOAM в абсолютное давление FlowVision.

    В ``simpleFoam`` давление — кинематическое (p/ρ); FlowVision
    использует абсолютное Pabs = Pref + p_dynamic.

    Args:
        p_of: Значение давления из OpenFOAM.
        rho: Плотность вещества, кг/м³.
        pref: Референсное давление FlowVision, Па.
        is_kinematic: ``True`` если давление в OpenFOAM кинематическое.

    Returns:
        Абсолютное давление в Па.

    Example:
        >>> convert_pressure(0.0, rho=1.225, pref=101325.0)
        101325.0
    """
    if is_kinematic:
        p_dynamic = p_of * rho
    else:
        p_dynamic = p_of
    return pref + p_dynamic


def convert_turbulence_params(
    k: float,
    velocity: tuple[float, float, float] | None = None,
    epsilon: float | None = None,
    omega: float | None = None,
    c_mu: float = 0.09,
) -> tuple[float, float | None]:
    """Конвертирует параметры турбулентности OpenFOAM в формат FlowVision.

    Вычисляет интенсивность турбулентных пульсаций I_t и линейный
    масштаб турбулентных вихрей L_t из граничных значений k и ε/ω.

    Формулы из FlowVision doc.pdf (Turb-BC.15–18) и OpenFOAM User Guide:

    - ``I_t = sqrt(2k/3) / |U|``  (Turb-BC.15)
    - ``L_t = C_μ^(3/4) · k^(3/2) / ε``  (Turb-BC.17, k-ε модели)
    - ``L_t = k^(1/2) / (C_μ^(1/4) · ω)``  (Turb-BC.18, k-ω SST)

    Args:
        k: Турбулентная кинетическая энергия, м²/с².
        velocity: Вектор скорости ``(Vx, Vy, Vz)`` для расчёта ``|U|``.
        epsilon: Скорость диссипации ε, м²/с³ (для k-ε моделей).
        omega: Удельная скорость диссипации ω, 1/с (для k-ω SST).
        c_mu: Константа модели (по умолчанию 0.09).

    Returns:
        Кортеж ``(I_t, L_t)``. ``L_t`` может быть ``None``,
        если ни ε ни ω не заданы.

    Example:
        >>> convert_turbulence_params(0.375, velocity=(10, 0, 0), omega=50)
        (0.05, ...)
    """
    if k <= 0:
        return (0.0, 0.0)

    u_mag = math.sqrt(sum(v * v for v in velocity)) if velocity else 0.0

    if u_mag > 1e-10:
        intensity = math.sqrt(2.0 * k / 3.0) / u_mag
    else:
        intensity = 0.05
        logger.warning("Zero velocity on patch — using default I_t=0.05")

    scale: float | None = None
    if epsilon is not None and epsilon > 1e-30:
        scale = c_mu ** 0.75 * k ** 1.5 / epsilon
    elif omega is not None and omega > 1e-30:
        scale = k ** 0.5 / (c_mu ** 0.25 * omega)

    return (intensity, scale)


def apply_mapping(project: CAEProject) -> CAEProject:
    """Применяет маппинг ко всем граничным условиям проекта.

    Заполняет поле ``fv_type`` в каждом ``BoundaryCondition``.
    Стратегия:

    1. Определить тип по полю ``U`` (``of_type``).
    2. Если тип ``U`` пуст или неизвестен — попробовать поле ``p``
       (``p_of_type``).
    3. Если оба пусты — оставить ``"Wall"`` (безопасный дефолт).

    Args:
        project: Проект с заполненными ``of_type``/``p_of_type`` в BC.

    Returns:
        Тот же проект с заполненными ``fv_type``.

    Example:
        >>> project = apply_mapping(project)
        >>> project.boundary_conditions[0].fv_type
        'Wall'
    """
    for bc in project.boundary_conditions:
        if bc.of_type:
            bc.fv_type = map_bc_type(bc.of_type, "U")
        elif bc.p_of_type:
            bc.fv_type = map_bc_type(bc.p_of_type, "p")
        else:
            bc.fv_type = "Wall"

        if bc.turb_k is not None and (
            bc.turb_omega is not None or bc.turb_epsilon is not None
        ):
            intensity, scale = convert_turbulence_params(
                k=bc.turb_k,
                velocity=bc.velocity,
                epsilon=bc.turb_epsilon,
                omega=bc.turb_omega,
            )
            bc.turb_intensity = intensity
            bc.turb_scale = scale
            logger.debug(
                "BC[%s]: k=%.4g → I_t=%.4g, L_t=%s",
                bc.patch_name, bc.turb_k, intensity,
                f"{scale:.4g}" if scale is not None else "N/A",
            )

    _convert_turbulence_ic(project)
    return project


def _convert_turbulence_ic(project: CAEProject) -> None:
    """Конвертирует турбулентные начальные условия k/ε/ω → I_t/L_t.

    Результаты записываются в ``project.initial_conditions``
    под ключами ``turb_intensity_ic`` и ``turb_scale_ic``.
    """
    ic = project.initial_conditions
    k_ic = ic.get("k")
    if not isinstance(k_ic, (int, float)) or k_ic <= 0:
        return

    vel_ic = ic.get("U")
    velocity = vel_ic if isinstance(vel_ic, tuple) and len(vel_ic) >= 3 else None

    eps_ic = ic.get("epsilon")
    omega_ic = ic.get("omega")
    epsilon = float(eps_ic) if isinstance(eps_ic, (int, float)) else None
    omega = float(omega_ic) if isinstance(omega_ic, (int, float)) else None

    if epsilon is None and omega is None:
        return

    intensity, scale = convert_turbulence_params(
        k=float(k_ic), velocity=velocity,
        epsilon=epsilon, omega=omega,
    )
    ic["turb_intensity_ic"] = intensity
    if scale is not None:
        ic["turb_scale_ic"] = scale

    logger.debug("IC: k=%.4g → I_t=%.4g, L_t=%s",
                 k_ic, intensity,
                 f"{scale:.4g}" if scale is not None else "N/A")
