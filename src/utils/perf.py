"""Замеры производительности этапов конвертации.

Предоставляет ``PerfTimer`` — лёгкий контейнер для хронометража
именованных этапов pipeline. Таймер не привязан к конкретному
модулю и может использоваться в CaseReader, ProjectWriter,
верификации и любых других местах.

Example:
    >>> timer = PerfTimer()
    >>> with timer.stage("parse controlDict"):
    ...     parse_file("system/controlDict")
    >>> with timer.stage("read mesh"):
    ...     MeshReader(case_path)
    >>> for name, ms in timer.stages:
    ...     print(f"{name}: {ms:.1f} ms")
    >>> print(f"Total: {timer.total_ms:.1f} ms")
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator


class PerfTimer:
    """Хронометраж именованных этапов.

    Attributes:
        stages: Список пар ``(имя_этапа, длительность_мс)``.
    """

    def __init__(self) -> None:
        self.stages: list[tuple[str, float]] = []
        self._t0: float = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Generator[None, None, None]:
        """Контекстный менеджер для замера одного этапа.

        Args:
            name: Человекочитаемое имя этапа.
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.stages.append((name, elapsed_ms))

    @property
    def total_ms(self) -> float:
        """Суммарное время всех замеренных этапов (мс)."""
        return sum(ms for _, ms in self.stages)

    @property
    def wall_ms(self) -> float:
        """Время от создания таймера до текущего момента (мс)."""
        return (time.perf_counter() - self._t0) * 1000

    def format_summary(self, title: str = "Performance") -> str:
        """Форматированная строка с таблицей замеров.

        Args:
            title: Заголовок таблицы.

        Returns:
            Многострочная строка с выровненными колонками.
        """
        if not self.stages:
            return f"{title}: no measurements"

        max_name = max(len(n) for n, _ in self.stages)
        lines = [f"{title}:"]
        for name, ms in self.stages:
            pct = (ms / self.total_ms * 100) if self.total_ms > 0 else 0
            bar = "█" * int(pct / 5)
            lines.append(f"  {name:<{max_name}}  {ms:>8.1f} ms  {pct:>5.1f}%  {bar}")
        lines.append(f"  {'TOTAL':<{max_name}}  {self.total_ms:>8.1f} ms")
        return "\n".join(lines)
