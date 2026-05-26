"""Сборка ``CAEProject`` из директории кейса OpenFOAM.

Определяет тип задачи (аэродинамика, VoF, теплообмен/обледенение),
читает физические свойства, граничные и начальные условия, параметры
расчёта — и собирает всё в промежуточное представление ``CAEProject``.

Поддерживаемые версии формата:
- OpenFOAM 12 (``constant/momentumTransport``, ``constant/physicalProperties``)
- OpenFOAM 6–11 (``constant/turbulenceProperties``, ``constant/transportProperties``)

Example:
    >>> from src.openfoam.case_reader import CaseReader
    >>> reader = CaseReader("tests/cases/airFoil2D")
    >>> project = reader.read()
    >>> print(project.physics.case_type)
    'aero'
    >>> print(project.physics.turbulence)
    'SpalartAllmaras'
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.model import (
    BoundaryCondition,
    CAEProject,
    PatchInfo,
    PhysicsModel,
    Substance,
)
from src.openfoam.dict_parser import parse_file
from src.openfoam.field_reader import FieldReader
from src.openfoam.mesh_reader import MeshReader
from src.utils.perf import PerfTimer

logger = logging.getLogger(__name__)


class CaseReader:
    """Читает проект OpenFOAM и собирает ``CAEProject``.

    Attributes:
        case_path: Абсолютный путь к директории кейса.
        mesh: Экземпляр ``MeshReader`` с загруженной сеткой.
        fields: Экземпляр ``FieldReader``.
    """

    # Солверы OpenFOAM 12, указывающие на VoF-задачу
    _VOF_SOLVERS = {"incompressibleVoF", "compressibleVoF", "interFoam",
                    "compressibleInterFoam", "multiphaseInterFoam",
                    "incompressibleMultiphaseVoF", "compressibleMultiphaseVoF"}

    # Солверы, указывающие на задачу теплообмена/обледенения
    _HEAT_SOLVERS = {"multiRegion", "chtMultiRegionFoam", "buoyantFoam",
                     "buoyantSimpleFoam", "foamMultiRun"}

    def __init__(self, case_path: str | Path) -> None:
        """Инициализирует CaseReader.

        Args:
            case_path: Путь к директории кейса OpenFOAM.

        Raises:
            FileNotFoundError: Если директория ``0/`` не найдена.
        """
        self.case_path = Path(case_path).resolve()
        self.perf = PerfTimer()
        poly_dir = self.case_path / "constant" / "polyMesh"
        if poly_dir.is_dir():
            with self.perf.stage("Загрузка polyMesh"):
                self.mesh: MeshReader | None = MeshReader(self.case_path)
        else:
            logger.warning("polyMesh not found — mesh data unavailable "
                           "(run blockMesh first?): %s", poly_dir)
            self.mesh = None
        self.fields = FieldReader(self.case_path)

    def read(self) -> CAEProject:
        """Читает проект OpenFOAM и собирает CAEProject.

        После вызова ``self.perf`` содержит замеры каждого этапа.

        Returns:
            Заполненный экземпляр ``CAEProject``.

        Example:
            >>> reader = CaseReader("tests/cases/airFoil2D")
            >>> project = reader.read()
            >>> project.physics.turbulence
            'SpalartAllmaras'
        """
        with self.perf.stage("Чтение controlDict"):
            control = self._read_control_dict()

        with self.perf.stage("Определение физики"):
            physics = self._detect_physics(control)

        with self.perf.stage("Чтение веществ"):
            substances = self._read_substances(physics)

        with self.perf.stage("Чтение полей (0/)"):
            fields_data = self.fields.read_all()

        with self.perf.stage("Сборка граничных условий"):
            boundary_conditions = self._build_boundary_conditions(fields_data)

        with self.perf.stage("Сборка начальных условий"):
            initial_conditions = self._build_initial_conditions(fields_data)

        patches = self.mesh.patches if self.mesh else []

        logger.debug(self.perf.format_summary("CaseReader"))

        return CAEProject(
            case_path=str(self.case_path),
            physics=physics,
            substances=substances,
            patches=patches,
            boundary_conditions=boundary_conditions,
            initial_conditions=initial_conditions,
            tref=298.0,
            pref=101325.0,
            end_time=float(control.get("endTime", 1)),
            delta_t=float(control.get("deltaT", 0.001)),
        )

    def _read_control_dict(self) -> dict[str, Any]:
        """Читает ``system/controlDict``."""
        path = self.case_path / "system" / "controlDict"
        return parse_file(path)

    def _detect_physics(self, control: dict[str, Any]) -> PhysicsModel:
        """Определяет тип задачи и физические модели.

        Использует информацию из ``controlDict`` (тип солвера) и
        ``constant/momentumTransport`` (модель турбулентности).

        Args:
            control: Разобранный ``controlDict``.

        Returns:
            Заполненный ``PhysicsModel``.
        """
        solver = control.get("solver", control.get("application", ""))

        case_type = self._classify_case(solver)
        turbulence = self._read_turbulence()
        gravity = self._read_gravity()

        return PhysicsModel(
            case_type=case_type,
            turbulence=turbulence,
            is_compressible="compressible" in solver.lower(),
            gravity=gravity,
            solver=solver,
        )

    def _classify_case(self, solver: str) -> str:
        """Определяет тип задачи по имени солвера.

        Args:
            solver: Имя солвера из ``controlDict``.

        Returns:
            Строка типа задачи: ``aero``, ``vof`` или ``icing``.
        """
        if solver in self._VOF_SOLVERS:
            return "vof"

        alpha_path = self.case_path / "0" / "alpha.water"
        alpha_orig = self.case_path / "0" / "alpha.water.orig"
        if alpha_path.exists() or alpha_orig.exists():
            return "vof"

        if solver in self._HEAT_SOLVERS:
            return "icing"

        constant_dir = self.case_path / "constant"
        if constant_dir.is_dir():
            region_dirs = [d for d in constant_dir.iterdir()
                           if d.is_dir() and d.name != "polyMesh"]
            if any((d / "physicalProperties").exists() for d in region_dirs):
                return "icing"

        return "aero"

    def _read_turbulence(self) -> str:
        """Определяет модель турбулентности из конфигурации.

        Пробует OpenFOAM 12 (``momentumTransport``) и старый формат
        (``turbulenceProperties``).

        Returns:
            Имя модели (``kOmegaSST``, ``SpalartAllmaras``, …)
            или ``laminar``.
        """
        const = self.case_path / "constant"
        search_dirs = [const]
        if const.is_dir():
            search_dirs.extend(
                d for d in sorted(const.iterdir())
                if d.is_dir() and d.name != "polyMesh"
            )

        for parent in search_dirs:
            for filename in ("momentumTransport", "turbulenceProperties"):
                fpath = parent / filename
                if fpath.exists():
                    data = parse_file(fpath)
                    sim_type = data.get("simulationType", "laminar")
                    if sim_type == "laminar":
                        return "laminar"

                    turb_block = data.get(sim_type, {})
                    if isinstance(turb_block, dict):
                        model = turb_block.get("model",
                                               turb_block.get("RASModel",
                                               turb_block.get("LESModel", "")))
                        if model:
                            return model
                    return sim_type

        return "laminar"

    def _read_gravity(self) -> tuple[float, float, float]:
        """Читает вектор гравитации из ``constant/g``.

        Returns:
            Кортеж ``(gx, gy, gz)`` или ``(0, 0, 0)`` если файл отсутствует.
        """
        const = self.case_path / "constant"
        candidates = [const / "g"]
        if const.is_dir():
            candidates.extend(
                d / "g" for d in sorted(const.iterdir())
                if d.is_dir() and d.name != "polyMesh"
            )

        for g_path in candidates:
            if g_path.exists():
                data = parse_file(g_path)
                value = data.get("value")
                if isinstance(value, list) and len(value) >= 3:
                    return (float(value[0]), float(value[1]), float(value[2]))

        return (0.0, 0.0, 0.0)

    def _read_substances(self, physics: PhysicsModel) -> list[Substance]:
        """Читает свойства веществ из ``constant/``.

        Для VoF-задач ищет ``physicalProperties.water`` и
        ``physicalProperties.air``. Для остальных — ``physicalProperties``
        или ``transportProperties``.

        Args:
            physics: Модель физики (для определения типа задачи).

        Returns:
            Список веществ задачи.
        """
        substances: list[Substance] = []
        const = self.case_path / "constant"

        if physics.case_type == "vof":
            for suffix, agg in [("water", "Liquid"), ("air", "Gas")]:
                fpath = const / f"physicalProperties.{suffix}"
                if fpath.exists():
                    data = parse_file(fpath)
                    substances.append(self._substance_from_dict(
                        data, name=suffix.capitalize(), agg_state=agg
                    ))
        elif physics.case_type == "icing":
            for region_dir in sorted(const.iterdir()):
                if not region_dir.is_dir():
                    continue
                for filename in ("physicalProperties", "transportProperties"):
                    fpath = region_dir / filename
                    if fpath.exists():
                        data = parse_file(fpath)
                        substances.append(self._substance_from_dict(
                            data, name=region_dir.name.capitalize(),
                            agg_state="Gas",
                        ))
                        break
            if not substances:
                for filename in ("physicalProperties", "transportProperties"):
                    fpath = const / filename
                    if fpath.exists():
                        data = parse_file(fpath)
                        substances.append(self._substance_from_dict(
                            data, name="Fluid", agg_state="Gas"
                        ))
                        break
        else:
            for filename in ("physicalProperties", "transportProperties"):
                fpath = const / filename
                if fpath.exists():
                    data = parse_file(fpath)
                    substances.append(self._substance_from_dict(
                        data, name="Air", agg_state="Gas"
                    ))
                    break

        return substances

    @staticmethod
    def _substance_from_dict(
        data: dict[str, Any],
        name: str = "Fluid",
        agg_state: str = "Gas",
    ) -> Substance:
        """Создаёт ``Substance`` из разобранного словаря OpenFOAM.

        Поддерживает как простой формат (``rho``, ``nu`` на верхнем уровне),
        так и вложенный ``thermoType`` / ``mixture`` формат OpenFOAM 12.

        Args:
            data: Словарь из ``physicalProperties`` / ``transportProperties``.
            name: Имя вещества.
            agg_state: Агрегатное состояние.

        Returns:
            Экземпляр ``Substance``.
        """
        mixture = data.get("mixture", {})
        eos = mixture.get("equationOfState", {}) if isinstance(mixture, dict) else {}
        thermo = mixture.get("thermodynamics", {}) if isinstance(mixture, dict) else {}
        transport = mixture.get("transport", {}) if isinstance(mixture, dict) else {}

        rho = _to_float(eos.get("rho", data.get("rho", 1.0)))
        nu = _to_float(data.get("nu", 1e-6))
        mu_direct = transport.get("mu")
        mu = _to_float(mu_direct) if mu_direct is not None else nu * rho

        cp = thermo.get("Cp", thermo.get("Cv", data.get("Cp")))
        kappa = transport.get("kappa", data.get("kappa"))

        return Substance(
            name=name,
            density=rho,
            viscosity=mu,
            cp=_to_float(cp) if cp is not None else None,
            thermal_conductivity=(_to_float(kappa) if kappa is not None
                                  else None),
            agg_state=agg_state,
        )

    def _build_boundary_conditions(
        self, fields_data: dict[str, dict[str, Any]]
    ) -> list[BoundaryCondition]:
        """Собирает граничные условия из данных полей.

        Для каждого патча создаётся один ``BoundaryCondition``,
        объединяющий информацию из всех полей (U, p, T, k, omega, alpha).

        Args:
            fields_data: Результат ``FieldReader.read_all()``.

        Returns:
            Список граничных условий.
        """
        patch_names = [p.name for p in self.mesh.patches] if self.mesh else []
        if not patch_names:
            u_boundary = _find_field(fields_data, "U").get("boundary", {})
            patch_names = list(u_boundary.keys())
        bcs: dict[str, BoundaryCondition] = {}

        for pname in patch_names:
            bcs[pname] = BoundaryCondition(patch_name=pname)

        u_data = _find_field(fields_data, "U").get("boundary", {})
        for pname, bc_dict in u_data.items():
            if pname not in bcs or not isinstance(bc_dict, dict):
                continue
            bc = bcs[pname]
            bc.of_type = bc_dict.get("type", "")
            bc.velocity = _extract_vector(bc_dict)

        p_data = _find_field(fields_data, "p")
        if not p_data:
            p_data = _find_field(fields_data, "p_rgh")
        p_boundary = p_data.get("boundary", {}) if isinstance(p_data, dict) else {}
        for pname, bc_dict in p_boundary.items():
            if pname not in bcs or not isinstance(bc_dict, dict):
                continue
            bcs[pname].pressure = _extract_scalar(bc_dict)
            bcs[pname].p_of_type = bc_dict.get("type", "")

        for field_name, attr in [("k", "turb_k"), ("epsilon", "turb_epsilon"),
                                  ("omega", "turb_omega")]:
            fd = _find_field(fields_data, field_name).get("boundary", {})
            for pname, bc_dict in fd.items():
                if pname not in bcs or not isinstance(bc_dict, dict):
                    continue
                val = _extract_scalar(bc_dict)
                if val is not None:
                    setattr(bcs[pname], attr, val)

        alpha_data = _find_field(fields_data, "alpha.water")
        if not alpha_data:
            alpha_data = _find_field(fields_data, "alpha.water.orig")
        alpha_boundary = (alpha_data.get("boundary", {})
                          if isinstance(alpha_data, dict) else {})
        for pname, bc_dict in alpha_boundary.items():
            if pname not in bcs or not isinstance(bc_dict, dict):
                continue
            bcs[pname].vof_alpha = _extract_scalar(bc_dict)

        return list(bcs.values())

    @staticmethod
    def _build_initial_conditions(
        fields_data: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Собирает начальные условия из ``internalField`` всех полей.

        Args:
            fields_data: Результат ``FieldReader.read_all()``.

        Returns:
            Словарь ``{имя_поля: значение_internalField}``.
        """
        ic: dict[str, Any] = {}
        for name, data in fields_data.items():
            internal = data.get("internal")
            if internal is not None:
                ic[name] = internal
        return ic


