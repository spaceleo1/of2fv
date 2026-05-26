"""Патчинг шаблонов ``.fvinp`` FlowVision данными из ``CAEProject``.

Использует текстовые замены вместо XML-маршалинга, чтобы
не ломать форматирование, от которого зависит парсер FlowVision.
Модификации применяются через ``re.sub`` к исходному тексту файла,
используя уникальный контекст XML-узлов для точного нацеливания.

Формат XML определён эмпирически на основе туториальных проектов
FlowVision 3.16.01.

Example:
    >>> from src.flowvision.template_patcher import TemplatePatcher
    >>> patcher = TemplatePatcher("templates/aero/NACA0012_3deg_00000.fvinp")
    >>> patcher.patch_general_settings(tref=300, pref=101325, gravity=(0, -9.81, 0))
    >>> patcher.save("output/project_00000.fvinp")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.model import CAEProject
from src.flowvision.model_mapper import convert_pressure

logger = logging.getLogger(__name__)


def _fv_num(value: float) -> str:
    """Форматирует число для FlowVision XML атрибутов.

    FlowVision ожидает целые числа без десятичной точки (``298``, ``0``)
    и дробные с полной точностью (``103.83``, ``-9.8000000000000007``).

    Args:
        value: Числовое значение.

    Returns:
        Строковое представление, совместимое с FV XML.
    """
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class TemplatePatcher:
    """Патчер шаблонов FlowVision ``.fvinp`` через текстовые замены.

    Сохраняет оригинальное форматирование XML, заменяя только
    конкретные значения атрибутов и тегов.

    Attributes:
        filepath: Путь к исходному шаблону.
        text: Текст файла шаблона (модифицируемый).
    """

    def __init__(self, template_path: str | Path) -> None:
        """Загружает шаблон ``.fvinp`` как текст.

        Args:
            template_path: Путь к XML-файлу шаблона.

        Raises:
            FileNotFoundError: Если файл не найден.
        """
        self.filepath = Path(template_path)
        self.text = self.filepath.read_text(encoding="utf-8")

    def patch_from_project(self, project: CAEProject) -> None:
        """Применяет все патчи из ``CAEProject`` к шаблону.

        Для несжимаемых солверов (``is_compressible=False``) автоматически
        конвертирует кинематическое давление OpenFOAM (p/ρ, м²/с²) в
        абсолютное давление FlowVision (Па) перед патчингом.

        Args:
            project: Заполненный проект-источник.

        Example:
            >>> patcher = TemplatePatcher("templates/aero/NACA0012_3deg_00000.fvinp")
            >>> patcher.patch_from_project(project)
            >>> patcher.save("output/result_00000.fvinp")
        """
        self.patch_general_settings(
            tref=project.tref,
            pref=project.pref,
            gravity=project.physics.gravity,
        )

        ics = dict(project.initial_conditions)
        if not project.physics.is_compressible:
            rho = project.substances[0].density if project.substances else 1.225
            for p_key in ("p", "p_rgh"):
                if p_key in ics and isinstance(ics[p_key], (int, float)):
                    ics[p_key] = convert_pressure(
                        float(ics[p_key]), rho=rho, pref=project.pref,
                        is_kinematic=True,
                    )
                    logger.debug(
                        "Converted kinematic %s → absolute pressure: %.2f Pa",
                        p_key, ics[p_key],
                    )

        self.patch_initial_conditions(ics)
        self._patch_turbulence_ic(ics)

        logger.info("Template patched with %d BCs, %d ICs",
                    len(project.boundary_conditions),
                    len(project.initial_conditions))

    def patch_general_settings(
        self,
        tref: float = 298.0,
        pref: float = 101325.0,
        gravity: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Патчит ``CGeneralSettings`` — Tref, Pref, гравитацию.

        Внутри блока ``CGeneralSettings`` ищет прямых потомков
        ``CFvValueConstant`` с myid 0..4 и заменяет их ``Constant``.

        Структура (из анализа шаблонов):
        - myid="0" — Tref (K)
        - myid="1" — Pref (Pa)
        - myid="2" — gravity X (м/с²)
        - myid="3" — gravity Y
        - myid="4" — gravity Z

        Args:
            tref: Референсная температура, К.
            pref: Референсное давление, Па.
            gravity: Вектор гравитации ``(gx, gy, gz)``, м/с².
        """
        replacements = {
            "0": _fv_num(tref),
            "1": _fv_num(pref),
            "2": _fv_num(gravity[0]),
            "3": _fv_num(gravity[1]),
            "4": _fv_num(gravity[2]),
        }
        self.text = _patch_block_constants(
            self.text,
            block_class="CGeneralSettings",
            child_class="CFvValueConstant",
            myid_to_value=replacements,
        )
        logger.info("Patched CGeneralSettings: Tref=%s, Pref=%s, g=%s",
                    tref, pref, gravity)

    def patch_initial_conditions(
        self, initial_conditions: dict[str, Any]
    ) -> None:
        """Патчит начальные условия в блоке ``CInitialData``.

        Ищет ``CIniVarVector`` (Velocity) и ``CIniVarScalar`` (Pressure,
        Temperature, VOF) внутри ``CInitialData`` и заменяет значения
        ``Constant`` в их дочерних ``CFvValueConstant``.

        Args:
            initial_conditions: Словарь ``{имя_поля: значение}``.
                Скалярные значения — float, векторные — tuple.
        """
        vel = initial_conditions.get("U")
        if isinstance(vel, tuple) and len(vel) >= 3:
            self._patch_velocity_ic(vel)

        p = initial_conditions.get("p", initial_conditions.get("p_rgh"))
        if isinstance(p, (int, float)):
            self._patch_scalar_ic("Pressure", float(p))

        alpha = initial_conditions.get("alpha.water",
                                       initial_conditions.get("alpha.water.orig"))
        if isinstance(alpha, (int, float)):
            self._patch_scalar_ic("VOF", float(alpha))

    def _patch_velocity_ic(self, vel: tuple[float, float, float]) -> None:
        """Патчит вектор скорости в ``CIniVarVector`` (Velocity).

        Внутри блока Velocity — 3 ``CFvValueConstant`` с myid 0,1,2
        (компоненты Vx, Vy, Vz).

        Args:
            vel: Вектор скорости (Vx, Vy, Vz).
        """
        marker = re.search(
            r'<OBJECT\s+class="CIniVarVector"[^>]*UIName="Velocity[^"]*"',
            self.text,
        )
        if not marker:
            logger.warning("CIniVarVector 'Velocity' not found in template")
            return

        bounds = _extract_nested_block(self.text[marker.start():], "CIniVarVector")
        if bounds is None:
            logger.warning("Could not find end of CIniVarVector block")
            return

        abs_start = marker.start() + bounds[0]
        abs_end = marker.start() + bounds[1]
        block = self.text[abs_start:abs_end]

        new_block = _replace_constant_in_block(block, "0", _fv_num(vel[0]))
        new_block = _replace_constant_in_block(new_block, "1", _fv_num(vel[1]))
        new_block = _replace_constant_in_block(new_block, "2", _fv_num(vel[2]))

        self.text = self.text[:abs_start] + new_block + self.text[abs_end:]
        logger.info("Patched Velocity IC: (%s, %s, %s)", *vel)

    def _patch_scalar_ic(self, var_name: str, value: float) -> None:
        """Патчит скалярное начальное условие (Pressure, Temperature, VOF).

        Ищет ``CIniVarScalar`` с UIName, содержащим ``var_name``,
        и заменяет ``Constant`` в его единственном ``CFvValueConstant``.

        Args:
            var_name: Подстрока UIName (``Pressure``, ``Temperature``, ``VOF``).
            value: Новое значение.
        """
        marker = re.search(
            rf'<OBJECT\s+class="CIniVarScalar"[^>]*UIName="{var_name}[^"]*"',
            self.text,
        )
        if not marker:
            logger.debug("CIniVarScalar '%s' not found in template", var_name)
            return

        bounds = _extract_nested_block(self.text[marker.start():], "CIniVarScalar")
        if bounds is None:
            logger.debug("Could not find end of CIniVarScalar '%s'", var_name)
            return

        abs_start = marker.start() + bounds[0]
        abs_end = marker.start() + bounds[1]
        block = self.text[abs_start:abs_end]

        new_block = _replace_constant_in_block(block, "0", _fv_num(value))
        self.text = self.text[:abs_start] + new_block + self.text[abs_end:]
        logger.info("Patched %s IC: %s", var_name, value)

    def _patch_turbulence_ic(self, initial_conditions: dict[str, Any]) -> None:
        """Патчит начальные условия Pulsations (I_t) и Turbulent scale (L_t).

        Ищет ``CIniVarScalar`` с UIName содержащим ``Pulsations`` и
        ``Turbulent scale`` и заменяет значения ``Constant`` в их
        дочерних ``CFvValueConstant``.

        Args:
            initial_conditions: Словарь начальных условий, содержащий
                ключи ``turb_intensity_ic`` и ``turb_scale_ic``.
        """
        intensity = initial_conditions.get("turb_intensity_ic")
        if isinstance(intensity, (int, float)):
            self._patch_scalar_ic("Pulsations", float(intensity))

        scale = initial_conditions.get("turb_scale_ic")
        if isinstance(scale, (int, float)):
            self._patch_scalar_ic("Turbulent scale", float(scale))

    def patch_source_path(self, stl_path: str) -> None:
        """Заменяет первый путь к геометрии (тег ``<Source>``) в шаблоне.

        Args:
            stl_path: Абсолютный путь к STL-файлу.
        """
        self.text = re.sub(
            r"(<Source>)([^<]*)(</Source>)",
            rf"\g<1>{re.escape(stl_path)}\g<3>",
            self.text,
            count=1,
        )
        logger.debug("Set Source = %s", stl_path)

    def fix_source_paths(self, fv_install_dir: str) -> None:
        """Исправляет абсолютные Windows-пути в тегах ``<Source>``.

        Шаблоны FlowVision содержат абсолютные Windows-пути
        (``C:\\Program Files\\FlowVision-3.16.01\\...``). Заменяет
        их на реальные пути к файлам в установке FlowVision на Linux.

        Args:
            fv_install_dir: Путь к директории FlowVision.
        """
        def _fix(match: re.Match) -> str:
            old_path = match.group(2)
            filename = old_path.rstrip().split("\\")[-1].split("/")[-1]
            if not filename:
                return match.group(0)
            for candidate in Path(fv_install_dir).rglob(filename):
                new_path = str(candidate)
                logger.debug("Fixed Source: %s -> %s", old_path.strip(), new_path)
                return f"{match.group(1)}{new_path}{match.group(3)}"
            logger.warning("Could not find %s in %s", filename, fv_install_dir)
            return match.group(0)

        self.text = re.sub(
            r"(<Source>)([^<]*)(</Source>)",
            _fix,
            self.text,
        )

    def save(self, output_path: str | Path) -> None:
        """Сохраняет модифицированный шаблон, сохраняя оригинальное форматирование.

        Args:
            output_path: Путь для записи.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.text, encoding="utf-8")
        logger.info("Saved patched template: %s", output_path)


def _extract_nested_block(text: str, block_class: str) -> tuple[int, int] | None:
    """Находит границы блока ``<OBJECT class="block_class" ...>...</OBJECT>`` с учётом вложенности.

    Args:
        text: Полный текст XML.
        block_class: Значение атрибута ``class`` искомого блока.

    Returns:
        ``(start, end)`` или ``None`` если не найден.
    """
    start_pat = re.compile(rf'<OBJECT\s+class="{block_class}"[^>]*>')
    m = start_pat.search(text)
    if not m:
        return None

    start = m.start()
    depth = 0
    i = start
    open_tag = re.compile(r'<OBJECT[\s>]')
    close_tag = "</OBJECT>"

    while i < len(text):
        if text[i:i + 7] == "<OBJECT" and open_tag.match(text[i:]):
            depth += 1
            i += 7
        elif text[i:i + 9] == close_tag:
            depth -= 1
            if depth == 0:
                return (start, i + 9)
            i += 9
        else:
            i += 1
    return None


def _patch_block_constants(
    text: str,
    block_class: str,
    child_class: str,
    myid_to_value: dict[str, str],
) -> str:
    """Заменяет ``Constant`` у прямых потомков ``child_class`` внутри блока ``block_class``.

    Использует нестинг-счётчик для корректного определения границ
    родительского блока (``</OBJECT>`` встречается внутри у потомков).

    Args:
        text: Полный текст XML.
        block_class: Класс родительского OBJECT (``CGeneralSettings``).
        child_class: Класс дочернего OBJECT (``CFvValueConstant``).
        myid_to_value: Словарь ``{myid: новое_значение}``.

    Returns:
        Модифицированный текст.
    """
    bounds = _extract_nested_block(text, block_class)
    if bounds is None:
        logger.warning("Block %s not found", block_class)
        return text

    start, end = bounds
    full_block = text[start:end]
    new_block = full_block

    for myid, new_val in myid_to_value.items():
        new_block = _replace_constant_in_block(new_block, myid, new_val,
                                                child_class=child_class)

    return text[:start] + new_block + text[end:]


def _replace_constant_in_block(
    block: str,
    myid: str,
    new_value: str,
    child_class: str = "CFvValueConstant",
) -> str:
    """Заменяет ``Constant="..."`` у OBJECT с заданным myid внутри блока.

    Args:
        block: XML-фрагмент.
        myid: Значение атрибута ``myid``.
        new_value: Новое значение ``Constant``.
        child_class: Класс объекта.

    Returns:
        Блок с заменённым значением.
    """
    pat = re.compile(
        rf'(<OBJECT\s+class="{child_class}"\s+myid="{myid}"\s+Constant=")([^"]*)',
    )
    new_block, count = pat.subn(rf'\g<1>{new_value}', block, count=1)
    if count == 0:
        logger.debug("No %s myid=%s found in block", child_class, myid)
    return new_block
