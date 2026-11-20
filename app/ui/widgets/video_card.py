"""
Video Settings Card Widget for ClipForge.
Displays standardized video specifications and provides bitrate tier,
hardware acceleration engine, and clip pre-standardization cache controls.
"""

from pathlib import Path
from typing import Optional
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QCheckBox
)

from app.core.hw_encoder import EncoderProfile
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
        title_lbl = QLabel("视频规格与加速设置")
        title_lbl.setProperty("class", "SectionTitle")
        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        self.lbl_hw_badge = QLabel("正在检测加速引擎...")
        self.lbl_hw_badge.setProperty("class", "BadgePending")
        header_layout.addWidget(self.lbl_hw_badge)
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

        # Hardware / Speed encoding mode row
        grid.addWidget(QLabel("编码加速引擎:"), 3, 0)
        self.combo_encode_mode = QComboBox()
        self.combo_encode_mode.addItem("智能硬件加速 (自动 · 推荐)", "auto")
        self.combo_encode_mode.addItem("CPU 极速软编 (veryfast)", "cpu_fast")
        self.combo_encode_mode.addItem("CPU 标准软编 (fast)", "cpu_quality")
        self.combo_encode_mode.setCurrentIndex(0)
        grid.addWidget(self.combo_encode_mode, 3, 1, 1, 3)

        layout.addLayout(grid)

        # Clip standardization cache toggle
        self.chk_clip_cache = QCheckBox("启用素材预标准化缓存 (多条混剪与 4K 显著提速)")
        self.chk_clip_cache.setChecked(True)
        self.chk_clip_cache.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.chk_clip_cache.setToolTip(
            "首次导出前一次性将源素材标准化为 1080x1920@30fps 中间缓存，后续多条视频与二次导出直接复用，避免重复 4K 软解与缩放"
        )
        layout.addWidget(self.chk_clip_cache)

    def set_detected_hardware(self, profile: Optional[EncoderProfile]):
        """Updates the hardware acceleration status badge after background detection."""
        if profile is not None and profile.is_hardware:
            short_names = {
                "h264_nvenc": "NVIDIA NVENC",
                "h264_qsv": "Intel QSV",
                "h264_amf": "AMD AMF",
                "h264_mf": "Win 硬件加速",
            }
            tag = short_names.get(profile.codec, profile.codec)
            self.lbl_hw_badge.setText(f"GPU 就绪 · {tag}")
            self.lbl_hw_badge.setProperty("class", "BadgeSuccess")
        else:
            self.lbl_hw_badge.setText("CPU 极速软编")
            self.lbl_hw_badge.setProperty("class", "BadgeRunning")
        self.lbl_hw_badge.style().unpolish(self.lbl_hw_badge)
        self.lbl_hw_badge.style().polish(self.lbl_hw_badge)

    def get_export_options(
        self,
        sub_config: SubtitleConfig,
        template_png_path: Optional[str] = None,
        enable_template: bool = True,
        fonts_dir: Optional[str] = None
    ) -> ExportOptions:
        bitrate_val = self.combo_bitrate.currentData() or "4M"
        encode_mode = self.combo_encode_mode.currentData() or "auto"
        preset_val = "fast" if encode_mode == "cpu_quality" else "veryfast"
        effective_fonts_dir = fonts_dir or (sub_config.fonts_dir if sub_config else None)
        return ExportOptions(
            output_width=1080,
            output_height=1920,
            fps=30,
            video_bitrate=bitrate_val,
            audio_bitrate="128k",
            audio_samplerate=44100,
            preset=preset_val,
            subtitle_config=sub_config,
            template_png_path=template_png_path,
            enable_template=enable_template,
            fonts_dir=effective_fonts_dir,
            encode_mode=encode_mode,
            use_clip_cache=self.chk_clip_cache.isChecked(),
        )
