"""
ClipForge - Automated Video Mixing Tool
Entry Point Application.
"""

import os
from pathlib import Path
import sys

# Ensure UTF-8 console output on Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main():
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ClipForge")
    app.setOrganizationName("ClipForge")

    project_root = Path(__file__).resolve().parent
    icon_path = project_root / "resources" / "icons" / "logo.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(project_root=project_root)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
