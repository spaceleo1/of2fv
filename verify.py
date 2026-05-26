#!/usr/bin/env python3
"""CLI для верификации конвертации OpenFOAM → FlowVision.

Тонкая обёртка над ``src.verification``. Вся логика сравнения
находится в ``src/verification/comparator.py``.

Usage:
    python verify.py <of_case_dir> <fvinp_path>

Example:
    python verify.py tests/cases/.../airFoil2D output/airFoil2D_fv/project/NACA0012_3deg_00000.fvinp
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.verification import compare, print_table


def main() -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(
        description="Verify OpenFOAM to FlowVision conversion"
    )
    parser.add_argument("of_case", help="Path to OpenFOAM case directory")
    parser.add_argument("fvinp", help="Path to generated .fvinp file")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(name)s %(levelname)s: %(message)s",
    )

    of_case = Path(args.of_case)
    fvinp = Path(args.fvinp)

    if not of_case.is_dir():
        print(f"Error: OF case not found: {of_case}", file=sys.stderr)
        return 1
    if not fvinp.is_file():
        print(f"Error: .fvinp not found: {fvinp}", file=sys.stderr)
        return 1

    rows = compare(str(of_case), str(fvinp))
    print_table(rows, title=f"{of_case.name} vs {fvinp.name}")

    n_fail = sum(1 for *_, m in rows if m == "FAIL")
    n_ok = sum(1 for *_, m in rows if m in ("OK", "OK (mapped)"))
    n_approx = sum(1 for *_, m in rows if m == "~")
    print(f"\nSummary: {n_ok} OK, {n_approx} approximate, {n_fail} FAIL")

    return 1 if n_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
