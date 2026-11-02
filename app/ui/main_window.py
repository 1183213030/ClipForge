"""
Main Window for ClipForge Application.
Integrates asset management, subtitle typography, video encoding settings,
batch timeline planning, and async task monitoring in an Awwwards-inspired dark UI.
"""

import json
import os
from pathlib import Path
import subprocess
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QSpinBox, QLineEdit, QFileDialog,
    QProgressBar, QScrollArea, QMessageBox, QFrame
)

from app.core.timeline_builder import TimelineBuilder
from app.services.task_service import TaskService, TaskRecord, BatchStatistics, TaskState
from app.ui.threads import BatchExportThread
from app.ui.widgets.asset_card import AssetCardWidget
from app.ui.widgets.subtitle_card import SubtitleCardWidget
from app.ui.widgets.video_card import VideoCardWidget
from app.ui.widgets.task_item_widget import TaskItemWidget
from app.utils.path_utils import normalize_path, ensure_dir


class MainWindow(QMainWindow):
    def __init__(self, project_root: Optional[Path] = None):
        super().__init__()
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self.icons_dir = self.project_root / "resources" / "icons"
        self.default_output_dir = ensure_dir(self.project_root / "output")

        self.task_service = TaskService(log_dir=self.project_root / "logs")
        self.export_thread: Optional[BatchExportThread] = None
        self.task_widgets: dict[str, TaskItemWidget] = {}
        self.latest_manifest_path: Optional[Path] = None

        self._init_window()
        self._init_ui()
        self._load_theme()

    def _init_window(self):
        self.setWindowTitle("ClipForge - 解压短视频全自动混剪工作台")
        self.setMinimumSize(1080, 750)
        self.resize(1180, 820)

        # Set Window Icon
        logo_path = self.icons_dir / "logo.png"
        if logo_path.is_file():
            self.setWindowIcon(QIcon(str(logo_path)))

    def _load_theme(self):
        qss_path = self.project_root / "resources" / "styles" / "dark_theme.qss"
        if qss_path.is_file():
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. Header Toolbar
        main_layout.addLayout(self._create_header())

        # 2. Main Content Splitter (Left: Controls & Inputs, Right: Batch & Tasks)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)

        # Left Panel (Scrollable Configs)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        self.asset_card = AssetCardWidget(self.icons_dir)
        self.subtitle_card = SubtitleCardWidget(self.icons_dir)
        self.video_card = VideoCardWidget(self.icons_dir)

        left_layout.addWidget(self.asset_card)
        left_layout.addWidget(self.subtitle_card)
        left_layout.addWidget(self.video_card)
        left_layout.addStretch()
        left_scroll.setWidget(left_content)

        # Right Panel (Batch Export Control & Task Monitor)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        right_layout.addWidget(self._create_batch_control_card())
        right_layout.addWidget(self._create_monitor_card())

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)

        main_layout.addWidget(splitter)

    def _create_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)

        # Logo / Title
        logo_lbl = QLabel()
        logo_img = self.icons_dir / "logo.png"
        if logo_img.is_file():
            logo_lbl.setPixmap(QIcon(str(logo_img)).pixmap(QSize(28, 28)))

        title_lbl = QLabel("ClipForge 片段工坊")
        title_lbl.setProperty("class", "HeaderTitle")

        sub_desc = QLabel("Windows 本地解压短视频智能混剪 · 离线全自动工作台")
        sub_desc.setProperty("class", "SubText")

        badge_offline = QLabel("纯本地运行 · 零云端依赖")
        badge_offline.setProperty("class", "BadgeSuccess")

        header.addWidget(logo_lbl)
        header.addWidget(title_lbl)
        header.addWidget(sub_desc)
        header.addStretch()
        header.addWidget(badge_offline)
        return header

    def _create_batch_control_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "CardFrame")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("批量导出控制")
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        # Settings Row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("生成数量:"))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 50)
        self.spin_count.setValue(3)
        self.spin_count.setFixedWidth(80)
        row1.addWidget(self.spin_count)

        row1.addSpacing(14)
        row1.addWidget(QLabel("输出目录:"))
        self.input_output_dir = QLineEdit(str(self.default_output_dir))
        self.input_output_dir.setReadOnly(True)
        btn_browse_out = QPushButton("更改目录")
        btn_browse_out.clicked.connect(self._browse_output_dir)
        row1.addWidget(self.input_output_dir)
        row1.addWidget(btn_browse_out)
        layout.addLayout(row1)

        # Actions Row
        row_act = QHBoxLayout()
        self.btn_start = QPushButton("开始批量混剪导出")
        self.btn_start.setProperty("class", "PrimaryBtn")
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self._start_batch_export)

        self.btn_cancel_all = QPushButton("全部取消")
        self.btn_cancel_all.setProperty("class", "DangerBtn")
        self.btn_cancel_all.setMinimumHeight(36)
        self.btn_cancel_all.setEnabled(False)
        self.btn_cancel_all.clicked.connect(self._cancel_all_tasks)

        row_act.addWidget(self.btn_start, stretch=3)
        row_act.addWidget(self.btn_cancel_all, stretch=1)
        layout.addLayout(row_act)

        return card

    def _create_monitor_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "CardFrame")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header with Statistics
        top_row = QHBoxLayout()
        title = QLabel("任务监视与实时进度")
        title.setProperty("class", "SectionTitle")
        top_row.addWidget(title)
        top_row.addStretch()

        self.btn_open_out_dir = QPushButton("打开输出目录")
        self.btn_open_out_dir.clicked.connect(self._open_output_dir)
        self.btn_view_manifest = QPushButton("查看导出清单")
        self.btn_view_manifest.setEnabled(False)
        self.btn_view_manifest.clicked.connect(self._view_manifest)

        top_row.addWidget(self.btn_open_out_dir)
        top_row.addWidget(self.btn_view_manifest)
        layout.addLayout(top_row)

        # Overall Weighted Progress Bar
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        layout.addWidget(self.overall_progress_bar)

        # Status Badges
        stats_row = QHBoxLayout()
        self.lbl_stat_total = QLabel("总任务: 0")
        self.lbl_stat_total.setProperty("class", "SubText")
        self.lbl_stat_running = QLabel("导出中: 0")
        self.lbl_stat_running.setStyleSheet("color: #60a5fa; font-weight: 600;")
        self.lbl_stat_success = QLabel("成功: 0")
        self.lbl_stat_success.setStyleSheet("color: #34d399; font-weight: 600;")
        self.lbl_stat_failed = QLabel("失败: 0")
        self.lbl_stat_failed.setStyleSheet("color: #f87171; font-weight: 600;")

        stats_row.addWidget(self.lbl_stat_total)
        stats_row.addWidget(self.lbl_stat_running)
        stats_row.addWidget(self.lbl_stat_success)
        stats_row.addWidget(self.lbl_stat_failed)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # Task Items Scroll Area
        self.task_scroll = QScrollArea()
        self.task_scroll.setWidgetResizable(True)
        self.task_scroll.setFrameShape(QFrame.NoFrame)

        self.task_container = QWidget()
        self.task_container_layout = QVBoxLayout(self.task_container)
        self.task_container_layout.setContentsMargins(0, 0, 0, 0)
        self.task_container_layout.setSpacing(6)
        self.task_container_layout.addStretch()

        self.task_scroll.setWidget(self.task_container)
        layout.addWidget(self.task_scroll)

        return card

    def _browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择成品输出目录")
        if d:
            self.input_output_dir.setText(d)

    def _start_batch_export(self):
        # 1. Validation before export
        audio_path = self.asset_card.audio_path
        srt_path = self.asset_card.srt_path
        scan_res = self.asset_card.scan_result
        output_dir = self.input_output_dir.text()
        count = self.spin_count.value()

        if not audio_path or not Path(audio_path).is_file():
            QMessageBox.warning(self, "输入检查", "请先选择有效的小说配音音频文件！")
            return

        if not scan_res or scan_res.valid_count == 0:
            QMessageBox.warning(self, "输入检查", "请先选择视频素材文件夹并确保扫描到至少 1 个有效视频！")
            return

        if not output_dir or not Path(output_dir).is_dir():
            QMessageBox.warning(self, "输入检查", "指定的输出目录不存在或不可写！")
            return

        # 2. Build TimelinePlans
        try:
            builder = TimelineBuilder()
            _, audio_dur, plans = builder.build_plans_from_inputs(
                clips_folder=self.asset_card.video_folder,
                audio_path=audio_path,
                count=count
            )
        except Exception as e:
            QMessageBox.critical(self, "组合计划生成失败", f"构建视频编排时间轴失败:\n{str(e)}")
            return

        # 3. Create batch in TaskService
        sub_cfg = self.subtitle_card.get_subtitle_config()
        export_opts = self.video_card.get_export_options(sub_cfg)

        new_tasks = self.task_service.create_batch(
            plans=plans,
            audio_path=audio_path,
            srt_path=srt_path,
            output_dir=output_dir,
            options=export_opts,
            filename_prefix="clipforge"
        )

        # Clear existing task widgets
        for w in self.task_widgets.values():
            w.setParent(None)
        self.task_widgets.clear()

        # Build task item widgets in reverse stretch
        for t in new_tasks:
            w = TaskItemWidget(
                task=t,
                icons_dir=self.icons_dir,
                on_cancel=self._cancel_single_task,
                on_retry=self._retry_single_task
            )
            self.task_widgets[t.task_id] = w
            # Insert before final stretch
            self.task_container_layout.insertWidget(
                self.task_container_layout.count() - 1, w
            )

        # 4. Lock inputs and start export thread
        self.btn_start.setEnabled(False)
        self.btn_cancel_all.setEnabled(True)
        self.spin_count.setEnabled(False)

        self.export_thread = BatchExportThread(self.task_service)
        self.export_thread.sig_task_updated.connect(self._on_task_updated)
        self.export_thread.sig_batch_updated.connect(self._on_batch_updated)
        self.export_thread.sig_finished.connect(self._on_batch_finished)
        self.export_thread.start()

    def _on_task_updated(self, task: TaskRecord):
        widget = self.task_widgets.get(task.task_id)
        if widget:
            widget.update_task_state(task)

    def _on_batch_updated(self, stats: BatchStatistics):
        self.overall_progress_bar.setValue(int(stats.weighted_progress * 100))
        self.lbl_stat_total.setText(f"总任务: {stats.total}")
        self.lbl_stat_running.setText(f"导出中: {stats.running}")
        self.lbl_stat_success.setText(f"成功: {stats.success}")
        self.lbl_stat_failed.setText(f"失败: {stats.failed}")

    def _on_batch_finished(self, stats: BatchStatistics):
        self.btn_start.setEnabled(True)
        self.btn_cancel_all.setEnabled(False)
        self.spin_count.setEnabled(True)

        # Generate manifest
        out_dir = self.input_output_dir.text()
        self.latest_manifest_path = self.task_service.generate_manifest(out_dir)
        self.btn_view_manifest.setEnabled(True)

        if stats.failed == 0 and stats.cancelled == 0:
            QMessageBox.information(
                self,
                "批量导出完成",
                f"已全部导出完成！共生成 {stats.success} 条视频。\n\n已归档导出记录: {self.latest_manifest_path.name}"
            )
        else:
            QMessageBox.warning(
                self,
                "批次执行结束",
                f"批次已结束: 成功 {stats.success} 条, 失败 {stats.failed} 条, 取消 {stats.cancelled} 条。\n可通过任务列表单独重试失败项。"
            )

    def _cancel_single_task(self, task_id: str):
        self.task_service.cancel_task(task_id)

    def _retry_single_task(self, task_id: str):
        ok = self.task_service.retry_task(task_id)
        if ok and (not self.export_thread or not self.export_thread.isRunning()):
            # Re-launch export worker for pending tasks
            self.btn_start.setEnabled(False)
            self.btn_cancel_all.setEnabled(True)
            self.export_thread = BatchExportThread(self.task_service)
            self.export_thread.sig_task_updated.connect(self._on_task_updated)
            self.export_thread.sig_batch_updated.connect(self._on_batch_updated)
            self.export_thread.sig_finished.connect(self._on_batch_finished)
            self.export_thread.start()

    def _cancel_all_tasks(self):
        self.task_service.cancel_all()

    def _open_output_dir(self):
        out_dir = self.input_output_dir.text()
        if os.path.isdir(out_dir):
            if os.name == "nt":
                subprocess.Popen(f'explorer "{out_dir}"')
            else:
                os.system(f'open "{out_dir}"')

    def _view_manifest(self):
        if self.latest_manifest_path and self.latest_manifest_path.is_file():
            if os.name == "nt":
                subprocess.Popen(f'notepad.exe "{self.latest_manifest_path}"')

    def closeEvent(self, event: QCloseEvent):
        """Intercepts window close to avoid orphaned FFmpeg processes."""
        stats = self.task_service.get_statistics()
        if stats.running > 0:
            reply = QMessageBox.question(
                self,
                "退出确认",
                f"当前有 {stats.running} 个视频正在导出中。\n关闭程序将立即终止视频渲染进程，是否确认退出？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.task_service.cancel_all()
                if self.export_thread and self.export_thread.isRunning():
                    self.export_thread.terminate()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
