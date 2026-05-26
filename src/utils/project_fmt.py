"""Утилиты форматирования ``CAEProject`` для отчётов и превью.

Единственная точка создания строк с описанием проекта.
Используется в CLI (``convert.py``), отчёте (``ProjectWriter``)
и панели предпросмотра GUI.
"""

from __future__ import annotations

from src.flowvision.model_mapper import map_field_name, map_turbulence
from src.model import CAEProject


def project_info_rows(project: CAEProject) -> list[tuple[str, str]]:
    """Возвращает строки ``(параметр, значение)`` для отображения проекта.

    Args:
        project: Заполненный ``CAEProject`` (BC-маппинг уже применён).

    Returns:
        Список пар ``(имя_параметра, строковое_значение)``.
    """
    fv_turb = map_turbulence(project.physics.turbulence) or "laminar"
    rows: list[tuple[str, str]] = [
        ("Тип задачи",           project.physics.case_type),
        ("Солвер (OF)",          project.physics.solver),
        ("Турбулентность (OF)",  project.physics.turbulence),
        ("Турбулентность (FV)",  fv_turb),
        ("Гравитация",           str(project.physics.gravity)),
        ("Референсная T (K)",    str(project.tref)),
        ("Референсное P (Па)",   str(project.pref)),
        ("Вещества", ", ".join(
            f"{s.name} (rho={s.density})" for s in project.substances
        ) or "—"),
        ("Патчи", ", ".join(p.name for p in project.patches) or "—"),
        ("Нач. условия", ", ".join(
            f"{k}={v}" for k, v in project.initial_conditions.items()
        ) or "—"),
        ("endTime",  str(project.end_time)),
        ("deltaT",   str(project.delta_t)),
    ]
    return rows


def bc_rows(project: CAEProject) -> list[tuple[str, str, str]]:
    """Возвращает строки ГУ: ``(патч, OF-тип, FV-тип)``.

    Args:
        project: Проект с применённым BC-маппингом.

    Returns:
        Список троек ``(имя_патча, of_type, fv_type)``.
    """
    return [
        (bc.patch_name, bc.of_type or "—", bc.fv_type or "—")
        for bc in project.boundary_conditions
    ]


def ic_rows(project: CAEProject) -> list[tuple[str, str, str]]:
    """Возвращает строки НУ: ``(OF-поле, FV-переменная, значение)``.

    Args:
        project: Проект с начальными условиями.

    Returns:
        Список троек ``(of_field, fv_name, value)``.
    """
    return [
        (field, map_field_name(field), str(value))
        for field, value in project.initial_conditions.items()
    ]