def _extract_scalar(bc_dict: dict[str, Any]) -> float | None:
    """Извлекает скалярное значение из BC-словаря OpenFOAM."""
    for key in ("value", "freestreamValue", "inletValue"):
        raw = bc_dict.get(key)
        if isinstance(raw, dict) and "uniform" in raw:
            try:
                return float(raw["uniform"])
            except (TypeError, ValueError):
                continue
        if isinstance(raw, str):
            try:
                return float(raw.split()[-1])
            except (ValueError, IndexError):
                continue
    return None


def _extract_vector(
    bc_dict: dict[str, Any],
) -> tuple[float, float, float] | None:
    """Извлекает вектор из BC-словаря OpenFOAM."""
    for key in ("value", "freestreamValue", "inletValue"):
        raw = bc_dict.get(key)
        if isinstance(raw, dict) and "uniform" in raw:
            vec = raw["uniform"]
            if isinstance(vec, list) and len(vec) >= 3:
                try:
                    return (float(vec[0]), float(vec[1]), float(vec[2]))
                except (TypeError, ValueError):
                    continue
    return None


def _find_field(
    fields_data: dict[str, dict[str, Any]], name: str
) -> dict[str, Any]:
    """Ищет поле по имени, в том числе с регионным префиксом.

    Для мультирегионных кейсов ключи имеют вид ``fluid/U``.
    Приоритет: точное совпадение, затем первый ключ ``*/name``.
    """
    if name in fields_data:
        return fields_data[name]
    for key, val in fields_data.items():
        if key.endswith(f"/{name}"):
            return val
    return {}


def _to_float(value: Any) -> float:
    """Безопасное приведение значения к float.

    Args:
        value: Значение из парсера — строка, число или ``None``.

    Returns:
        Число с плавающей точкой.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
