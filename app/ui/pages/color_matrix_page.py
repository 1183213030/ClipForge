"""
Color Matrix & Multi-Specification Batch Studio Page for ClipForge 3.0.
Provides drag-and-drop batch video queue, 7-color palette grading matrix,
real-time 60fps WYSIWYG preview monitor, and dual-pipeline NVENC hardware export.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QPushButton,
    QCheckBox, QSlider, QSpinBox, QLineEdit, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QFrame,
    QScrollArea, QMessageBox, QGroupBox
)

from app.core.color_matrix_processor import (
    ColorMatrixConfig,
    COLOR_PRESETS,
    get_default_badge_path,
)
from app.core.color_preview_engine import ColorPreviewEngine
from app.services.badge_service import BadgeService
from app.ui.color_matrix_thread import (
    ColorMatrixExportThread,
    VideoQueueItem,
)
from app.core.hw_encoder import get_best_hardware_encoder, EncoderProfile
from app.utils.ffmpeg_utils import get_ffmpeg_path
from app.utils.path_utils import normalize_path

logger = logging.getLogger(__name__)


class ClickablePreviewLabel(QLabel):
    """Interactive preview screen that cycles through colors on user click."""
    clicked = Signal()

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class ColorMatrixPage(QWidget):
    """
    Color Matrix & Multi-Specification Studio Page.
    Integrated into ClipForge 3.0 and available as a standalone window.
    """
    def __init__(self, project_root: Path, icons_dir: Path, parent=None):
        super().__init__(parent)
        self.project_root = project_root
        self.icons_dir = icons_dir
        self.preview_engine = ColorPreviewEngine()
        self.export_thread: Optional[ColorMatrixExportThread] = None

        self.queue_items: list[VideoQueueItem] = []
        self.current_preview_index: int = -1
        self.current_preview_color: str = "red"
        self.preview_aspect_mode: str = "landscape"  # 'landscape' or 'portrait'
        self.output_dir: Path = self.project_root / "output" / "matrix_color"

        # Watermark Badge Persistence Service
        self.badge_service = BadgeService(self.project_root)
        self.badges_dir = self.badge_service.get_badge_library_dir()

        # Load user defaults from persistent configuration (None if not set)
        def_l, def_p = self.badge_service.get_default_badges()
        self.landscape_badge_path: Optional[Path] = def_l
        self.portrait_badge_path: Optional[Path] = def_p

        # Hardware encoder detection
        self.hw_profile = get_best_hardware_encoder(get_ffmpeg_path())

        self._init_ui()
        self.setAcceptDrops(True)

    def _icon(self, name: str) -> QIcon:
        p = self.icons_dir / name
        return QIcon(str(p)) if p.is_file() else QIcon()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # 1. Top Mini Status Bar (Hardware Indicator & Quick Summary)
        main_layout.addLayout(self._create_top_bar())

        # 2. Main Content Splitter (Left: Queue + Config, Right: Live Monitor)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)

        # Left Column: Configuration & Batch Queue
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(self._create_source_banner_card())
        left_layout.addWidget(self._create_matrix_config_card())
        left_layout.addWidget(self._create_queue_card(), stretch=1)
        left_layout.addWidget(self._create_action_bar_card())

        splitter.addWidget(left_container)

        # Right Column: Real-time Preview Monitor & Color Inspector
        right_container = self._create_preview_panel()
        splitter.addWidget(right_container)

        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)

        main_layout.addWidget(splitter, stretch=1)
        self._populate_badge_combos()

    def _create_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(12)

        title = QLabel("矩阵调色工坊")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        bar.addWidget(title)

        sub_desc = QLabel("一键批量多色调调色 · 1280×720横屏 / 720×1280竖屏规整 · 防搬重数字指纹")
        sub_desc.setStyleSheet("font-size: 12px; color: #64748b;")
        bar.addWidget(sub_desc)

        bar.addStretch()

        # Hardware acceleration badge
        hw_name = self.hw_profile.display_name if self.hw_profile else "CPU 软编模式"
        hw_pill = QLabel(f"硬件加速: {hw_name}")
        hw_pill.setStyleSheet(
            "background-color: #1e293b; color: #38bdf8; font-size: 11px; "
            "font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid #334155;"
        )
        bar.addWidget(hw_pill)
        return bar

    def _create_source_banner_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SourceBannerCard")
        card.setStyleSheet(
            "QFrame#SourceBannerCard {"
            "  background: #18191e; border: 1px solid #2e3039; border-radius: 8px; padding: 8px 12px;"
            "}"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(self._icon("film.svg").pixmap(QSize(20, 20)))
        layout.addWidget(icon_lbl)

        self.lbl_current_video_info = QLabel("当前未选中视频（点击下方「添加视频」或将视频拖入窗口）")
        self.lbl_current_video_info.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 500;")
        layout.addWidget(self.lbl_current_video_info, stretch=1)

        btn_pick = QPushButton("选择视频文件...")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.setStyleSheet(
            "QPushButton { background: #262833; border: 1px solid #3e4251; border-radius: 6px; "
            "color: #e2e8f0; padding: 5px 12px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #323544; border-color: #6366f1; }"
        )
        btn_pick.clicked.connect(self._on_click_add_videos)
        layout.addWidget(btn_pick)

        return card

    def _create_matrix_config_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("MatrixConfigCard")
        card.setStyleSheet(
            "QFrame#MatrixConfigCard {"
            "  background: #18191e; border: 1px solid #272832; border-radius: 8px; padding: 12px;"
            "}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        # 1. Output Color Palettes Checkboxes
        color_row = QHBoxLayout()
        color_row.setSpacing(8)

        lbl_out = QLabel("输出:")
        lbl_out.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        color_row.addWidget(lbl_out)

        # Digital Fingerprint (Anti-Deduplication)
        self.chk_fingerprint = QCheckBox("指纹")
        self.chk_fingerprint.setChecked(True)
        self.chk_fingerprint.setToolTip("注入无感动态微噪点与元数据脱敏，有效防止平台同质化搬运风控")
        self.chk_fingerprint.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")
        color_row.addWidget(self.chk_fingerprint)

        self.color_checkboxes: dict[str, QCheckBox] = {}
        for key, name, hex_color in COLOR_PRESETS:
            chk = QCheckBox(name)
            chk.setChecked(True)
            chk.setStyleSheet(
                f"QCheckBox {{ color: {hex_color}; font-size: 12px; font-weight: 600; spacing: 4px; }}"
                f"QCheckBox::indicator:checked {{ background-color: {hex_color}; border-color: {hex_color}; }}"
            )
            chk.stateChanged.connect(self._update_target_summary)
            self.color_checkboxes[key] = chk
            color_row.addWidget(chk)

        color_row.addStretch()
        vbox.addLayout(color_row)

        # 2. Output Resolution & Badge
        spec_row = QHBoxLayout()
        spec_row.setSpacing(10)

        lbl_spec = QLabel("输出规格:")
        lbl_spec.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        spec_row.addWidget(lbl_spec)

        self.chk_orig_size = QCheckBox("原尺寸")
        self.chk_orig_size.setChecked(False)
        self.chk_orig_size.stateChanged.connect(self._update_target_summary)
        spec_row.addWidget(self.chk_orig_size)

        self.chk_landscape = QCheckBox("横板 1280×720")
        self.chk_landscape.setChecked(True)
        self.chk_landscape.stateChanged.connect(self._update_target_summary)
        spec_row.addWidget(self.chk_landscape)

        self.chk_portrait = QCheckBox("竖版 720×1280")
        self.chk_portrait.setChecked(True)
        self.chk_portrait.stateChanged.connect(self._update_target_summary)
        spec_row.addWidget(self.chk_portrait)

        self.chk_badge = QCheckBox("添加角标")
        self.chk_badge.setChecked(True)
        self.chk_badge.setStyleSheet("color: #fb7185; font-size: 12px; font-weight: 600;")
        self.chk_badge.stateChanged.connect(self._on_badge_toggled)
        spec_row.addWidget(self.chk_badge)

        spec_row.addStretch()
        vbox.addLayout(spec_row)

        # 2.5 Dedicated Badge Management Card
        self.badge_box = QFrame()
        self.badge_box.setObjectName("BadgeBox")
        self.badge_box.setStyleSheet(
            "QFrame#BadgeBox { background: #131418; border: 1px solid #282a36; border-radius: 6px; padding: 8px 10px; }"
        )
        badge_layout = QVBoxLayout(self.badge_box)
        badge_layout.setContentsMargins(8, 6, 8, 6)
        badge_layout.setSpacing(6)

        # Badge Top Row: Title + Library Actions
        b_hdr = QHBoxLayout()
        b_hdr_lbl = QLabel("专属角标库 (上传一次本地永久保存 · 下拉直接选用)")
        b_hdr_lbl.setStyleSheet("color: #e2e8f0; font-size: 12px; font-weight: 600;")
        b_hdr.addWidget(b_hdr_lbl)
        b_hdr.addStretch()

        btn_upload_badge = QPushButton("+ 上传新角标...")
        btn_upload_badge.setCursor(Qt.PointingHandCursor)
        btn_upload_badge.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #6366f1); "
            "color: #ffffff; border: none; border-radius: 4px; padding: 3px 10px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background: #4338ca; }"
        )
        btn_upload_badge.clicked.connect(self._on_upload_new_badge)
        b_hdr.addWidget(btn_upload_badge)

        btn_open_badge_dir = QPushButton("打开角标库")
        btn_open_badge_dir.setCursor(Qt.PointingHandCursor)
        btn_open_badge_dir.setStyleSheet(
            "QPushButton { background: #22242f; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #cbd5e1; padding: 2px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #2d3140; color: #ffffff; }"
        )
        btn_open_badge_dir.clicked.connect(self._on_open_badge_dir)
        b_hdr.addWidget(btn_open_badge_dir)

        btn_refresh_badges = QPushButton("刷新库")
        btn_refresh_badges.setCursor(Qt.PointingHandCursor)
        btn_refresh_badges.setStyleSheet(
            "QPushButton { background: #22242f; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #cbd5e1; padding: 2px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #2d3140; color: #38bdf8; }"
        )
        btn_refresh_badges.clicked.connect(self._on_refresh_badge_library)
        b_hdr.addWidget(btn_refresh_badges)
        badge_layout.addLayout(b_hdr)

        # Landscape Badge Row (Dropdown + Set Default Checkbox)
        land_row = QHBoxLayout()
        lbl_l_tag = QLabel("横板角标 (16:9):")
        lbl_l_tag.setStyleSheet("color: #94a3b8; font-size: 11px; min-width: 90px;")
        land_row.addWidget(lbl_l_tag)

        self.cmb_landscape_badge = QComboBox()
        self.cmb_landscape_badge.setStyleSheet(
            "QComboBox { background: #1a1c24; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #f1f5f9; padding: 3px 8px; font-size: 11px; min-width: 180px; }"
            "QComboBox QAbstractItemView { background: #1a1c24; color: #f1f5f9; selection-background-color: #312e81; }"
        )
        self.cmb_landscape_badge.currentIndexChanged.connect(self._on_landscape_badge_changed)
        land_row.addWidget(self.cmb_landscape_badge, stretch=1)

        self.chk_landscape_default = QCheckBox("设为横板默认")
        self.chk_landscape_default.setToolTip("勾选后下次打开软件自动选用此角标，无需重复选择")
        self.chk_landscape_default.setStyleSheet("color: #38bdf8; font-size: 11px;")
        self.chk_landscape_default.stateChanged.connect(self._on_landscape_default_toggled)
        land_row.addWidget(self.chk_landscape_default)
        badge_layout.addLayout(land_row)

        # Portrait Badge Row (Dropdown + Set Default Checkbox)
        port_row = QHBoxLayout()
        lbl_p_tag = QLabel("竖版角标 (9:16):")
        lbl_p_tag.setStyleSheet("color: #94a3b8; font-size: 11px; min-width: 90px;")
        port_row.addWidget(lbl_p_tag)

        self.cmb_portrait_badge = QComboBox()
        self.cmb_portrait_badge.setStyleSheet(
            "QComboBox { background: #1a1c24; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #f1f5f9; padding: 3px 8px; font-size: 11px; min-width: 180px; }"
            "QComboBox QAbstractItemView { background: #1a1c24; color: #f1f5f9; selection-background-color: #312e81; }"
        )
        self.cmb_portrait_badge.currentIndexChanged.connect(self._on_portrait_badge_changed)
        port_row.addWidget(self.cmb_portrait_badge, stretch=1)

        self.chk_portrait_default = QCheckBox("设为竖版默认")
        self.chk_portrait_default.setToolTip("勾选后下次打开软件自动选用此角标，无需重复选择")
        self.chk_portrait_default.setStyleSheet("color: #a78bfa; font-size: 11px;")
        self.chk_portrait_default.stateChanged.connect(self._on_portrait_default_toggled)
        port_row.addWidget(self.chk_portrait_default)
        badge_layout.addLayout(port_row)

        vbox.addWidget(self.badge_box)

        # 3. Strength Slider & Copies Count
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(12)

        lbl_st = QLabel("调色强度:")
        lbl_st.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        ctrl_row.addWidget(lbl_st)

        self.slider_strength = QSlider(Qt.Horizontal)
        self.slider_strength.setRange(0, 100)
        self.slider_strength.setValue(60)
        self.slider_strength.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #334155; border-radius: 2px; }"
            "QSlider::sub-page:horizontal { background: #6366f1; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #e0e7ff; width: 14px; margin: -5px 0; border-radius: 7px; }"
        )
        self.slider_strength.valueChanged.connect(self._on_strength_slider_changed)
        ctrl_row.addWidget(self.slider_strength, stretch=1)

        self.lbl_strength_val = QLabel("强度: 60%")
        self.lbl_strength_val.setStyleSheet("color: #a5b4fc; font-size: 12px; font-weight: 600; min-width: 75px;")
        ctrl_row.addWidget(self.lbl_strength_val)

        ctrl_row.addSpacing(12)

        lbl_copies = QLabel("每种颜色生成:")
        lbl_copies.setStyleSheet("font-size: 12px; color: #94a3b8;")
        ctrl_row.addWidget(lbl_copies)

        self.spin_copies = QSpinBox()
        self.spin_copies.setRange(1, 10)
        self.spin_copies.setValue(1)
        self.spin_copies.setStyleSheet(
            "background: #111216; border: 1px solid #334155; border-radius: 4px; "
            "color: #f8fafc; padding: 2px 6px; font-size: 12px; min-width: 45px;"
        )
        self.spin_copies.valueChanged.connect(self._update_target_summary)
        ctrl_row.addWidget(self.spin_copies)

        lbl_copies_unit = QLabel("个")
        lbl_copies_unit.setStyleSheet("font-size: 12px; color: #64748b;")
        ctrl_row.addWidget(lbl_copies_unit)

        ctrl_row.addStretch()
        vbox.addLayout(ctrl_row)

        # 4. Target Summary Statement
        self.lbl_summary_statement = QLabel("将生成 14 个视频")
        self.lbl_summary_statement.setStyleSheet(
            "background: #101115; border-left: 3px solid #6366f1; padding: 6px 10px; "
            "color: #94a3b8; font-size: 12px; border-radius: 2px;"
        )
        vbox.addWidget(self.lbl_summary_statement)

        return card

    def _create_queue_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("QueueCard")
        card.setStyleSheet(
            "QFrame#QueueCard {"
            "  background: #18191e; border: 1px solid #272832; border-radius: 8px; padding: 10px;"
            "}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(8)

        # Queue Header
        q_hdr = QHBoxLayout()
        self.lbl_queue_count = QLabel("批量队列: 0 个视频 (可拖入多个，最多 100 个)")
        self.lbl_queue_count.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1;")
        q_hdr.addWidget(self.lbl_queue_count)
        q_hdr.addStretch()

        btn_add = QPushButton("添加视频...")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(
            "QPushButton { background: #262833; border: 1px solid #3e4251; border-radius: 4px; "
            "color: #e2e8f0; padding: 3px 10px; font-size: 11px; }"
            "QPushButton:hover { background: #323544; border-color: #6366f1; }"
        )
        btn_add.clicked.connect(self._on_click_add_videos)
        q_hdr.addWidget(btn_add)

        btn_clear = QPushButton("清空队列")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #334155; border-radius: 4px; "
            "color: #94a3b8; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:hover { color: #ef4444; border-color: #ef4444; }"
        )
        btn_clear.clicked.connect(self._on_clear_queue)
        q_hdr.addWidget(btn_clear)

        vbox.addLayout(q_hdr)

        # Queue Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["序号", "文件名", "状态", "进度", "生成", "时长"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableWidget { background: #111216; border: 1px solid #232530; border-radius: 4px; "
            "gridline-color: #1e2029; color: #e2e8f0; font-size: 12px; }"
            "QHeaderView::section { background: #1a1c24; color: #94a3b8; border: none; padding: 4px; font-weight: 600; }"
            "QTableWidget::item:selected { background: #272b38; }"
        )
        self.table.itemSelectionChanged.connect(self._on_table_row_selected)
        vbox.addWidget(self.table)

        return card

    def _create_action_bar_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("ActionBarCard")
        card.setStyleSheet(
            "QFrame#ActionBarCard {"
            "  background: #18191e; border: 1px solid #272832; border-radius: 8px; padding: 10px;"
            "}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(8)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background: #1e293b; border-radius: 3px; border: none; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #22c55e); border-radius: 3px; }"
        )
        vbox.addWidget(self.progress_bar)

        self.lbl_progress_status = QLabel("就绪 (等待添加任务)")
        self.lbl_progress_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        vbox.addWidget(self.lbl_progress_status)

        # Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_start = QPushButton("开始生成")
        self.btn_start.setIcon(self._icon("play.svg"))
        self.btn_start.setIconSize(QSize(16, 16))
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #6366f1); "
            "color: #ffffff; border: none; border-radius: 6px; padding: 8px 24px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4338ca, stop:1 #4f46e5); }"
            "QPushButton:disabled { background: #334155; color: #64748b; }"
        )
        self.btn_start.clicked.connect(self._on_start_export)
        btn_row.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setIcon(self._icon("square.svg"))
        self.btn_cancel.setIconSize(QSize(14, 14))
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            "QPushButton { background: #262833; border: 1px solid #3e4251; border-radius: 6px; "
            "color: #e2e8f0; padding: 8px 18px; font-size: 13px; font-weight: 500; }"
            "QPushButton:hover { background: #3b1d22; border-color: #ef4444; color: #ef4444; }"
            "QPushButton:disabled { background: #1c1d24; color: #475569; border-color: #262833; }"
        )
        self.btn_cancel.clicked.connect(self._on_cancel_export)
        btn_row.addWidget(self.btn_cancel)

        self.btn_open_folder = QPushButton("打开输出文件夹")
        self.btn_open_folder.setIcon(self._icon("folder-open.svg"))
        self.btn_open_folder.setIconSize(QSize(15, 15))
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setStyleSheet(
            "QPushButton { background: #262833; border: 1px solid #3e4251; border-radius: 6px; "
            "color: #e2e8f0; padding: 8px 16px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #323544; border-color: #6366f1; }"
        )
        self.btn_open_folder.clicked.connect(self._on_open_output_folder)
        btn_row.addWidget(self.btn_open_folder)

        self.chk_out_same_dir = QCheckBox("输出到视频所在文件夹")
        self.chk_out_same_dir.setChecked(False)
        self.chk_out_same_dir.setStyleSheet("color: #94a3b8; font-size: 12px;")
        btn_row.addWidget(self.chk_out_same_dir)

        btn_row.addStretch()

        # Output Dir Selector
        lbl_dir = QLabel("输出目录:")
        lbl_dir.setStyleSheet("color: #64748b; font-size: 11px;")
        btn_row.addWidget(lbl_dir)

        self.txt_out_dir = QLineEdit(str(self.output_dir))
        self.txt_out_dir.setReadOnly(True)
        self.txt_out_dir.setMaximumWidth(180)
        self.txt_out_dir.setStyleSheet(
            "background: #111216; border: 1px solid #2d303e; border-radius: 4px; "
            "color: #94a3b8; padding: 4px 6px; font-size: 11px;"
        )
        btn_row.addWidget(self.txt_out_dir)

        btn_browse = QPushButton("浏览...")
        btn_browse.setStyleSheet(
            "QPushButton { background: #22242f; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #cbd5e1; padding: 4px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #2d3140; }"
        )
        btn_browse.clicked.connect(self._on_browse_output_dir)
        btn_row.addWidget(btn_browse)

        vbox.addLayout(btn_row)
        return card

    def _create_preview_panel(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PreviewPanel")
        card.setStyleSheet(
            "QFrame#PreviewPanel {"
            "  background: #15161b; border: 1px solid #232530; border-radius: 8px; padding: 12px;"
            "}"
        )
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        # Header with Palette Icon
        hdr = QHBoxLayout()
        p_icon = QLabel()
        p_icon.setPixmap(self._icon("palette.svg").pixmap(QSize(18, 18)))
        hdr.addWidget(p_icon)

        p_title = QLabel("调色预览与监视器")
        p_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f1f5f9;")
        hdr.addWidget(p_title)
        hdr.addStretch()

        # Color Selector Combo
        hdr.addWidget(QLabel("预览颜色:"))
        self.cmb_preview_color = QComboBox()
        for key, name, _ in COLOR_PRESETS:
            self.cmb_preview_color.addItem(name, key)
        self.cmb_preview_color.setCurrentIndex(1)  # Default '红'
        self.cmb_preview_color.setStyleSheet(
            "QComboBox { background: #1e2029; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #f1f5f9; padding: 3px 8px; font-size: 12px; }"
        )
        self.cmb_preview_color.currentIndexChanged.connect(self._on_preview_color_combo_changed)
        hdr.addWidget(self.cmb_preview_color)

        # Aspect Ratio Selector
        hdr.addSpacing(6)
        hdr.addWidget(QLabel("画幅:"))
        self.cmb_preview_aspect = QComboBox()
        self.cmb_preview_aspect.addItem("横板 16:9", "landscape")
        self.cmb_preview_aspect.addItem("竖版 9:16", "portrait")
        self.cmb_preview_aspect.setStyleSheet(
            "QComboBox { background: #1e2029; border: 1px solid #363a4d; border-radius: 4px; "
            "color: #f1f5f9; padding: 3px 8px; font-size: 12px; }"
        )
        self.cmb_preview_aspect.currentIndexChanged.connect(self._on_preview_aspect_changed)
        hdr.addWidget(self.cmb_preview_aspect)

        vbox.addLayout(hdr)

        # Time slider
        time_row = QHBoxLayout()
        self.slider_time = QSlider(Qt.Horizontal)
        self.slider_time.setRange(0, 1000)
        self.slider_time.setValue(0)
        self.slider_time.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #334155; border-radius: 2px; }"
            "QSlider::sub-page:horizontal { background: #38bdf8; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #ffffff; width: 12px; margin: -4px 0; border-radius: 6px; }"
        )
        self.slider_time.valueChanged.connect(self._on_preview_time_slider_changed)
        time_row.addWidget(self.slider_time, stretch=1)

        self.lbl_time_str = QLabel("00:00 / 00:00")
        self.lbl_time_str.setStyleSheet("color: #94a3b8; font-size: 11px; min-width: 85px;")
        time_row.addWidget(self.lbl_time_str)
        vbox.addLayout(time_row)

        # Preview Video Screen (Clickable to cycle colors)
        self.lbl_screen = ClickablePreviewLabel()
        self.lbl_screen.setAlignment(Qt.AlignCenter)
        self.lbl_screen.setMinimumSize(320, 240)
        self.lbl_screen.setStyleSheet(
            "background: #090a0d; border: 1px solid #1f212a; border-radius: 6px;"
        )
        self.lbl_screen.clicked.connect(self._on_cycle_preview_color)
        self.lbl_screen.setText("暂无视频画面\n(拖入视频即可实时查看 60fps 调色效果)")
        vbox.addWidget(self.lbl_screen, stretch=1)

        # Bottom Hint & Micro Inspector
        self.lbl_preview_badge_info = QLabel("预览: 红 强度 60%")
        self.lbl_preview_badge_info.setStyleSheet("color: #a5b4fc; font-size: 12px; font-weight: 600;")
        vbox.addWidget(self.lbl_preview_badge_info)

        lbl_hint = QLabel("提示: 拖动强度滑块实时查看调色效果 · 点击画面可循环切换预览颜色")
        lbl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        vbox.addWidget(lbl_hint)

        return card

    # -------------------------------------------------------------
    # Drag and Drop Events
    # -------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        files = []
        for url in urls:
            f = Path(url.toLocalFile())
            if f.is_file() and f.suffix.lower() in [".mp4", ".mov", ".mkv", ".flv", ".avi", ".ts", ".webm"]:
                files.append(f)
        if files:
            self._add_video_files(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # -------------------------------------------------------------
    # Batch Queue Actions
    # -------------------------------------------------------------
    def _on_click_add_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择待调色视频",
            str(self.project_root),
            "视频文件 (*.mp4 *.mov *.mkv *.flv *.avi *.ts *.webm);;所有文件 (*.*)",
        )
        if paths:
            self._add_video_files([Path(p) for p in paths])

    def _add_video_files(self, paths: list[Path]):
        existing = {item.source_path for item in self.queue_items}
        added_count = 0
        for p in paths:
            if p not in existing:
                item = VideoQueueItem(source_path=p)
                self.queue_items.append(item)
                added_count += 1

        self._refresh_table()
        if self.queue_items and self.current_preview_index < 0:
            self._select_preview_video(0)

        self._update_target_summary()

    def _on_clear_queue(self):
        if self.export_thread and self.export_thread.isRunning():
            QMessageBox.warning(self, "操作受限", "当前正在执行导出任务，无法清空队列。")
            return
        self.queue_items.clear()
        self.current_preview_index = -1
        self.preview_engine.close()
        self.lbl_screen.clear()
        self.lbl_screen.setText("暂无视频画面\n(拖入视频即可实时查看 60fps 调色效果)")
        self.lbl_current_video_info.setText("当前未选中视频")
        self._refresh_table()
        self._update_target_summary()

    def _refresh_table(self):
        self.table.setRowCount(len(self.queue_items))
        self.lbl_queue_count.setText(f"批量队列: {len(self.queue_items)} 个视频 (可拖入多个，最多 100 个)")

        for row, item in enumerate(self.queue_items):
            # Index
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, idx_item)

            # Name
            name_item = QTableWidgetItem(item.source_path.name)
            name_item.setToolTip(str(item.source_path))
            self.table.setItem(row, 1, name_item)

            # Status
            status_item = QTableWidgetItem(item.status)
            status_item.setTextAlignment(Qt.AlignCenter)
            if item.status == "完成":
                status_item.setForeground(Qt.green)
            elif item.status == "处理中":
                status_item.setForeground(Qt.cyan)
            elif item.status == "失败":
                status_item.setForeground(Qt.red)
            self.table.setItem(row, 2, status_item)

            # Progress
            pct_str = f"{int(item.progress_pct)}%"
            prog_item = QTableWidgetItem(pct_str)
            prog_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, prog_item)

            # Generated Count
            gen_str = f"{item.generated_count}/{item.total_target_count}"
            gen_item = QTableWidgetItem(gen_str)
            gen_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, gen_item)

            # Duration
            dur_str = item.elapsed_str
            dur_item = QTableWidgetItem(dur_str)
            dur_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, dur_item)

    def _on_table_row_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            if 0 <= row < len(self.queue_items):
                self._select_preview_video(row)

    def _select_preview_video(self, index: int):
        if not (0 <= index < len(self.queue_items)):
            return
        self.current_preview_index = index
        item = self.queue_items[index]

        # Load video into preview engine
        ok, dur_sec, w, h = self.preview_engine.load_video(item.source_path)
        if ok:
            item.duration_sec = dur_sec
            size_mb = item.source_path.stat().st_size / (1024 * 1024)
            mins = int(dur_sec // 60)
            secs = int(dur_sec % 60)
            dur_text = f"{mins:02d}:{secs:02d}"
            item.elapsed_str = dur_text

            self.lbl_current_video_info.setText(
                f"{item.source_path.name}  时长: {dur_text}  大小: {size_mb:.1f} MB  ({w}×{h})"
            )
            self.lbl_time_str.setText(f"00:00 / {dur_text}")
            self.slider_time.setValue(0)
            self._refresh_preview_frame()
            self._refresh_table()

    # -------------------------------------------------------------
    # Live Preview & WYSIWYG Simulation
    # -------------------------------------------------------------
    def _on_preview_time_slider_changed(self, val: int):
        dur = self.preview_engine._duration_sec
        if dur > 0:
            target_ts = (val / 1000.0) * dur
            self.preview_engine.seek_frame(target_ts)
            cur_m = int(target_ts // 60)
            cur_s = int(target_ts % 60)
            tot_m = int(dur // 60)
            tot_s = int(dur % 60)
            self.lbl_time_str.setText(f"{cur_m:02d}:{cur_s:02d} / {tot_m:02d}:{tot_s:02d}")
            self._refresh_preview_frame()

    def _on_strength_slider_changed(self, val: int):
        self.lbl_strength_val.setText(f"强度: {val}%")
        self._refresh_preview_frame()

    def _on_badge_toggled(self):
        self.badge_box.setVisible(self.chk_badge.isChecked())
        self._update_target_summary()
        self._refresh_preview_frame()

    def _populate_badge_combos(self):
        """Populates landscape and portrait badge dropdowns from the persistent badge library."""
        badges = self.badge_service.list_badges()
        saved_l, saved_p = self.badge_service.get_default_badges()

        self.cmb_landscape_badge.blockSignals(True)
        self.cmb_portrait_badge.blockSignals(True)
        self.chk_landscape_default.blockSignals(True)
        self.chk_portrait_default.blockSignals(True)

        self.cmb_landscape_badge.clear()
        self.cmb_portrait_badge.clear()

        # 0th item: No badge
        self.cmb_landscape_badge.addItem("[不使用横板角标]", None)
        self.cmb_portrait_badge.addItem("[不使用竖版角标]", None)

        cur_l_idx = 0
        cur_p_idx = 0

        for idx, b_path in enumerate(badges, start=1):
            is_l_def = bool(saved_l and b_path.name == saved_l.name)
            is_p_def = bool(saved_p and b_path.name == saved_p.name)

            l_label = f"{b_path.name}  [默认]" if is_l_def else b_path.name
            p_label = f"{b_path.name}  [默认]" if is_p_def else b_path.name

            self.cmb_landscape_badge.addItem(l_label, b_path)
            self.cmb_portrait_badge.addItem(p_label, b_path)

            if is_l_def:
                cur_l_idx = idx
            if is_p_def:
                cur_p_idx = idx

        self.cmb_landscape_badge.setCurrentIndex(cur_l_idx)
        self.cmb_portrait_badge.setCurrentIndex(cur_p_idx)

        self.landscape_badge_path = self.cmb_landscape_badge.currentData()
        self.portrait_badge_path = self.cmb_portrait_badge.currentData()

        self.chk_landscape_default.setChecked(bool(saved_l and cur_l_idx > 0))
        self.chk_portrait_default.setChecked(bool(saved_p and cur_p_idx > 0))

        self.cmb_landscape_badge.blockSignals(False)
        self.cmb_portrait_badge.blockSignals(False)
        self.chk_landscape_default.blockSignals(False)
        self.chk_portrait_default.blockSignals(False)

        self._refresh_preview_frame()

    def _on_upload_new_badge(self):
        """Allows user to upload one or more PNG badges, auto-importing them into the persistent library."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "上传水印角标 (可单选或多选)",
            "",
            "PNG图片 (*.png);;所有文件 (*.*)",
        )
        if not paths:
            return

        last_imported: Optional[Path] = None
        for p_str in paths:
            imp = self.badge_service.import_badge(Path(p_str))
            if imp:
                last_imported = imp

        self._populate_badge_combos()

        if last_imported:
            for i in range(self.cmb_landscape_badge.count()):
                if self.cmb_landscape_badge.itemData(i) == last_imported:
                    self.cmb_landscape_badge.setCurrentIndex(i)
                    break
            for i in range(self.cmb_portrait_badge.count()):
                if self.cmb_portrait_badge.itemData(i) == last_imported:
                    self.cmb_portrait_badge.setCurrentIndex(i)
                    break

        QMessageBox.information(
            self,
            "上传成功",
            f"已将 {len(paths)} 个角标保存到本地角标库！\n以后打开软件无需重复上传，下拉即可随时选用。"
        )

    def _on_landscape_badge_changed(self, idx: int):
        self.landscape_badge_path = self.cmb_landscape_badge.currentData()
        saved_l, _ = self.badge_service.get_default_badges()

        is_def = False
        if self.landscape_badge_path and saved_l:
            is_def = (self.landscape_badge_path.name == saved_l.name)
        self.chk_landscape_default.blockSignals(True)
        self.chk_landscape_default.setChecked(is_def)
        self.chk_landscape_default.blockSignals(False)

        self._refresh_preview_frame()

    def _on_portrait_badge_changed(self, idx: int):
        self.portrait_badge_path = self.cmb_portrait_badge.currentData()
        _, saved_p = self.badge_service.get_default_badges()

        is_def = False
        if self.portrait_badge_path and saved_p:
            is_def = (self.portrait_badge_path.name == saved_p.name)
        self.chk_portrait_default.blockSignals(True)
        self.chk_portrait_default.setChecked(is_def)
        self.chk_portrait_default.blockSignals(False)

        self._refresh_preview_frame()

    def _on_landscape_default_toggled(self, state: int):
        if self.chk_landscape_default.isChecked():
            if self.landscape_badge_path:
                self.badge_service.set_default_landscape_badge(self.landscape_badge_path.name)
            else:
                self.badge_service.set_default_landscape_badge(None)
        else:
            self.badge_service.set_default_landscape_badge(None)
        self._populate_badge_combos()

    def _on_portrait_default_toggled(self, state: int):
        if self.chk_portrait_default.isChecked():
            if self.portrait_badge_path:
                self.badge_service.set_default_portrait_badge(self.portrait_badge_path.name)
            else:
                self.badge_service.set_default_portrait_badge(None)
        else:
            self.badge_service.set_default_portrait_badge(None)
        self._populate_badge_combos()

    def _on_open_badge_dir(self):
        b_dir = self.badge_service.get_badge_library_dir()
        if sys.platform == "win32":
            os.startfile(str(b_dir))
        else:
            subprocess.Popen(["xdg-open", str(b_dir)])

    def _on_refresh_badge_library(self):
        self._populate_badge_combos()

    def _on_preview_aspect_changed(self, idx: int):
        self.preview_aspect_mode = self.cmb_preview_aspect.currentData() or "landscape"
        self._refresh_preview_frame()

    def _on_preview_color_combo_changed(self, idx: int):
        self.current_preview_color = self.cmb_preview_color.currentData() or "red"
        self._refresh_preview_frame()

    def _on_cycle_preview_color(self):
        """Cycles through colors when clicking the preview screen directly."""
        cur_idx = self.cmb_preview_color.currentIndex()
        next_idx = (cur_idx + 1) % self.cmb_preview_color.count()
        self.cmb_preview_color.setCurrentIndex(next_idx)

    def _refresh_preview_frame(self):
        raw_bgr = self.preview_engine.get_raw_frame()
        if raw_bgr is None:
            return

        st = self.slider_strength.value() / 100.0
        badge_on = self.chk_badge.isChecked()
        aspect_mode = self.cmb_preview_aspect.currentData() or "landscape"
        badge_p = self.portrait_badge_path if aspect_mode == "portrait" else self.landscape_badge_path

        graded_bgr = ColorPreviewEngine.apply_color_grading(
            raw_bgr,
            self.current_preview_color,
            st,
            add_badge=badge_on,
            badge_image_path=badge_p,
            layout=aspect_mode,
        )

        pixmap = ColorPreviewEngine.to_qpixmap(graded_bgr, max_w=self.lbl_screen.width(), max_h=self.lbl_screen.height())
        self.lbl_screen.setPixmap(pixmap)

        # Update preview badge label
        color_label = self.cmb_preview_color.currentText()
        aspect_label = self.cmb_preview_aspect.currentText()
        badge_status = "有角标" if (badge_on and badge_p) else "无角标"
        self.lbl_preview_badge_info.setText(f"预览: {color_label} 强度 {int(st * 100)}% · {aspect_label} · {badge_status}")

    def _update_target_summary(self):
        selected_colors = [k for k, chk in self.color_checkboxes.items() if chk.isChecked()]
        layouts = []
        if self.chk_landscape.isChecked():
            layouts.append("横板 1280×720")
        if self.chk_portrait.isChecked():
            layouts.append("竖版 720×1280")
        if self.chk_orig_size.isChecked():
            layouts.append("原尺寸")

        copies = self.spin_copies.value()
        badge_str = " + 角标" if self.chk_badge.isChecked() else ""
        units_per_video = len(selected_colors) * len(layouts) * copies

        color_str = "、".join([f"{name}×{copies}" for k, name, _ in COLOR_PRESETS if k in selected_colors])
        layout_str = "、".join(layouts)

        msg = f"将生成 {units_per_video} 个视频（{layout_str}{badge_str}）：{color_str}"
        self.lbl_summary_statement.setText(msg)

    # -------------------------------------------------------------
    # Output Directory & Export Execution
    # -------------------------------------------------------------
    def _on_browse_output_dir(self):
        p = QFileDialog.getExistingDirectory(self, "选择矩阵视频输出目录", str(self.output_dir))
        if p:
            self.output_dir = Path(p)
            self.txt_out_dir.setText(str(self.output_dir))

    def _on_open_output_folder(self):
        target = self.output_dir
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(target))
        else:
            subprocess.Popen(["xdg-open", str(target)])

    def _build_config(self) -> ColorMatrixConfig:
        selected_colors = [k for k, chk in self.color_checkboxes.items() if chk.isChecked()]
        if not selected_colors:
            selected_colors = ["original"]

        out_dir = None if self.chk_out_same_dir.isChecked() else self.output_dir

        return ColorMatrixConfig(
            colors=selected_colors,
            strength=self.slider_strength.value() / 100.0,
            output_landscape=self.chk_landscape.isChecked(),
            output_portrait=self.chk_portrait.isChecked(),
            output_original_size=self.chk_orig_size.isChecked(),
            enable_fingerprint=self.chk_fingerprint.isChecked(),
            add_badge=self.chk_badge.isChecked(),
            badge_text="二创",
            landscape_badge_path=self.landscape_badge_path if self.chk_badge.isChecked() else None,
            portrait_badge_path=self.portrait_badge_path if self.chk_badge.isChecked() else None,
            copies_per_color=self.spin_copies.value(),
            output_dir=out_dir,
            max_concurrent_nvenc=2,
        )

    def _on_start_export(self):
        if not self.queue_items:
            QMessageBox.information(self, "队列为空", "请先添加至少一个视频文件再开始导出。")
            return

        config = self._build_config()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.lbl_progress_status.setText("正在初始化导出管线...")

        self.export_thread = ColorMatrixExportThread(self.queue_items, config, parent=self)
        self.export_thread.video_item_started.connect(self._on_item_started)
        self.export_thread.video_item_progress.connect(self._on_item_progress)
        self.export_thread.video_item_finished.connect(self._on_item_finished)
        self.export_thread.batch_progress.connect(self._on_batch_progress)
        self.export_thread.batch_finished.connect(self._on_batch_finished)
        self.export_thread.log_message.connect(self._on_log_msg)
        self.export_thread.start()

    def _on_cancel_export(self):
        if self.export_thread and self.export_thread.isRunning():
            self.export_thread.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl_progress_status.setText("正在取消导出，等待当前帧落盘...")

    def _on_item_started(self, idx: int, filename: str):
        if 0 <= idx < len(self.queue_items):
            self.queue_items[idx].status = "处理中"
            self._refresh_table()

    def _on_item_progress(self, idx: int, done_units: int, total_units: int, current_pct: float):
        if 0 <= idx < len(self.queue_items):
            item = self.queue_items[idx]
            item.generated_count = done_units
            base_pct = (done_units / total_units) * 100.0 if total_units > 0 else 0.0
            item.progress_pct = min(100.0, base_pct + (current_pct / total_units * 100.0))
            self._refresh_table()

    def _on_item_finished(self, idx: int, status: str, done_units: int, fail_units: int):
        if 0 <= idx < len(self.queue_items):
            item = self.queue_items[idx]
            item.status = status
            item.generated_count = done_units
            item.progress_pct = 100.0 if status == "完成" else item.progress_pct
            self._refresh_table()

    def _on_batch_progress(self, done: int, fail: int, total: int, status_text: str):
        pct = int((done + fail) / total * 100.0) if total > 0 else 0
        self.progress_bar.setValue(min(100, pct))
        self.lbl_progress_status.setText(status_text)

    def _on_batch_finished(self, success_count: int, fail_count: int):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100 if fail_count == 0 else self.progress_bar.value())
        msg = f"批量导出完成: 成功生成 {success_count} 个视频"
        if fail_count > 0:
            msg += f"，失败 {fail_count} 个"
        self.lbl_progress_status.setText(msg)
        QMessageBox.information(self, "导出任务完成", msg)

    def _on_log_msg(self, text: str, level: str):
        logger.info(f"[Matrix] {text}")
