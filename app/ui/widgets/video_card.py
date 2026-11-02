"""
Video Settings Card Widget for ClipForge.
Displays standardized video specifications and provides bitrate tier selection.
"""

from pathlib import Path
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox
)

from app.core.subtitle_processor import SubtitleConfig
from app.core.video_processor import ExportOptions


class VideoCardWidget(QFrame):
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
        icon_lbl.setPixmap(QIcon(str(self.icons_dir / "film.svg")).pixmap(QSize(18, 18)))
        title_lbl = QLabel("视频规格与码率设置")
        title_lbl.setProperty("class", "SectionTitle")
        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Specifications Grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        # Fixed specs
        grid.addWidget(QLabel("画面比例:"), 0, 0)
        lbl_ratio = QLabel("9:16 (竖屏)")
        lbl_ratio.setStyleSheet("color: #60a5fa; font-weight: 600;")
        grid.addWidget(lbl_ratio, 0, 1)

        grid.addWidget(QLabel("目标分辨率:"), 0, 2)
        lbl_res = QLabel("1080 × 1920")
        lbl_res.setStyleSheet("color: #e2e4ec;")
        grid.addWidget(lbl_res, 0, 3)

        grid.addWidget(QLabel("统一帧率:"), 1, 0)
        lbl_fps = QLabel("30.0 FPS")
        lbl_fps.setStyleSheet("color: #e2e4ec;")
        grid.addWidget(lbl_fps, 1, 1)

        grid.addWidget(QLabel("原视频声音:"), 1, 2)
        lbl_audio_mode = QLabel("彻底消除 (仅保留配音)")
        lbl_audio_mode.setStyleSheet("color: #34d399;")
        grid.addWidget(lbl_audio_mode, 1, 3)

        # Bitrate row
        grid.addWidget(QLabel("视频输出码率:"), 2, 0)
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItem("2 Mbps (体积紧凑)", "2M")
        self.combo_bitrate.addItem("4 Mbps (画质与体积均衡 · 推荐)", "4M")
        self.combo_bitrate.addItem("6 Mbps (高清优质)", "6M")
        self.combo_bitrate.addItem("8 Mbps (高保真)", "8M")
        self.combo_bitrate.addItem("10 Mbps (极致画质)", "10M")
        self.combo_bitrate.setCurrentIndex(1)  # Default 4M
        grid.addWidget(self.combo_bitrate, 2, 1, 1, 3)

        layout.addLayout(grid)

    def get_export_options(self, sub_config: SubtitleConfig) -> ExportOptions:
        bitrate_val = self.combo_bitrate.currentData() or "4M"
        return ExportOptions(
            output_width=1080,
            output_height=1920,
            fps=30,
            video_bitrate=bitrate_val,
            audio_bitrate="128k",
            audio_samplerate=44100,
            preset="fast",
            subtitle_config=sub_config
        )
