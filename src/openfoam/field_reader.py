"""Чтение полей OpenFOAM из директории ``0/``.

Парсит файлы полей (``U``, ``p``, ``T``, ``k``, ``omega``,
``alpha.water`` и т.д.), извлекая начальные условия
(``internalField``) и граничные условия (``boundaryField``).

Example:
    >>> from src.openfoam.field_reader import FieldReader
    >>> reader = FieldReader("tests/cases/airFoil2D")
    >>> fields = reader.read_all()
    >>> print(fields["U"]["internal"])
    (25.75, 3.62, 0.0)
    >>> print(fields["U"]["boundary"]["walls"]["type"])
    'noSlip'
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.openfoam.dict_parser import parse_file


class FieldReader:
    """Ридер файлов полей из директории ``0/`` кейса OpenFOAM.

    Attributes:
        case_path: Путь к директории кейса.
        fields_dir: Путь к директории ``0/``.
    """

    # Стандартные файлы полей OpenFOAM
    KNOWN_FIELDS = (
        "U", "p", "p_rgh", "T",
        "k", "epsilon", "omega", "nut", "nuTilda",
        "alpha.water", "alpha.water.orig",
    )

    def __init__(self, case_path: str | Path) -> None:
        """Инициализирует FieldReader.

        Args:
            case_path: Путь к директории кейса OpenFOAM.

        Raises:
            FileNotFoundError: Если директория ``0/`` не найдена.
        """
        self.case_path = Path(case_path)
        self.fields_dir = self.case_path / "0"
        if not self.fields_dir.is_dir():
            raise FileNotFoundError(f"Directory 0/ not found: {self.fields_dir}")

    def read_all(self) -> dict[str, dict[str, Any]]:
        """Читает все известные файлы полей из ``0/``.

        Для мультирегионных задач (``0/fluid/``, ``0/solid/``, …)
        рекурсивно обходит подкаталоги и строит иерархический
        словарь ``{регион/поле: {...}}``.

        Returns:
            Словарь ``{имя_поля: {"internal": ..., "boundary": ...}}``.
            Ключ ``internal`` содержит значение ``internalField``
            (скаляр, вектор или ``None``), ключ ``boundary`` — словарь
            ``{имя_патча: {type, value, ...}}``.

        Example:
            >>> reader = FieldReader("tests/cases/airFoil2D")
            >>> data = reader.read_all()
            >>> data["p"]["internal"]
            0.0
        """
        result: dict[str, dict[str, Any]] = {}
        self._read_fields_from(self.fields_dir, result, prefix="")
        return result

    def _read_fields_from(
        self,
        directory: Path,
        result: dict[str, dict[str, Any]],
        prefix: str,
    ) -> None:
        """Рекурсивно читает файлы полей из директории.

        Args:
            directory: Директория для обхода.
            result: Словарь-аккумулятор результатов.
            prefix: Префикс пути (имя региона или пустая строка).
        """
        for entry in directory.iterdir():
            if entry.is_dir():
                region_prefix = f"{prefix}{entry.name}/" if prefix else f"{entry.name}/"
                self._read_fields_from(entry, result, region_prefix)
            elif entry.is_file():
                key = f"{prefix}{entry.name}" if prefix else entry.name
                try:
                    data = parse_file(entry)
                    foam_file = data.get("FoamFile", {})
                    field_class = (foam_file.get("class", "")
                                   if isinstance(foam_file, dict) else "")
                    internal = self._parse_internal_field(
                        data.get("internalField"))
                    boundary = data.get("boundaryField", {})
                    result[key] = {
                        "internal": internal,
                        "boundary": boundary,
                        "dimensions": data.get("dimensions", ""),
                        "class": field_class,
                    }
                except (ValueError, KeyError):
                    continue

    def read_field(self, field_name: str) -> dict[str, Any]:
        """Читает один файл поля из ``0/``.

        Args:
            field_name: Имя файла поля (``U``, ``p``, ``alpha.water`` и т.д.).

        Returns:
            Словарь с ключами:
            - ``internal``: значение ``internalField``
            - ``boundary``: словарь граничных условий по патчам
            - ``dimensions``: строка размерности (если есть)
            - ``class``: класс поля из ``FoamFile``

        Raises:
            FileNotFoundError: Если файл поля не существует.
        """
        fpath = self.fields_dir / field_name
        if not fpath.is_file():
            raise FileNotFoundError(f"Field file not found: {fpath}")

        data = parse_file(fpath)

        foam_file = data.get("FoamFile", {})
        field_class = foam_file.get("class", "") if isinstance(foam_file, dict) else ""

        internal = self._parse_internal_field(data.get("internalField"))
        boundary = data.get("boundaryField", {})

        return {
            "internal": internal,
            "boundary": boundary,
            "dimensions": data.get("dimensions", ""),
            "class": field_class,
        }

    @staticmethod
    def _parse_internal_field(raw: Any) -> Any:
        """Преобразует значение ``internalField`` в числовой формат.

        Args:
            raw: Сырое значение из парсера. Может быть строкой
                (``"uniform 0"``), словарём (``{"uniform": ["1", "0", "0"]}``).

        Returns:
            Число (float), кортеж (для вектора) или ``None``.
        """
        if raw is None:
            return None

        if isinstance(raw, dict):
            uniform = raw.get("uniform")
            if isinstance(uniform, list):
                return tuple(float(x) for x in uniform)
            if isinstance(uniform, str):
                return float(uniform)

        if isinstance(raw, str):
            parts = raw.split()
            if len(parts) == 2 and parts[0] == "uniform":
                try:
                    return float(parts[1])
                except ValueError:
                    return parts[1]
            try:
                return float(raw)
            except ValueError:
                return raw

        return raw
