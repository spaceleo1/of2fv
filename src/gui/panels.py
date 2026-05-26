"""Панели GUI-приложения конвертера OF -> FV.

Содержит четыре виджета-панели:

- ``InputPanel``   -- выбор входного OF-кейса, выходной директории
- ``PreviewPanel`` -- таблица параметров распознанного проекта
- ``LogPanel``     -- лог-вывод с цветовой маркировкой
- ``VerifyPanel``  -- таблица результатов верификации
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.model import CAEProject
from src.flowvision.model_mapper import map_turbulence, map_field_name


class InputPanel(QWidget):
    """Панель выбора входных и выходных путей.

    Signals:
        case_selected(str): Выбран путь к OF-кейсу.
    """

    case_selected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        grp = QGroupBox("Пути проекта")
        grp_layout = QVBoxLayout(grp)

        # OF case
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("OpenFOAM кейс:"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Путь к директории кейса...")
        row1.addWidget(self.input_edit)
        self.btn_browse_input = QPushButton("Обзор...")
        self.btn_browse_input.clicked.connect(self._browse_input)
        row1.addWidget(self.btn_browse_input)
        grp_layout.addLayout(row1)

        # Output dir
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Выходная директория:"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Куда сохранить проект FV...")
        row2.addWidget(self.output_edit)
        self.btn_browse_output = QPushButton("Обзор...")
        self.btn_browse_output.clicked.connect(self._browse_output)
        row2.addWidget(self.btn_browse_output)
        grp_layout.addLayout(row2)

        # Project name
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Имя проекта (опц.):"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("По умолчанию — имя кейса")
        row3.addWidget(self.name_edit)
        grp_layout.addLayout(row3)

        layout.addWidget(grp)

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Выберите директорию кейса OpenFOAM"
        )
        if path:
            self.input_edit.setText(path)
            self.case_selected.emit(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Выберите выходную директорию"
        )
        if path:
            self.output_edit.setText(path)

    def get_input_path(self) -> str:
        return self.input_edit.text().strip()

    def get_output_path(self) -> str:
        return self.output_edit.text().strip()

    def get_project_name(self) -> str | None:
        name = self.name_edit.text().strip()
        return name if name else None


class PreviewPanel(QWidget):
    """Таблица параметров распознанного OpenFOAM-проекта."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.label = QLabel("Предпросмотр проекта")
        self.label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(
            ["Параметр", "OpenFOAM", "FlowVision"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.table)

    def load_project(self, project: CAEProject) -> None:
        """Заполняет таблицу данными из ``CAEProject``."""
        rows: list[tuple[str, str, str]] = []

        fv_turb = map_turbulence(project.physics.turbulence) or "laminar"
        rows.append(("Тип задачи", project.physics.case_type, ""))
        rows.append(("Солвер", project.physics.solver, ""))
        rows.append(("Турбулентность", project.physics.turbulence, fv_turb))
        rows.append(("Гравитация", str(project.physics.gravity), ""))
        rows.append(("Tref (K)", str(project.tref), str(project.tref)))
        rows.append(("Pref (Па)", str(project.pref), str(project.pref)))

        for s in project.substances:
            rows.append((
                f"Вещество: {s.name}",
                f"rho={s.density}, mu={s.viscosity}",
                s.agg_state,
            ))

        for key, val in project.initial_conditions.items():
            fv_name = map_field_name(key)
            rows.append((f"НУ: {key}", str(val), fv_name))

        for bc in project.boundary_conditions:
            rows.append((
                f"ГУ: {bc.patch_name}",
                bc.of_type,
                bc.fv_type or "—",
            ))

        self.table.setRowCount(len(rows))
        for i, (param, of_val, fv_val) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(param))
            self.table.setItem(i, 1, QTableWidgetItem(of_val))
            self.table.setItem(i, 2, QTableWidgetItem(fv_val))

    def clear(self) -> None:
        self.table.setRowCount(0)


class LogPanel(QWidget):
    """Панель логов с цветовой маркировкой уровней."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        label = QLabel("Лог")
        label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(label)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text_edit)

    _COLORS = {
        "DEBUG": "#888888",
        "INFO": "#2196F3",
        "WARNING": "#FF9800",
        "ERROR": "#F44336",
        "CRITICAL": "#D32F2F",
    }

    def append_message(self, level: str, message: str) -> None:
        """Добавляет лог-сообщение с цветом уровня."""
        color = self._COLORS.get(level, "#000000")
        html = (
            f'<span style="color:{color}"><b>[{level}]</b> '
            f'{message}</span>'
        )
        self.text_edit.append(html)

    def clear(self) -> None:
        self.text_edit.clear()


class VerifyPanel(QWidget):
    """Таблица результатов верификации OF vs FV."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        label = QLabel("Верификация")
        label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Параметр", "OpenFOAM", "FlowVision", "Статус"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.table)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

    def load_results(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Заполняет таблицу результатами ``verify.compare()``."""
        self.table.setRowCount(len(rows))

        n_ok = n_fail = n_approx = 0
        for i, (param, of_val, fv_val, status) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(param))
            self.table.setItem(i, 1, QTableWidgetItem(of_val))
            self.table.setItem(i, 2, QTableWidgetItem(fv_val))

            item = QTableWidgetItem(status)
            if status in ("OK", "OK (mapped)"):
                item.setForeground(Qt.GlobalColor.darkGreen)
                n_ok += 1
            elif status == "FAIL":
                item.setForeground(Qt.GlobalColor.red)
                n_fail += 1
            elif status == "~":
                item.setForeground(Qt.GlobalColor.darkYellow)
                n_approx += 1
            self.table.setItem(i, 3, item)

        self.summary_label.setText(
            f"Итого: {n_ok} OK, {n_approx} приблиз., {n_fail} FAIL"
        )

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.summary_label.setText("")
