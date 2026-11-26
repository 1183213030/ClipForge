"""
Main Window for ClipForge Application.
Integrates asset management, subtitle typography, video encoding settings,
batch timeline planning, and async task monitoring in an Awwwards-inspired dark UI.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QSpinBox, QLineEdit, QFileDialog,
    QProgressBar, QScrollArea, QMessageBox, QFrame, QStackedWidget
)

from app.core.media_probe import probe_media
from app.core.timeline_builder import TimelineBuilder
from app.core.edit_project import EditProject, create_project
from app.services.task_service import TaskService, TaskRecord, BatchStatistics, TaskState
from app.ui.threads import BatchExportThread, DetectHardwareThread
from app.ui.pages.workbench_page import WorkbenchPage
from app.ui.pages.color_matrix_page import ColorMatrixPage
from app.ui.widgets.asset_card import AssetCardWidget
from app.ui.widgets.subtitle_card import SubtitleCardWidget
from app.ui.widgets.video_card import VideoCardWidget
from app.ui.widgets.task_item_widget import TaskItemWidget
from app.utils.path_utils import normalize_path, ensure_dir



class MainWindow(QMainWindow):
    def __init__(self, project_root: Optional[Path] = None):
        super().__init__()
        if getattr(sys, "frozen", False):
            base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            exe_dir = Path(sys.executable).parent
            self.project_root = project_root or base_dir
            self.icons_dir = self.project_root / "resources" / "icons"
            self.default_output_dir = ensure_dir(exe_dir / "output")
            self.task_service = TaskService(log_dir=exe_dir / "logs")
        else:
            self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
            self.icons_dir = self.project_root / "resources" / "icons"
            self.default_output_dir = ensure_dir(self.project_root / "output")
            self.task_service = TaskService(log_dir=self.project_root / "logs")

        self.export_thread: Optional[BatchExportThread] = None
        self._hw_detect_thread: Optional[DetectHardwareThread] = None
        self._user_changed_workers: bool = False
        self.task_widgets: dict[str, TaskItemWidget] = {}
        self.latest_manifest_path: Optional[Path] = None

        self._init_window()
        self._init_ui()
        self._load_theme()
        self._start_hw_detection()

    def _init_window(self):
        self.setWindowTitle("ClipForge 3.0 - 智能短视频工坊")
        self.setMinimumSize(1120, 780)
        self.resize(1220, 840)

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
        main_layout.setContentsMargins(14, 8, 14, 8)
        main_layout.setSpacing(8)

        # 1. Compact Header Toolbar (~46px)
        main_layout.addLayout(self._create_header())

        # 2. Main Stacked Views (0: Batch Mix, 1: Workbench)
        self.stack = QStackedWidget()

        # Page 0: Batch Mix Splitter (Left: Controls & Inputs, Right: Batch & Tasks)
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

        self.stack.addWidget(splitter)

        # Page 1: Workbench
        self.workbench_page = WorkbenchPage(self.project_root, self.icons_dir)
        self.stack.addWidget(self.workbench_page)

        # Page 2: Color Matrix Studio (ClipForge 3.0)
        self.color_matrix_page = ColorMatrixPage(self.project_root, self.icons_dir)
        self.stack.addWidget(self.color_matrix_page)

        main_layout.addWidget(self.stack, stretch=1)

    def _create_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        header.setSpacing(12)

        # Compact Logo / Title
        logo_lbl = QLabel()
        logo_img = self.icons_dir / "logo.png"
        if logo_img.is_file():
            logo_lbl.setPixmap(QIcon(str(logo_img)).pixmap(QSize(22, 22)))

        title_lbl = QLabel("ClipForge 3.0")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")

        header.addWidget(logo_lbl)
        header.addWidget(title_lbl)

        # Mode Nav Switcher
        header.addSpacing(16)
        self.btn_nav_batch = QPushButton("批量混剪")
        self.btn_nav_batch.setProperty("class", "NavTabBtnActive")
        self.btn_nav_batch.setCursor(Qt.PointingHandCursor)
        self.btn_nav_batch.clicked.connect(lambda: self._switch_page(0))

        self.btn_nav_workbench = QPushButton("精细编辑工作台")
        self.btn_nav_workbench.setProperty("class", "NavTabBtn")
        self.btn_nav_workbench.setCursor(Qt.PointingHandCursor)
        self.btn_nav_workbench.clicked.connect(lambda: self._switch_page(1))

        self.btn_nav_color = QPushButton("矩阵调色大师")
        self.btn_nav_color.setProperty("class", "NavTabBtn")
        self.btn_nav_color.setCursor(Qt.PointingHandCursor)
        self.btn_nav_color.clicked.connect(lambda: self._switch_page(2))

        header.addWidget(self.btn_nav_batch)
        header.addWidget(self.btn_nav_workbench)
        header.addWidget(self.btn_nav_color)

        header.addStretch()
        badge_offline = QLabel("纯本地运行 · 零云端依赖")
        badge_offline.setProperty("class", "BadgeSuccess")
        header.addWidget(badge_offline)
        return header

    def _switch_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.btn_nav_batch.setProperty("class", "NavTabBtnActive" if index == 0 else "NavTabBtn")
        self.btn_nav_workbench.setProperty("class", "NavTabBtnActive" if index == 1 else "NavTabBtn")
        self.btn_nav_color.setProperty("class", "NavTabBtnActive" if index == 2 else "NavTabBtn")

        for btn in (self.btn_nav_batch, self.btn_nav_workbench, self.btn_nav_color):
            btn.style().unpolish(btn)
            btn.style().polish(btn)


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
        row1.addWidget(QLabel("单篇混剪版本:"))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 50)
        self.spin_count.setValue(1)
        self.spin_count.setFixedWidth(75)
        self.spin_count.setToolTip("单篇模式下生成的不同画面混剪版本数；多篇批量模式下可在左侧任务清单中为各小说独立定制")
        row1.addWidget(self.spin_count)

        row1.addSpacing(12)
        row1.addWidget(QLabel("并行并发数:"))
        self.spin_workers = QSpinBox()
        max_cpu_workers = max(4, min(8, os.cpu_count() or 4))
        self.spin_workers.setRange(1, max_cpu_workers)
        self.spin_workers.setValue(2)
        self.spin_workers.setFixedWidth(80)
        self.spin_workers.setSuffix(" 任务")
        self.spin_workers.setToolTip("设置同时并行渲染的任务数 (建议 2~4 任务，配合硬件加速可大幅缩短总耗时)")
        self.spin_workers.valueChanged.connect(self._on_workers_spin_changed)
        row1.addWidget(self.spin_workers)

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

        # Prewarm cache status banner (shown only during batch clip pre-standardization)
        self.lbl_prewarm_status = QLabel("")
        self.lbl_prewarm_status.setStyleSheet(
            "color: #60a5fa; font-size: 12px; font-weight: 500; padding: 2px 0;"
        )
        self.lbl_prewarm_status.hide()
        layout.addWidget(self.lbl_prewarm_status)

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

    def _start_hw_detection(self):
        """Probes available GPU hardware encoder asynchronously on startup."""
        self._hw_detect_thread = DetectHardwareThread(self)
        self._hw_detect_thread.sig_detected.connect(self._on_hw_detected)
        self._hw_detect_thread.start()

    def _on_hw_detected(self, profile, rec_workers: int):
        self.video_card.set_detected_hardware(profile)
        if not self._user_changed_workers and rec_workers >= 1:
            clamped = min(max(1, rec_workers), self.spin_workers.maximum())
            self.spin_workers.blockSignals(True)
            self.spin_workers.setValue(clamped)
            self.spin_workers.blockSignals(False)

    def _on_workers_spin_changed(self, _val: int):
        self._user_changed_workers = True

    def _browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择成品输出目录")
        if d:
            self.input_output_dir.setText(d)

    def _start_batch_export(self):
        # 1. Validation before export
        novel_tasks = self.asset_card.get_novel_tasks(default_count=self.spin_count.value())
        scan_res = self.asset_card.scan_result
        output_dir = self.input_output_dir.text()

        if not novel_tasks:
            if self.asset_card.is_batch_mode:
                QMessageBox.warning(self, "输入检查", "请先在多篇小说清单中添加至少 1 本小说任务（支持目录自动配对或多选文件添加）！")
            else:
                QMessageBox.warning(self, "输入检查", "请先选择有效的小说配音音频文件！")
            return

        if not scan_res or scan_res.valid_count == 0:
            QMessageBox.warning(self, "输入检查", "请先选择视频素材文件夹并确保扫描到至少 1 个有效视频！")
            return

        if not output_dir or not Path(output_dir).is_dir():
            QMessageBox.warning(self, "输入检查", "指定的输出目录不存在或不可写！")
            return

        # 2. Build TimelinePlans and tasks for each novel task
        sub_cfg = self.subtitle_card.get_subtitle_config()
        tpl_path = self.asset_card.template_path if self.asset_card.enable_template else None
        export_opts = self.video_card.get_export_options(
            sub_config=sub_cfg,
            template_png_path=tpl_path,
            enable_template=self.asset_card.enable_template and bool(tpl_path)
        )

        self.task_service.clear_all_tasks()
        all_new_tasks = []
        builder = TimelineBuilder()

        try:
            for item in novel_tasks:
                if not item.is_valid:
                    continue

                audio_dur = item.audio_duration
                if audio_dur <= 0:
                    audio_meta = probe_media(item.audio_path)
                    if not audio_meta.is_valid_audio:
                        raise ValueError(f"小说音频文件无效或无法读取: {item.audio_path}")
                    audio_dur = audio_meta.duration
                    item.audio_duration = audio_dur

                count = item.export_count if self.asset_card.is_batch_mode else self.spin_count.value()
                plans = builder.build_plans_from_scan(
                    scan_res=scan_res,
                    audio_duration=audio_dur,
                    count=max(1, count),
                )

                created = self.task_service.create_batch(
                    plans=plans,
                    audio_path=item.audio_path,
                    srt_path=item.srt_path,
                    output_dir=output_dir,
                    options=export_opts,
                    filename_prefix=item.novel_title
                )
                all_new_tasks.extend(created)
        except Exception as e:
            QMessageBox.critical(self, "组合计划生成失败", f"构建视频编排时间轴失败:\n{str(e)}")
            return

        if not all_new_tasks:
            QMessageBox.warning(self, "任务检查", "未能创建任何有效导出任务，请检查小说音频与时长设置。")
            return

        # Clear existing task widgets
        for w in self.task_widgets.values():
            w.setParent(None)
        self.task_widgets.clear()

        # Build task item widgets in reverse stretch
        for t in all_new_tasks:
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
        self.spin_workers.setEnabled(False)

        # Set user-configured concurrency level
        self.task_service.max_workers = self.spin_workers.value()

        self.export_thread = BatchExportThread(self.task_service)
        self.export_thread.sig_task_updated.connect(self._on_task_updated)
        self.export_thread.sig_batch_updated.connect(self._on_batch_updated)
        self.export_thread.sig_prewarm_progress.connect(self._on_prewarm_progress)
        self.export_thread.sig_finished.connect(self._on_batch_finished)
        self.export_thread.start()

    def _on_prewarm_progress(self, done: int, total: int, clip_name: str):
        if done < total:
            self.lbl_prewarm_status.setText(
                f"正在并行预处理加速缓存 ({done}/{total}): {clip_name}"
            )
            self.lbl_prewarm_status.show()
        else:
            self.lbl_prewarm_status.setText(
                f"素材加速缓存已就绪 ({total}/{total})，正在高速并行渲染..."
            )
            self.lbl_prewarm_status.show()

    def _on_task_updated(self, task: TaskRecord):
        if task.state == TaskState.RUNNING and task.progress > 0.01:
            self.lbl_prewarm_status.hide()
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
        self.lbl_prewarm_status.hide()
        self.btn_start.setEnabled(True)
        self.btn_cancel_all.setEnabled(False)
        self.spin_count.setEnabled(True)
        self.spin_workers.setEnabled(True)

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
            self.task_service.max_workers = self.spin_workers.value()
            self.btn_start.setEnabled(False)
            self.btn_cancel_all.setEnabled(True)
            self.spin_count.setEnabled(False)
            self.spin_workers.setEnabled(False)
            self.export_thread = BatchExportThread(self.task_service)
            self.export_thread.sig_task_updated.connect(self._on_task_updated)
            self.export_thread.sig_batch_updated.connect(self._on_batch_updated)
            self.export_thread.sig_prewarm_progress.connect(self._on_prewarm_progress)
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
