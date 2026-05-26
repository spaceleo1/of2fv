#!/usr/bin/env python3
"""CLI-интерфейс конвертера OpenFOAM -> FlowVision.

Читает проект OpenFOAM, определяет тип задачи, экспортирует
геометрию в STL и генерирует проект FlowVision на основе
шаблона.

Usage:
    python convert.py --input tests/cases/airFoil2D --output output/airFoil2D_fv
    python convert.py -i tests/cases/damBreak -o output/damBreak_fv
    python convert.py -i tests/cases/airFoil2D -o output/test --name MyProject
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.openfoam.case_reader import CaseReader
from src.flowvision.model_mapper import apply_mapping
from src.flowvision.project_writer import ProjectWriter
from src.utils.project_fmt import bc_rows, project_info_rows

console = Console()


def main() -> int:
    """Точка входа CLI.

    Returns:
        Код возврата: 0 при успехе, 1 при ошибке.
    """
    parser = argparse.ArgumentParser(
        description="Конвертер проектов OpenFOAM -> FlowVision",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python convert.py -i tests/cases/airFoil2D -o output/airFoil2D_fv\n"
            "  python convert.py -i tests/cases/damBreak -o output/damBreak_fv\n"
        ),
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Путь к директории кейса OpenFOAM",
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Директория для выходного проекта FlowVision",
    )
    parser.add_argument(
        "-n", "--name",
        default=None,
        help="Имя проекта FlowVision (по умолчанию — имя кейса)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Подробный вывод (уровень DEBUG)",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
    )

    input_path = Path(args.input)
    if not input_path.is_dir():
        console.print(f"[red]Ошибка:[/] директория не найдена: {input_path}")
        return 1

    console.print(Panel(
        f"[bold]OpenFOAM -> FlowVision Converter[/]\n"
        f"Input:  {input_path.resolve()}\n"
        f"Output: {Path(args.output).resolve()}",
        title="OF2FV",
    ))

    try:
        console.print("[dim]Чтение проекта OpenFOAM...[/]")
        reader = CaseReader(input_path)
        project = reader.read()

        _print_project_info(project)

        console.print("[dim]Генерация проекта FlowVision...[/]")
        writer = ProjectWriter(
            project,
            output_dir=args.output,
            project_name=args.name,
            mesh_reader=reader.mesh,
        )
        files = writer.write()

        _print_results(files, writer.warnings)
        _print_perf(reader, writer)

    except FileNotFoundError as e:
        console.print(f"[red]Ошибка:[/] {e}")
        return 1
    except Exception as e:
        console.print(f"[red]Критическая ошибка:[/] {e}")
        logging.exception("Unexpected error")
        return 1

    return 0


def _print_project_info(project) -> None:
    """Выводит информацию о распознанном проекте."""
    apply_mapping(project)

    table = Table(title="Распознанный проект OpenFOAM")
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение")
    for name, value in project_info_rows(project):
        table.add_row(name, value)
    console.print(table)
    console.print()

    bc_table = Table(title="Граничные условия")
    bc_table.add_column("Патч", style="cyan")
    bc_table.add_column("OF тип")
    bc_table.add_column("FV тип")
    for patch, of_type, fv_type in bc_rows(project):
        bc_table.add_row(patch, of_type, fv_type)
    console.print(bc_table)
    console.print()


def _print_results(files: dict[str, str], warnings: list[str]) -> None:
    """Выводит результаты конвертации."""
    console.print("[bold green]Конвертация завершена![/]\n")

    table = Table(title="Созданные файлы")
    table.add_column("Тип", style="cyan")
    table.add_column("Путь")

    for ftype, fpath in files.items():
        if not ftype.startswith("stl_"):
            table.add_row(ftype, fpath)

    stl_count = sum(1 for k in files if k.startswith("stl_"))
    if stl_count:
        table.add_row("STL файлы", f"{stl_count} шт. в {files.get('stl_dir', '')}")

    console.print(table)

    if warnings:
        console.print()
        for w in warnings:
            console.print(f"[yellow]  WARN:[/] {w}")

    console.print()
    console.print("[dim]Следующие шаги:[/]")
    console.print("  1. Импортируйте STL из geometry/ в FlowVision ППП")
    console.print("  2. Назначьте граничные условия на группы фасеток")
    console.print("  3. Настройте адаптацию расчётной сетки")
    console.print("  4. Проверьте и скорректируйте параметры решателя")


def _print_perf(reader, writer) -> None:
    """Выводит замеры производительности этапов конвертации."""
    table = Table(title="Производительность")
    table.add_column("Этап", style="cyan")
    table.add_column("Время (мс)", justify="right")
    table.add_column("%", justify="right")

    all_stages = reader.perf.stages + writer.perf.stages
    total = sum(ms for _, ms in all_stages) or 1

    for name, ms in all_stages:
        pct = ms / total * 100
        table.add_row(name, f"{ms:.1f}", f"{pct:.0f}%")

    table.add_row(
        "[bold]ИТОГО[/]",
        f"[bold]{total:.1f}[/]",
        "[bold]100%[/]",
        style="bold",
    )
    console.print(table)


if __name__ == "__main__":
    sys.exit(main())
