"""Главное окно GUI-приложения конвертера OF -> FV.

Компонует панели ввода, предпросмотра, логов и верификации,
управляет фоновыми задачами через workers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.gui.log_handler import QtLogHandler
from src.gui.panels import InputPanel, LogPanel, PreviewPanel, VerifyPanel
from src.gui.workers import CaseReaderWorker, ConvertWorker, VerifyWorker
from src.model import CAEProject
from src.utils.perf import PerfTimer

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Главное окно конвертера OpenFOAM -> FlowVision."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OF2FV Converter — OpenFOAM -> FlowVision")
        self.setMinimumSize(1000, 650)

        self._project: CAEProject | None = None
        self._fvinp_path: str | None = None
        self._fvproj_path: str | None = None
        self._worker: CaseReaderWorker | ConvertWorker | VerifyWorker | None = None
        self._mesh_reader = None

        self._setup_logging()
        self._build_ui()
        self._build_toolbar()
        self._connect_signals()

        self.statusBar().showMessage("Готово")

    def _setup_logging(self) -> None:
        self._log_handler = QtLogHandler()
        self._log_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.DEBUG)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        self.input_panel = InputPanel()
        root_layout.addWidget(self.input_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.preview_panel = PreviewPanel()
        splitter.addWidget(self.preview_panel)

        right_tabs = QTabWidget()
        self.log_panel = LogPanel()
        self.verify_panel = VerifyPanel()
        right_tabs.addTab(self.log_panel, "Лог")
        right_tabs.addTab(self.verify_panel, "Верификация")
        splitter.addWidget(right_tabs)

        splitter.setSizes([500, 500])
        root_layout.addWidget(splitter, stretch=1)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Действия")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.act_load = QAction("Загрузить кейс", self)
        self.act_load.setToolTip("Прочитать и распознать OpenFOAM кейс")
        toolbar.addAction(self.act_load)

        self.act_convert = QAction("Конвертировать", self)
        self.act_convert.setEnabled(False)
        toolbar.addAction(self.act_convert)

        self.act_verify = QAction("Верифицировать", self)
        self.act_verify.setEnabled(False)
        toolbar.addAction(self.act_verify)

        self.act_open_fv = QAction("Открыть в FlowVision", self)
        self.act_open_fv.setEnabled(False)
        toolbar.addAction(self.act_open_fv)

    def _connect_signals(self) -> None:
        self.input_panel.case_selected.connect(self._on_load_case)
        self.act_load.triggered.connect(self._on_load_triggered)
        self.act_convert.triggered.connect(self._on_convert)
        self.act_verify.triggered.connect(self._on_verify)
        self.act_open_fv.triggered.connect(self._on_open_fv)
        self._log_handler.signal.message.connect(self.log_panel.append_message)

    def _on_load_triggered(self) -> None:
        path = self.input_panel.get_input_path()
        if path:
            self._on_load_case(path)
        else:
            QMessageBox.warning(
                self, "Ошибка", "Укажите путь к директории кейса OpenFOAM."
            )

    def _on_load_case(self, case_path: str) -> None:
        if not Path(case_path).is_dir():
            QMessageBox.warning(
                self, "Ошибка", f"Директория не найдена:\n{case_path}"
            )
            return

        self.statusBar().showMessage("Чтение кейса OpenFOAM...")
        self.preview_panel.clear()
        self.act_convert.setEnabled(False)
        self.act_verify.setEnabled(False)

        self._worker = CaseReaderWorker(case_path)
        self._worker.finished.connect(self._on_case_loaded)
        self._worker.error.connect(self._on_worker_error)
        self._worker.perf_ready.connect(self._on_perf)
        self._worker.start()

    def _on_case_loaded(self, project: CAEProject) -> None:
        self._project = project
        if isinstance(self._worker, CaseReaderWorker):
            self._mesh_reader = self._worker.mesh
        self.preview_panel.load_project(project)
        self.act_convert.setEnabled(True)
        self.statusBar().showMessage(
            f"Кейс загружен: {project.physics.case_type} "
            f"({project.physics.solver})"
        )
        logger.info("Загружен кейс: %s (%s)",
                     project.physics.case_type, project.physics.solver)

        if not self.input_panel.get_output_path():
            case_name = Path(project.case_path).name
            default_out = str(
                Path(project.case_path).parent / f"{case_name}_fv"
            )
            self.input_panel.output_edit.setText(default_out)

    def _on_convert(self) -> None:
        if self._project is None:
            return

        output_dir = self.input_panel.get_output_path()
        if not output_dir:
            QMessageBox.warning(
                self, "Ошибка", "Укажите выходную директорию."
            )
            return

        self.statusBar().showMessage("Конвертация...")
        self.act_convert.setEnabled(False)

        self._worker = ConvertWorker(
            self._project,
            output_dir,
            self.input_panel.get_project_name(),
            mesh_reader=self._mesh_reader,
        )
        self._worker.finished.connect(self._on_convert_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.perf_ready.connect(self._on_perf)
        self._worker.start()

    def _on_convert_done(self, result: dict) -> None:
        files = result["files"]
        warnings = result["warnings"]

        self._fvinp_path = files.get("fvinp")
        self._fvproj_path = files.get("fvproj")

        logger.info("Конвертация завершена: %d файлов", len(files))
        for w in warnings:
            logger.warning(w)

        self.act_convert.setEnabled(True)
        self.act_verify.setEnabled(bool(self._fvinp_path))
        self.act_open_fv.setEnabled(bool(self._fvproj_path))
        self.statusBar().showMessage("Конвертация завершена")

        QMessageBox.information(
            self, "Готово",
            f"Проект FlowVision создан.\n"
            f"Файлов: {len(files)}\n"
            f"Предупреждений: {len(warnings)}",
        )

    def _on_verify(self) -> None:
        if self._project is None or self._fvinp_path is None:
            return

        self.statusBar().showMessage("Верификация...")
        self._worker = VerifyWorker(
            self._project.case_path, self._fvinp_path
        )
        self._worker.finished.connect(self._on_verify_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.perf_ready.connect(self._on_perf)
        self._worker.start()

    def _on_verify_done(self, rows: list) -> None:
        self.verify_panel.load_results(rows)
        n_fail = sum(1 for _, _, _, m in rows if m == "FAIL")
        self.statusBar().showMessage(
            f"Верификация: {'PASS' if n_fail == 0 else f'{n_fail} FAIL'}"
        )
        logger.info("Верификация завершена: %d строк",  len(rows))

    def _on_open_fv(self) -> None:
        if not self._fvproj_path:
            return

        fv_ppp = self._find_fvppp()
        if not fv_ppp:
            QMessageBox.warning(
                self, "FlowVision",
                "FvPPP не найден. Укажите путь к FlowVision в переменной\n"
                "окружения FVPPP или откройте .fvproj вручную.",
            )
            return

        proc = QProcess(self)
        proc.start(fv_ppp, [self._fvproj_path])
        logger.info("Запущен FvPPP: %s %s", fv_ppp, self._fvproj_path)

    @staticmethod
    def _find_fvppp() -> str | None:
        import os
        env_path = os.environ.get("FVPPP")
        if env_path and Path(env_path).is_file():
            return env_path

        candidates = [
            Path(__file__).resolve().parent.parent.parent
            / "flowvision" / "flowvision" / "FvPPP",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    def _on_perf(self, timer: PerfTimer) -> None:
        """Выводит замеры производительности в лог."""
        for name, ms in timer.stages:
            pct = (ms / timer.total_ms * 100) if timer.total_ms > 0 else 0
            self.log_panel.append_message(
                "INFO", f"⏱ {name}: {ms:.1f} мс ({pct:.0f}%)"
            )
        self.log_panel.append_message(
            "INFO", f"⏱ Итого: {timer.total_ms:.1f} мс"
        )

    def _on_worker_error(self, msg: str) -> None:
        logger.error(msg)
        self.statusBar().showMessage("Ошибка")
        QMessageBox.critical(self, "Ошибка", msg)
        self.act_convert.setEnabled(self._project is not None)
