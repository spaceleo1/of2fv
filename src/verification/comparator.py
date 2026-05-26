"""Логика сравнения параметров OpenFOAM-кейса и FlowVision ``.fvinp``.

Выделено из корневого ``verify.py`` для возможности импорта из любого модуля
без зависимости от текущего рабочего каталога.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.table import Table
    _HAS_RICH = True
except ImportError:  # pragma: no cover
    _HAS_RICH = False

from src.openfoam.case_reader import CaseReader
from src.flowvision.model_mapper import apply_mapping, map_turbulence


# Row type: (parameter, OF value, FV value, match status)
ComparisonRow = tuple[str, str, str, str]


def parse_fvinp(fvinp_path: str | Path) -> dict[str, Any]:
    """Извлекает ключевые параметры из ``.fvinp`` XML.

    Args:
        fvinp_path: Путь к файлу ``.fvinp``.

    Returns:
        Словарь с параметрами FlowVision.
    """
    tree = ET.parse(fvinp_path)
    root = tree.getroot()
    result: dict[str, Any] = {}

    gs = root.find('.//OBJECT[@class="CGeneralSettings"]')
    if gs is not None:
        _myid_map = {"0": "tref", "1": "pref",
                     "2": "gravity_x", "3": "gravity_y", "4": "gravity_z"}
        for child in gs.findall('OBJECT[@class="CFvValueConstant"]'):
            key = _myid_map.get(child.get("myid", ""))
            if key:
                result[key] = _safe_float(child.get("Constant", ""))

    for init in root.findall('.//OBJECT[@class="CInitialData"]'):
        for var in init:
            if var.tag != "OBJECT":
                continue
            uname = var.get("UIName", "")
            cls = var.get("class", "")

            if cls == "CIniVarVector" and "Velocity" in uname:
                comps: dict[str, float] = {}
                for sub in var.findall('OBJECT[@class="CFvValueConstant"]'):
                    comps[sub.get("myid", "")] = _safe_float(sub.get("Constant", "0"))
                result["vel_x"] = comps.get("0", 0.0)
                result["vel_y"] = comps.get("1", 0.0)
                result["vel_z"] = comps.get("2", 0.0)

            elif cls == "CIniVarScalar" and "Pressure" in uname:
                sub = var.find('OBJECT[@class="CFvValueConstant"]')
                if sub is not None:
                    result["pressure_ic"] = _safe_float(sub.get("Constant", "0"))

            elif cls == "CIniVarScalar" and "VOF" in uname:
                sub = var.find('OBJECT[@class="CFvValueConstant"]')
                if sub is not None:
                    result["vof_ic"] = _safe_float(sub.get("Constant", "0"))

            elif cls == "CIniVarScalar" and "Temperature" in uname:
                sub = var.find('OBJECT[@class="CFvValueConstant"]')
                if sub is not None:
                    result["temperature_ic"] = _safe_float(sub.get("Constant", "0"))

    return result


def compare(of_case_dir: str, fvinp_path: str) -> list[ComparisonRow]:
    """Сравнивает параметры OpenFOAM-кейса и FlowVision ``.fvinp``.

    Args:
        of_case_dir: Путь к директории кейса OpenFOAM.
        fvinp_path: Путь к сгенерированному ``.fvinp``.

    Returns:
        Список строк таблицы: ``(параметр, значение_OF, значение_FV, статус)``.
    """
    reader = CaseReader(of_case_dir)
    project = reader.read()
    apply_mapping(project)
    fv = parse_fvinp(fvinp_path)

    rows: list[ComparisonRow] = []

    rows.append(("Case type", project.physics.case_type, Path(fvinp_path).stem, "—"))

    of_turb = project.physics.turbulence
    fv_turb = map_turbulence(of_turb) or "laminar"
    rows.append(("Turbulence", of_turb, fv_turb, "OK (mapped)"))

    if project.substances:
        s = project.substances[0]
        rows.append(("Substance", f"{s.name}, rho={s.density}", "(from FV database)", "~"))

    of_tref = project.tref
    fv_tref = fv.get("tref")
    rows.append(("Tref (K)", _fmt(of_tref), _fmt(fv_tref), _match(of_tref, fv_tref)))

    of_pref = project.pref
    fv_pref = fv.get("pref")
    rows.append(("Pref (Pa)", _fmt(of_pref), _fmt(fv_pref), _match(of_pref, fv_pref)))

    of_g = project.physics.gravity
    fv_g = (fv.get("gravity_x", 0.0), fv.get("gravity_y", 0.0), fv.get("gravity_z", 0.0))
    g_ok = all(_match(of_g[i], fv_g[i]) == "OK" for i in range(3))
    rows.append(("Gravity (m/s²)", _fmt(of_g), _fmt(fv_g), "OK" if g_ok else "FAIL"))

    ic = project.initial_conditions
    of_vel = ic.get("U")
    if isinstance(of_vel, tuple) and len(of_vel) >= 3:
        fv_vel = (fv.get("vel_x"), fv.get("vel_y"), fv.get("vel_z"))
        if all(v is not None for v in fv_vel):
            vel_ok = all(_match(of_vel[i], fv_vel[i]) == "OK" for i in range(3))
            rows.append(("Velocity IC (m/s)", _fmt(of_vel), _fmt(fv_vel),
                         "OK" if vel_ok else "FAIL"))
        else:
            rows.append(("Velocity IC (m/s)", _fmt(of_vel), "—", "—"))
    elif of_vel is not None:
        rows.append(("Velocity IC (m/s)", _fmt(of_vel), "—", "—"))

    of_p = ic.get("p", ic.get("p_rgh"))
    fv_p = fv.get("pressure_ic")
    if of_p is not None:
        rows.append(("Pressure IC (Pa)", _fmt(of_p), _fmt(fv_p),
                     _match(of_p, fv_p) if fv_p is not None else "—"))

    of_alpha = ic.get("alpha.water", ic.get("alpha.water.orig"))
    fv_alpha = fv.get("vof_ic")
    if of_alpha is not None:
        rows.append(("VOF IC", _fmt(of_alpha), _fmt(fv_alpha),
                     _match(of_alpha, fv_alpha) if fv_alpha is not None else "—"))

    for bc in project.boundary_conditions:
        fv_type = bc.fv_type or "(unmapped)"
        rows.append((
            f"BC[{bc.patch_name}]",
            f"{bc.of_type} -> {fv_type}",
            fv_type,
            "OK" if bc.fv_type else "—",
        ))
        if bc.turb_intensity is not None:
            rows.append((
                f"  Turb I_t [{bc.patch_name}]",
                f"k={_fmt(bc.turb_k)}",
                f"I_t={bc.turb_intensity:.4g}",
                "OK (converted)",
            ))
        if bc.turb_scale is not None:
            src = (f"ε={_fmt(bc.turb_epsilon)}" if bc.turb_epsilon is not None
                   else f"ω={_fmt(bc.turb_omega)}")
            rows.append((
                f"  Turb L_t [{bc.patch_name}]",
                src,
                f"L_t={bc.turb_scale:.4g} m",
                "OK (converted)",
            ))

    return rows


def print_table(rows: list[ComparisonRow], title: str = "") -> None:
    """Выводит таблицу сравнения в терминал."""
    if _HAS_RICH:
        console = Console()
        table = Table(title=title or "OF vs FV Comparison", show_lines=True)
        table.add_column("Parameter", style="cyan", min_width=20)
        table.add_column("OpenFOAM", style="green")
        table.add_column("FlowVision (.fvinp)", style="yellow")
        table.add_column("Match?", style="bold")

        for param, of_val, fv_val, match in rows:
            if match in ("OK", "OK (mapped)", "OK (converted)"):
                match_cell = f"[green]{match}[/green]"
            elif match == "FAIL":
                match_cell = f"[red bold]{match}[/red bold]"
            elif match == "~":
                match_cell = f"[yellow]{match}[/yellow]"
            else:
                match_cell = match
            table.add_row(param, of_val, fv_val, match_cell)

        console.print(table)
    else:  # pragma: no cover
        print(f"\n{'=' * 80}")
        print(title or "OF vs FV Comparison")
        print(f"{'=' * 80}")
        print(f"{'Parameter':<25} {'OpenFOAM':<25} {'FlowVision':<25} {'Match?':<8}")
        print(f"{'-' * 83}")
        for param, of_val, fv_val, match in rows:
            print(f"{param:<25} {of_val:<25} {fv_val:<25} {match:<8}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_float(val: str) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return float("nan")


def _fmt(val: Any) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        if val == int(val) and abs(val) < 1e10:
            return str(int(val))
        return f"{val:.6g}"
    if isinstance(val, tuple):
        return "(" + ", ".join(_fmt(v) for v in val) + ")"
    return str(val)


def _match(of_val: Any, fv_val: Any, tolerance: float = 1e-6) -> str:
    if of_val is None or fv_val is None:
        return "—"
    if isinstance(of_val, (int, float)) and isinstance(fv_val, (int, float)):
        if abs(of_val - fv_val) < tolerance * max(1.0, abs(of_val)):
            return "OK"
        return "FAIL"
    if isinstance(of_val, str) and isinstance(fv_val, str):
        return "OK" if of_val.lower() == fv_val.lower() else "~"
    return "—"
