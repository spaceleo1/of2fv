"""Верификация соответствия OpenFOAM-проекта сгенерированному FlowVision ``.fvinp``.

Этот модуль содержит логику сравнения, вынесенную из корневого ``verify.py``.
Импортировать следует из этого пакета, а не напрямую из ``verify``.

Example:
    >>> from src.verification import compare, parse_fvinp
    >>> rows = compare("tests/cases/airFoil2D", "output/.../result_00000.fvinp")
"""

from src.verification.comparator import compare, parse_fvinp, print_table

__all__ = ["compare", "parse_fvinp", "print_table"]
