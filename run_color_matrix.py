"""
ClipForge 3.0 - Color Matrix Studio (Standalone Edition)
Dedicated independent runner for fast batch video color grading and dual-pipeline NVENC export.
Can be run on the same machine or copied to a secondary workstation independently.
"""

import os
from pathlib import Path
import sys

# Ensure UTF-8 console output on Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from app.ui.pages.color_matrix_page import ColorMatrixPage


class StandaloneColorMatrixWindow(QMainWindow):
    def __init__(self, project_root: Path):
        super().__init__()
        self.project_root = project_root
        self.icons_dir = self.project_root / "resources" / "icons"

        self.setWindowTitle("ClipForge 3.0 - 矩阵调色大师 (独立极速版)")
        self.setMinimumSize(1080, 720)
        self.resize(1180, 800)

        # Set Logo
        logo_path = self.icons_dir / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))

        # Load Dark Theme
        qss_path = self.project_root / "resources" / "styles" / "dark_theme.qss"
        if qss_path.is_file():
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))

        # Setup Page
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        self.matrix_page = ColorMatrixPage(self.project_root, self.icons_dir, parent=self)
        layout.addWidget(self.matrix_page)


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ClipForge-ColorMatrix")

    if getattr(sys, "frozen", False):
        project_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        project_root = Path(__file__).resolve().parent

    icon_path = project_root / "resources" / "icons" / "logo.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = StandaloneColorMatrixWindow(project_root=project_root)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
