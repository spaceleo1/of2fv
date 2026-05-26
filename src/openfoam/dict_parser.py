"""Парсер формата OpenFOAM dictionary (foam dict).

Рекурсивно разбирает текстовые файлы OpenFOAM, возвращая вложенные
словари Python. Поддерживает:

- Однострочные ``//`` и блочные ``/* ... */`` комментарии
- Вложенные блоки ``key { ... }``
- Списки ``key ( ... )`` и ``N ( ... )`` (с предшествующим счётчиком)
- Значения с размерностью ``[0 2 -1 0 0 0 0]``
- Ссылки на переменные ``$internalField``
- Директиву ``#include "..."`` (рекурсивное включение)
- Заголовок ``FoamFile { ... }``

Example:
    >>> from src.openfoam.dict_parser import parse_file
    >>> data = parse_file("tests/cases/airFoil2D/system/controlDict")
    >>> data["endTime"]
    '500'
    >>> data["solver"]
    'incompressibleFluid'
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_file(filepath: str | Path) -> dict[str, Any]:
    """Читает и парсит файл формата OpenFOAM dictionary.

    Args:
        filepath: Путь к файлу OpenFOAM.

    Returns:
        Словарь с разобранными ключами и значениями.

    Raises:
        FileNotFoundError: Если файл не существует.
        ValueError: Если формат файла некорректен.

    Example:
        >>> data = parse_file("constant/physicalProperties")
        >>> data["nu"]
        '1e-05'
    """
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_comments(text)
    tokens = _tokenize(text)
    result, _ = _parse_block(tokens, 0, path.parent)
    return result


def parse_string(text: str) -> dict[str, Any]:
    """Парсит строку в формате OpenFOAM dictionary.

    Args:
        text: Содержимое файла OpenFOAM.

    Returns:
        Словарь с разобранными ключами и значениями.
    """
    text = _strip_comments(text)
    tokens = _tokenize(text)
    result, _ = _parse_block(tokens, 0, None)
    return result


def _strip_comments(text: str) -> str:
    """Удаляет однострочные и блочные комментарии."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


_TOKEN_RE = re.compile(
    r"""
    (\#include(?:Etc|Func)?\s+"[^"]+")  |  # директива include/includeEtc/includeFunc
    ([{}()\[\];])          |  # спецсимволы
    ("(?:[^"\\]|\\.)*")    |  # строка в кавычках
    ([^\s{}()\[\];]+)         # обычный токен
    """,
    re.VERBOSE,
)


def _tokenize(text: str) -> list[str]:
    """Разбивает текст на токены."""
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        token = m.group(0)
        tokens.append(token)
    return tokens


def _parse_block(
    tokens: list[str],
    pos: int,
    base_dir: Path | None,
) -> tuple[dict[str, Any], int]:
    """Рекурсивно разбирает блок ``{ ... }`` или верхний уровень файла.

    Args:
        tokens: Список токенов.
        pos: Текущая позиция в списке.
        base_dir: Директория файла (для разрешения ``#include``).

    Returns:
        Кортеж ``(словарь, новая_позиция)``.
    """
    result: dict[str, Any] = {}

    while pos < len(tokens):
        token = tokens[pos]

        if token == "}":
            return result, pos + 1

        if token == ";":
            pos += 1
            continue

        if token.startswith("#include"):
            match = re.match(r'#include\s+"([^"]+)"', token)
            if match and base_dir:
                inc_path = base_dir / match.group(1)
                if inc_path.exists():
                    included = parse_file(inc_path)
                    result.update(included)
            # #includeEtc и #includeFunc — системные, пропускаем
            pos += 1
            continue

        key = token.strip('"')
        pos += 1

        if pos >= len(tokens):
            break

        next_token = tokens[pos]

        if next_token == "{":
            pos += 1
            sub_dict, pos = _parse_block(tokens, pos, base_dir)
            result[key] = sub_dict

        elif next_token == "(":
            pos += 1
            items, pos = _parse_list(tokens, pos)
            if key.isdigit():
                result["_list_count"] = int(key)
                result["_list"] = items
            else:
                result[key] = items

        elif next_token == "[":
            dims, pos = _parse_dimensions(tokens, pos)
            value = None
            if pos < len(tokens) and tokens[pos] == ";":
                value = dims
                pos += 1
            elif pos < len(tokens):
                value = tokens[pos]
                pos += 1
                if pos < len(tokens) and tokens[pos] == "(":
                    pos += 1
                    vec, pos = _parse_list(tokens, pos)
                    value = vec
                if pos < len(tokens) and tokens[pos] == ";":
                    pos += 1
            result[key] = value

        else:
            value_parts = [next_token]
            pos += 1

            if pos < len(tokens) and tokens[pos] == "(":
                pos += 1
                vec, pos = _parse_list(tokens, pos)
                if next_token == "uniform" or next_token == "nonuniform":
                    result[key] = {next_token: vec}
                else:
                    result[key] = vec
                if pos < len(tokens) and tokens[pos] == ";":
                    pos += 1
                continue

            while pos < len(tokens) and tokens[pos] not in ("{", "}", ";", "("):
                value_parts.append(tokens[pos])
                pos += 1

            if pos < len(tokens) and tokens[pos] == ";":
                pos += 1

            value = " ".join(value_parts) if len(value_parts) > 1 else value_parts[0]
            result[key] = value

    return result, pos


def _parse_list(tokens: list[str], pos: int) -> tuple[list[Any], int]:
    """Разбирает список ``( ... )``.

    Args:
        tokens: Список токенов.
        pos: Позиция после открывающей скобки ``(``.

    Returns:
        Кортеж ``(список_элементов, новая_позиция)``.
    """
    items: list[Any] = []

    while pos < len(tokens):
        token = tokens[pos]

        if token == ")":
            return items, pos + 1

        if token == "(":
            pos += 1
            sub_list, pos = _parse_list(tokens, pos)
            items.append(sub_list)
        elif token == "{":
            pos += 1
            sub_dict, pos = _parse_block(tokens, pos, None)
            items.append(sub_dict)
        else:
            items.append(token)
            pos += 1

    return items, pos


def _parse_dimensions(
    tokens: list[str], pos: int
) -> tuple[str, int]:
    """Разбирает блок размерности ``[0 2 -1 0 0 0 0]``.

    Args:
        tokens: Список токенов.
        pos: Позиция открывающей скобки ``[``.

    Returns:
        Кортеж ``(строка_размерности, новая_позиция)``.
    """
    dims: list[str] = []
    pos += 1
    while pos < len(tokens) and tokens[pos] != "]":
        dims.append(tokens[pos])
        pos += 1
    if pos < len(tokens):
        pos += 1
    return "[" + " ".join(dims) + "]", pos
