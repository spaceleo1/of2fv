#!/usr/bin/env python3
"""Точка входа GUI-приложения конвертера OpenFOAM -> FlowVision.

Usage:
    python gui.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OF2FV Converter")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
