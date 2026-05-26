"""Фоновые потоки для тяжёлых операций конвертера.

Каждый worker запускается в ``QThread`` и взаимодействует
с GUI через Qt-сигналы, не блокируя основной поток.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from src.flowvision.model_mapper import apply_mapping
from src.flowvision.project_writer import ProjectWriter
from src.model import CAEProject
from src.openfoam.case_reader import CaseReader
from src.openfoam.mesh_reader import MeshReader
from src.utils.perf import PerfTimer


class CaseReaderWorker(QThread):
    """Парсит OpenFOAM-кейс в фоновом потоке.

    После завершения атрибут ``mesh`` содержит загруженный ``MeshReader``
    (или ``None`` если polyMesh недоступен). Передавайте его в
    ``ConvertWorker`` чтобы избежать повторной загрузки сетки.

    Signals:
        finished(CAEProject): Результат парсинга.
        error(str): Текст ошибки.
        perf_ready(PerfTimer): Замеры производительности.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    perf_ready = pyqtSignal(object)

    def __init__(self, case_path: str, parent=None) -> None:
        super().__init__(parent)
        self.case_path = case_path
        self.mesh = None

    def run(self) -> None:
        try:
            reader = CaseReader(self.case_path)
            project = reader.read()
            apply_mapping(project)
            self.mesh = reader.mesh
            self.finished.emit(project)
            self.perf_ready.emit(reader.perf)
        except Exception as exc:
            self.error.emit(str(exc))


class ConvertWorker(QThread):
    """Выполняет конвертацию в фоновом потоке.

    Signals:
        finished(dict): Словарь созданных файлов.
        error(str): Текст ошибки.
        perf_ready(PerfTimer): Замеры производительности.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    perf_ready = pyqtSignal(object)

    def __init__(
        self,
        project: CAEProject,
        output_dir: str,
        project_name: str | None = None,
        mesh_reader: MeshReader | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.output_dir = output_dir
        self.project_name = project_name
        self.mesh_reader = mesh_reader

    def run(self) -> None:
        try:
            writer = ProjectWriter(
                self.project, self.output_dir, self.project_name,
                mesh_reader=self.mesh_reader,
            )
            files = writer.write()
            result = {"files": files, "warnings": writer.warnings}
            self.finished.emit(result)
            self.perf_ready.emit(writer.perf)
        except Exception as exc:
            self.error.emit(str(exc))


class VerifyWorker(QThread):
    """Выполняет верификацию в фоновом потоке.

    Signals:
        finished(list): Список строк таблицы сравнения.
        error(str): Текст ошибки.
        perf_ready(PerfTimer): Замеры производительности.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    perf_ready = pyqtSignal(object)

    def __init__(self, of_case: str, fvinp_path: str, parent=None) -> None:
        super().__init__(parent)
        self.of_case = of_case
        self.fvinp_path = fvinp_path

    def run(self) -> None:
        try:
            from src.verification import compare
            timer = PerfTimer()
            with timer.stage("Верификация"):
                rows = compare(self.of_case, self.fvinp_path)
            self.finished.emit(rows)
            self.perf_ready.emit(timer)
        except Exception as exc:
            self.error.emit(str(exc))
