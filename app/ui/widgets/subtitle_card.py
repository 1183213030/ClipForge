"""
Subtitle Settings and Live Typography Preview Card Widget for ClipForge.
Configures font family, font size, primary/outline colors, and screen alignment.
"""

from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFontDatabase
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QSpinBox
)

from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition


WINDOWS_COMMON_FONTS = [
    "Microsoft YaHei",
    "SimHei",
    "KaiTi",
    "FangSong",
    "SimSun",
    "Segoe UI",
    "Arial"
]


class SubtitleCardWidget(QFrame):
    def __init__(self, icons_dir: Path, parent=None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.setProperty("class", "CardFrame")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(QIcon(str(self.icons_dir / "subtitles.svg")).pixmap(QSize(18, 18)))
        title_lbl = QLabel("字幕与排版样式")
        title_lbl.setProperty("class", "SectionTitle")
        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Controls Grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        # 1. Font Family
        grid.addWidget(QLabel("中文字体:"), 0, 0)
        self.combo_font = QComboBox()
        # Enumerate system fonts or default to common
        installed_families = set(QFontDatabase.families())
        for f in WINDOWS_COMMON_FONTS:
            self.combo_font.addItem(f)
        self.combo_font.currentTextChanged.connect(self._update_preview)
        grid.addWidget(self.combo_font, 0, 1)

        # 2. Font Size
        grid.addWidget(QLabel("字幕字号:"), 0, 2)
        self.spin_size = QSpinBox()
        self.spin_size.setRange(8, 48)
        self.spin_size.setValue(10)
        self.spin_size.setSuffix(" px")
        self.spin_size.setToolTip("推文字幕渲染字号 (范围 8 - 48 px，样片推荐 9 - 10 px)")
        self.spin_size.valueChanged.connect(self._update_preview)
        grid.addWidget(self.spin_size, 0, 3)

        # 3. Position Alignment
        grid.addWidget(QLabel("字幕位置:"), 1, 0)
        self.combo_pos = QComboBox()
        self.combo_pos.addItem("画面正中央 (小说推文推荐)", SubtitlePosition.CENTER)
        self.combo_pos.addItem("底部居中 (传统短视频)", SubtitlePosition.BOTTOM)
        self.combo_pos.addItem("顶部居中", SubtitlePosition.TOP)
        self.combo_pos.currentIndexChanged.connect(self._update_preview)
        grid.addWidget(self.combo_pos, 1, 1)

        # 4. Stroke / Outline Width
        grid.addWidget(QLabel("黑色描边:"), 1, 2)
        self.spin_stroke = QSpinBox()
        self.spin_stroke.setRange(0, 8)
        self.spin_stroke.setValue(2)
        self.spin_stroke.setSuffix(" px")
        self.spin_stroke.valueChanged.connect(self._update_preview)
        grid.addWidget(self.spin_stroke, 1, 3)

        layout.addLayout(grid)

        # Live Mini Preview Frame (Simulates 9:16 layout)
        self.preview_frame = QFrame()
        self.preview_frame.setProperty("class", "SubCardFrame")
        self.preview_frame.setMinimumHeight(64)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(12, 8, 12, 8)

        self.preview_lbl = QLabel("门后显现出一道耀眼的金色光华！")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_lbl)

        layout.addWidget(self.preview_frame)
        self._update_preview()

    def _update_preview(self):
        font_name = self.combo_font.currentText()
        font_size = self.spin_size.value()
        pos_data = self.combo_pos.currentData()

        # Update preview label styling
        align = Qt.AlignCenter
        if pos_data == SubtitlePosition.TOP:
            align = Qt.AlignTop | Qt.AlignHCenter
        elif pos_data == SubtitlePosition.BOTTOM:
            align = Qt.AlignBottom | Qt.AlignHCenter

        self.preview_lbl.setAlignment(align)
        ui_px = max(11, min(int(font_size * 1.1), 26))
        self.preview_lbl.setStyleSheet(
            f"font-family: '{font_name}'; "
            f"font-size: {ui_px}px; "
            f"font-weight: bold; "
            f"color: #ffffff;"
        )

    def get_subtitle_config(self) -> SubtitleConfig:
        pos = self.combo_pos.currentData() or SubtitlePosition.CENTER
        return SubtitleConfig(
            font_name=self.combo_font.currentText(),
            font_size=self.spin_size.value(),
            primary_color="&H00FFFFFF",
            outline_color="&H00000000",
            outline_width=self.spin_stroke.value(),
            position=pos,
            margin_v=0 if pos == SubtitlePosition.CENTER else (80 if pos == SubtitlePosition.BOTTOM else 40),
            margin_l=30,
            margin_r=30,
            max_line_chars=24
        )
