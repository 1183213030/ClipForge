"""
Workbench Page for ClipForge Stage 5.4.
Provides a lightweight non-linear editing workbench for novel tweet videos.
Integrates segment reordering/timing, 9:16 vertical video preview, subtitle table editing,
timeline track overview, project save/load persistence, and deterministic re-export.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QFileDialog, QMessageBox,
    QProgressBar, QFrame
)

from app.core.edit_project import EditProject, ProjectError
from app.ui.widgets.video_player_widget import VideoPlayerWidget
from app.ui.widgets.segment_list_widget import SegmentListWidget
from app.ui.widgets.subtitle_editor_widget import SubtitleEditorWidget
from app.ui.widgets.timeline_track_widget import TimelineTrackWidget
from app.ui.threads import ProjectReExportThread
from app.utils.path_utils import normalize_path, ensure_dir


class WorkbenchPage(QWidget):
    project_changed = Signal(object)  # EditProject

    def __init__(self, project_root: Path, icons_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project_root = project_root
        self.icons_dir = icons_dir
        self.output_dir = ensure_dir(project_root / "output")
        self.temp_dir = ensure_dir(project_root / "temp")

        self.project: Optional[EditProject] = None
        self.current_project_path: Optional[Path] = None
        self.is_dirty: bool = False
        self.reexport_thread: Optional[ProjectReExportThread] = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # 1. Compact Top Action Bar (~42px)
        layout.addLayout(self._create_action_bar())

        # 2. Main 3-Column Splitter (Left: Segments, Mid: Player, Right: Subtitles)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(6)

        # Left Column: Video Segment List
        left_container = QFrame()
        left_container.setProperty("class", "CardFrame")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(10, 10, 10, 10)
        self.segment_list = SegmentListWidget(self.icons_dir)
        self.segment_list.segment_selected.connect(self._on_segment_selected_for_preview)
        self.segment_list.project_modified.connect(self._on_project_modified)
        left_layout.addWidget(self.segment_list)
        main_splitter.addWidget(left_container)

        # Center Column: 9:16 Video Player
        center_container = QFrame()
        center_container.setProperty("class", "CardFrame")
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(10, 10, 10, 10)
        self.player_widget = VideoPlayerWidget(self.icons_dir)
        self.player_widget.position_changed.connect(self._on_player_position_changed)
        center_layout.addWidget(self.player_widget)
        main_splitter.addWidget(center_container)

        # Right Column: Subtitle Table Editor
        right_container = QFrame()
        right_container.setProperty("class", "CardFrame")
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 10)
        self.subtitle_editor = SubtitleEditorWidget(self.icons_dir)
        self.subtitle_editor.subtitle_clicked.connect(self._on_subtitle_clicked)
        self.subtitle_editor.project_modified.connect(self._on_project_modified)
        right_layout.addWidget(self.subtitle_editor)
        main_splitter.addWidget(right_container)

        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setStretchFactor(2, 4)
        layout.addWidget(main_splitter, stretch=1)

        # 3. Bottom Timeline Overview
        bottom_frame = QFrame()
        bottom_frame.setProperty("class", "CardFrame")
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(8, 6, 8, 6)
        bottom_layout.setSpacing(4)

        lbl_track_title = QLabel("时间轴概览 (点击/拖动跳转)")
        lbl_track_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        bottom_layout.addWidget(lbl_track_title)

        self.timeline_widget = TimelineTrackWidget()
        self.timeline_widget.seek_requested.connect(self._on_timeline_seek_requested)
        bottom_layout.addWidget(self.timeline_widget)

        # Export Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #1e222d;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 3px;
            }
        """)
        self.progress_bar.hide()
        bottom_layout.addWidget(self.progress_bar)

        layout.addWidget(bottom_frame)

    def _create_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        # Project Name & Save Status
        self.lbl_proj_name = QLabel("未加载项目")
        self.lbl_proj_name.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 14px;")

        self.lbl_dirty_tag = QLabel("")
        self.lbl_dirty_tag.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: 600;")

        bar.addWidget(self.lbl_proj_name)
        bar.addWidget(self.lbl_dirty_tag)
        bar.addStretch()

        # Action Buttons
        self.btn_open = QPushButton("打开工程")
        self._set_btn_icon(self.btn_open, "folder-open.svg", "开")
        self.btn_open.clicked.connect(self._on_open_project)
        bar.addWidget(self.btn_open)

        self.btn_save = QPushButton("保存工程")
        self._set_btn_icon(self.btn_save, "save.svg", "存")
        self.btn_save.clicked.connect(self._on_save_project)
        bar.addWidget(self.btn_save)

        self.btn_save_as = QPushButton("另存为...")
        self.btn_save_as.clicked.connect(self._on_save_project_as)
        bar.addWidget(self.btn_save_as)

        # Re-export Button
        self.btn_reexport = QPushButton("确定性重新导出")
        self.btn_reexport.setProperty("class", "PrimaryBtn")
        self.btn_reexport.setMinimumHeight(30)
        self._set_btn_icon(self.btn_reexport, "download.svg", "导")
        self.btn_reexport.setToolTip("使用当前时间轴精确重导，完全跳过随机混剪")
        self.btn_reexport.clicked.connect(self._on_reexport)
        bar.addWidget(self.btn_reexport)

        return bar

    def _set_btn_icon(self, btn: QPushButton, icon_file: str, fallback: str):
        p = self.icons_dir / icon_file
        if p.is_file():
            btn.setIcon(QIcon(str(p)))
            btn.setIconSize(QSize(15, 15))
        else:
            btn.setText(fallback)

    def set_project(self, project: EditProject, project_path: Optional[Path] = None):
        """Loads and activates an EditProject in the workbench."""
        self.project = project
        self.current_project_path = project_path
        self.is_dirty = False
        self._update_header_status()

        self.segment_list.set_project(project)
        self.subtitle_editor.set_project(project)
        self.timeline_widget.set_project(project)

        if not project:
            self.project_changed.emit(None)
            return

        # Check for missing assets
        missing = project.validate_assets()
        if missing:
            msg = f"检测到 {len(missing)} 个素材文件路径丢失:\n" + "\n".join(missing[:3])
            if len(missing) > 3:
                msg += f"\n...及其他 {len(missing) - 3} 个"
            QMessageBox.warning(self, "素材丢失提示", msg)

        # If project has export history, preview the latest output
        if project.export_history:
            latest = project.export_history[-1]
            if Path(latest.output_path).is_file():
                self.player_widget.load_media(latest.output_path)
        elif project.video_track:
            first_clip = project.video_track[0].clip_path
            if Path(first_clip).is_file():
                self.player_widget.load_media(first_clip)

        self.project_changed.emit(project)

    def _update_header_status(self):
        if not self.project:
            self.lbl_proj_name.setText("未加载项目")
            self.lbl_dirty_tag.setText("")
            return
        name = self.project.meta.project_name
        self.lbl_proj_name.setText(f"项目: {name}")
        self.lbl_dirty_tag.setText("[未保存更改]" if self.is_dirty else "[已保存]")

    def _on_project_modified(self):
        self.is_dirty = True
        self._update_header_status()
        self.timeline_widget.update()

    def _on_segment_selected_for_preview(self, clip_path: str):
        if Path(clip_path).is_file():
            self.player_widget.load_media(clip_path)

    def _on_subtitle_clicked(self, start_sec: float):
        ms = int(start_sec * 1000)
        self.player_widget.seek(ms)
        self.timeline_widget.set_current_time(start_sec)

    def _on_timeline_seek_requested(self, time_sec: float):
        ms = int(time_sec * 1000)
        self.player_widget.seek(ms)

    def _on_player_position_changed(self, pos_ms: int):
        sec = pos_ms / 1000.0
        self.timeline_widget.set_current_time(sec)

    def _on_open_project(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开 ClipForge 工程文件", "", "工程文件 (*.clipforge *.json)"
        )
        if not file_path:
            return
        try:
            proj = EditProject.load(file_path)
            self.set_project(proj, Path(file_path))
        except Exception as e:
            QMessageBox.critical(self, "加载工程失败", f"无法解析工程文件:\n{e}")

    def _on_save_project(self):
        if not self.project:
            return
        if not self.current_project_path:
            self._on_save_project_as()
            return
        try:
            self.project.save(self.current_project_path)
            self.is_dirty = False
            self._update_header_status()
            QMessageBox.information(self, "保存成功", f"工程已保存至:\n{self.current_project_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_save_project_as(self):
        if not self.project:
            return
        default_name = f"{self.project.meta.project_name}.clipforge"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "另存为工程文件", str(self.output_dir / default_name), "工程文件 (*.clipforge)"
        )
        if not file_path:
            return
        try:
            p = Path(file_path)
            self.project.save(p)
            self.current_project_path = p
            self.is_dirty = False
            self._update_header_status()
            QMessageBox.information(self, "保存成功", f"工程已另存至:\n{p.name}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _on_reexport(self):
        if not self.project:
            QMessageBox.warning(self, "提示", "请先打开或创建一个项目。")
            return

        missing = self.project.validate_assets()
        if missing:
            QMessageBox.critical(
                self, "无法导出", f"存在缺失的素材文件 ({len(missing)} 个)，请修复后再试。"
            )
            return

        # Determine next version output path
        next_ver = len(self.project.export_history) + 1
        out_filename = f"{self.project.meta.project_name}_v{next_ver}.mp4"
        out_path = self.output_dir / out_filename

        # Avoid overwriting
        idx = 1
        while out_path.exists():
            out_path = self.output_dir / f"{self.project.meta.project_name}_v{next_ver}_{idx}.mp4"
            idx += 1

        self.btn_reexport.setEnabled(False)
        self.btn_reexport.setText("正在确定性重导...")
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self.reexport_thread = ProjectReExportThread(
            project=self.project,
            output_path=str(out_path),
            temp_dir=self.temp_dir,
            parent=self
        )
        self.reexport_thread.sig_progress.connect(self._on_reexport_progress)
        self.reexport_thread.sig_finished.connect(self._on_reexport_finished)
        self.reexport_thread.sig_error.connect(self._on_reexport_error)
        self.reexport_thread.start()

    def _on_reexport_progress(self, pct: float):
        self.progress_bar.setValue(int(pct))

    def _on_reexport_finished(self, out_path: str, elapsed: float):
        self.progress_bar.hide()
        self.btn_reexport.setEnabled(True)
        self.btn_reexport.setText("确定性重新导出")

        # Auto-save project with new export history
        if self.current_project_path:
            try:
                self.project.save(self.current_project_path)
                self.is_dirty = False
                self._update_header_status()
            except Exception:
                pass

        # Load newly re-exported file into preview player
        self.player_widget.load_media(out_path)
        QMessageBox.information(
            self, "重新导出成功",
            f"视频已生成且通过后置校验:\n{Path(out_path).name}\n耗时: {elapsed:.1f} 秒\n(已加载至预览播放器)"
        )

    def _on_reexport_error(self, err: str):
        self.progress_bar.hide()
        self.btn_reexport.setEnabled(True)
        self.btn_reexport.setText("确定性重新导出")
        QMessageBox.critical(self, "导出失败", f"视频重导过程中发生错误:\n{err}")
