"""Запись итогового проекта FlowVision из ``CAEProject``.

Собирает выходную директорию с:
- Патченным ``.fvinp`` (путь к геометрии)
- Копиями ``.fvproj``, ``.fvctrl`` и бинарных файлов из шаблона
- STL-файлами патчей для импорта геометрии
- Отчётом о конвертации ``conversion_report.txt``

FlowVision чувствителен к точному формату XML: UUID в ``.fvproj``
должны совпадать с бинарными файлами ``.fvbcs``/``.fvgeom``,
а формат ``.fvinp`` нельзя перезаписывать через ``ElementTree``
(сломается парсер). Поэтому используем текстовые замены и
побайтовое копирование бинарных файлов.

Example:
    >>> from src.flowvision.project_writer import ProjectWriter
    >>> writer = ProjectWriter(project, output_dir="output/airFoil2D_fv")
    >>> writer.write()
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from src.model import CAEProject
from src.flowvision.model_mapper import apply_mapping, map_turbulence
from src.flowvision.stl_exporter import export_all_patches
from src.flowvision.template_patcher import TemplatePatcher
from src.openfoam.mesh_reader import MeshReader
from src.utils.perf import PerfTimer
from src.utils.project_fmt import bc_rows, ic_rows, project_info_rows

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
FV_INSTALL_DIR = Path(__file__).resolve().parent.parent.parent / "flowvision" / "flowvision"

TEMPLATE_MAP = {
    "aero": "aero",
    "vof": "vof",
    "icing": "icing",
}

# Расширения файлов FlowVision, необходимых для открытия проекта
_COPY_EXTENSIONS = (
    ".fvbcs", ".fvgeom", ".fvgobj", ".fvstat",
    ".fvgprep", ".fvgprep_b", ".fvview", ".fvresd",
)


class ProjectWriter:
    """Генерирует проект FlowVision из ``CAEProject``.

    Attributes:
        project: Исходный проект-источник.
        output_dir: Директория для выходных файлов.
        project_name: Имя проекта (используется в именах файлов).
        warnings: Список предупреждений при конвертации.
    """

    def __init__(
        self,
        project: CAEProject,
        output_dir: str | Path,
        project_name: str | None = None,
        mesh_reader: MeshReader | None = None,
    ) -> None:
        """Инициализирует ProjectWriter.

        Args:
            project: Заполненный ``CAEProject``.
            output_dir: Директория для выходных файлов.
            project_name: Имя проекта. По умолчанию берётся из
                имени директории кейса.
            mesh_reader: Уже загруженный ``MeshReader`` из ``CaseReader``.
                Если передан, повторная загрузка сетки не выполняется.
        """
        self.project = project
        self.output_dir = Path(output_dir)
        self.project_name = project_name or Path(project.case_path).name
        self.warnings: list[str] = []
        self.perf = PerfTimer()
        self._mesh_reader = mesh_reader

    def write(self) -> dict[str, str]:
        """Выполняет полную генерацию проекта FlowVision.

        Структура выходных директорий::

            output_dir/
              project/          ← чистая директория только для FV-файлов
                *.fvproj, *.fvinp, *.fvctrl, ...
              geometry/         ← STL-файлы
              conversion_report.txt

        FlowVision падает при наличии любых посторонних файлов или
        подпапок в директории проекта, поэтому FV-файлы
        изолированы в ``project/``.

        Returns:
            Словарь ``{тип_файла: путь}`` с созданными файлами.

        Example:
            >>> writer = ProjectWriter(project, "output/test")
            >>> files = writer.write()
            >>> print(files["fvinp"])
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._project_dir = self.output_dir / "project"
        self._project_dir.mkdir(exist_ok=True)
        files: dict[str, str] = {}

        with self.perf.stage("Маппинг OF -> FV"):
            apply_mapping(self.project)

        template_dir = self._get_template_dir()
        template_name = self._get_template_base_name(template_dir)
        self._fv_name = template_name

        with self.perf.stage("Экспорт STL"):
            stl_files = self._export_stl()
            files["stl_dir"] = str(self.output_dir / "geometry")
            for name, path in stl_files.items():
                files[f"stl_{name}"] = path

        with self.perf.stage("Патчинг .fvinp"):
            fvinp_path = self._write_fvinp(template_dir, template_name)
            files["fvinp"] = str(fvinp_path)

        with self.perf.stage("Копирование шаблона"):
            fvproj_path = self._copy_fvproj(template_dir, template_name)
            files["fvproj"] = str(fvproj_path)

            fvctrl_path = self._copy_fvctrl(template_dir, template_name)
            files["fvctrl"] = str(fvctrl_path)

        with self.perf.stage("Копирование бинарных"):
            binaries = self._copy_binaries(template_dir, template_name)
            for ext, path in binaries.items():
                files[ext] = str(path)

        with self.perf.stage("Запись отчёта"):
            report_path = self._write_report()
            files["report"] = str(report_path)

        logger.debug(self.perf.format_summary("ProjectWriter"))

        return files

    def _get_template_dir(self) -> Path:
        """Определяет директорию шаблона по типу задачи."""
        case_type = self.project.physics.case_type
        template_name = TEMPLATE_MAP.get(case_type, "aero")
        tdir = TEMPLATES_DIR / template_name
        if not tdir.is_dir():
            raise FileNotFoundError(
                f"Template directory not found: {tdir} "
                f"(case_type={case_type})"
            )
        return tdir

    @staticmethod
    def _get_template_base_name(template_dir: Path) -> str:
        """Извлекает базовое имя шаблона из ``.fvproj``."""
        fvproj_files = list(template_dir.glob("*.fvproj"))
        if not fvproj_files:
            raise FileNotFoundError(f"No .fvproj in {template_dir}")
        return fvproj_files[0].stem

    def _write_fvinp(self, template_dir: Path, template_name: str) -> Path:
        """Патчит и записывает ``.fvinp``, сохраняя оригинальное форматирование."""
        fvinp_files = list(template_dir.glob("*.fvinp"))
        if not fvinp_files:
            raise FileNotFoundError(f"No .fvinp in {template_dir}")

        patcher = TemplatePatcher(fvinp_files[0])

        if FV_INSTALL_DIR.is_dir():
            patcher.fix_source_paths(str(FV_INSTALL_DIR))

        patcher.patch_from_project(self.project)

        out = self._project_dir / f"{template_name}_00000.fvinp"
        patcher.save(out)

        fv_turb = map_turbulence(self.project.physics.turbulence)
        if fv_turb:
            logger.info("Turbulence: %s -> %s",
                        self.project.physics.turbulence, fv_turb)
        else:
            self.warnings.append(
                f"Turbulence model '{self.project.physics.turbulence}' "
                "has no direct FV equivalent — manual setup required"
            )

        return out

    def _copy_fvproj(self, template_dir: Path, template_name: str) -> Path:
        """Копирует ``.fvproj`` из шаблона без изменения UUID и имени.

        UUID и имя файла должны совпадать с бинарными файлами
        ``.fvbcs``/``.fvgeom``, иначе FlowVision не откроет проект.
        """
        src = template_dir / f"{template_name}.fvproj"
        out = self._project_dir / f"{template_name}.fvproj"
        shutil.copy2(src, out)
        return out

    def _copy_fvctrl(self, template_dir: Path, template_name: str) -> Path:
        """Копирует ``.fvctrl`` из шаблона без изменений."""
        src = template_dir / f"{template_name}.fvctrl"
        out = self._project_dir / f"{template_name}.fvctrl"
        shutil.copy2(src, out)
        return out

    def _copy_binaries(
        self, template_dir: Path, template_name: str
    ) -> dict[str, Path]:
        """Копирует бинарные файлы FlowVision (.fvbcs, .fvgeom и т.д.).

        Имена файлов сохраняются как в шаблоне — FlowVision
        использует имя проекта из ``.fvproj`` для поиска
        соответствующих файлов.

        Args:
            template_dir: Директория шаблона.
            template_name: Базовое имя шаблона.

        Returns:
            Словарь ``{расширение: путь}``.
        """
        result: dict[str, Path] = {}
        for ext in _COPY_EXTENSIONS:
            for src in template_dir.glob(f"*{ext}"):
                out = self._project_dir / src.name
                shutil.copy2(src, out)
                result[ext] = out
                logger.debug("Copied %s", src.name)
        return result

    def _export_stl(self) -> dict[str, str]:
        """Экспортирует патчи polyMesh в STL-файлы.

        STL размещаются в ``output_dir/geometry/``, отдельно от
        директории проекта FlowVision ``output_dir/project/``.
        Если ``mesh_reader`` передан в конструктор, повторная загрузка
        сетки не выполняется.
        """
        stl_dir = self.output_dir / "geometry"
        stl_dir.mkdir(exist_ok=True)
        result: dict[str, str] = {}

        case_path = Path(self.project.case_path)
        poly_dir = case_path / "constant" / "polyMesh"
        if not poly_dir.is_dir():
            self.warnings.append(
                "polyMesh not found — STL export skipped. "
                "Run blockMesh first or provide geometry manually."
            )
            return result

        mesh = self._mesh_reader or MeshReader(case_path)
        counts = export_all_patches(mesh, stl_dir, skip_empty=True)

        for name, n_tris in counts.items():
            stl_path = stl_dir / f"{name}.stl"
            result[name] = str(stl_path)
            logger.info("Exported %s: %d triangles", name, n_tris)

        return result

    def _write_report(self) -> Path:
        """Записывает текстовый отчёт о конвертации."""
        report_path = self.output_dir / "conversion_report.txt"
        lines: list[str] = [
            "OpenFOAM -> FlowVision Conversion Report",
            "=" * 50,
            f"Source: {self.project.case_path}",
            f"Output: {self.output_dir}",
            "",
            "Project parameters:",
        ]

        for param, value in project_info_rows(self.project):
            lines.append(f"  {param}: {value}")
        lines.append("")

        lines.append("Substances:")
        for s in self.project.substances:
            lines.append(f"  {s.name}: rho={s.density}, mu={s.viscosity}, "
                         f"state={s.agg_state}")
        lines.append("")

        lines.append("Boundary Conditions:")
        for patch, of_type, fv_type in bc_rows(self.project):
            lines.append(f"  {patch}: {of_type} -> {fv_type}")
        lines.append("")

        lines.append("Initial Conditions:")
        for of_field, fv_name, value in ic_rows(self.project):
            lines.append(f"  {of_field} ({fv_name}): {value}")
        lines.append("")

        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
            lines.append("")

        fv_name = getattr(self, "_fv_name", self.project_name)
        lines += [
            "Manual steps required after import:",
            f"  1. Open {fv_name}.fvproj in FlowVision PPP",
            "  2. Import STL files from geometry/ (Geometry Preprocessor)",
            "  3. Assign boundary conditions to facet groups",
            "  4. Configure mesh adaptation parameters",
            "  5. Review and adjust solver settings",
        ]

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
