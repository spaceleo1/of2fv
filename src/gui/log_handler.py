"""Перенаправление ``logging`` в виджет ``QTextEdit``.

Позволяет отображать все лог-сообщения приложения
в GUI-панели с цветовой маркировкой уровней.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal


class QtLogSignal(QObject):
    """Сигнал для передачи лог-сообщений между потоками."""

    message = pyqtSignal(str, str)  # (level, formatted_message)


class QtLogHandler(logging.Handler):
    """``logging.Handler``, перенаправляющий записи в Qt-сигнал.

    Используется для безопасной передачи лог-сообщений из
    фоновых потоков в GUI-поток через сигнал ``message``.

    Example:
        >>> handler = QtLogHandler()
        >>> handler.signal.message.connect(log_panel.append_message)
        >>> logging.getLogger().addHandler(handler)
    """

    def __init__(self) -> None:
        super().__init__()
        self.signal = QtLogSignal()
        self.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.signal.message.emit(record.levelname, msg)
        except RuntimeError:
            pass
