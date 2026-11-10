"""
Segment List Widget for ClipForge Stage 5.4.
Displays and manages the ordered list of video track segments in an EditProject.
Supports reordering (move up/down), duration adjustment, replacing, deleting, and adding segments.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QScrollArea, QFrame, QDoubleSpinBox,
    QFileDialog, QMessageBox
)

from app.core.edit_project import EditProject, MIN_SEGMENT_DURATION


class SegmentItemWidget(QFrame):
    selected = Signal(str)          # segment_id
    move_up = Signal(str)           # segment_id
    move_down = Signal(str)         # segment_id
    replace_requested = Signal(str) # segment_id
    delete_requested = Signal(str)  # segment_id
    duration_changed = Signal(str, float)  # segment_id, new_dur

    def __init__(self, segment_id: str, index: int, name: str, duration: float,
                 is_tail: bool, icons_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.segment_id = segment_id
        self.index = index
        self.is_tail = is_tail
        self.icons_dir = icons_dir

        self.setProperty("class", "CardFrame")
        self.setStyleSheet("""
            QFrame.CardFrame {
                background-color: #12141a;
                border: 1px solid #1e222d;
                border-radius: 6px;
                padding: 6px;
            }
            QFrame.CardFrame:hover {
                border-color: #3b82f6;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Index Badge
        self.lbl_idx = QLabel(f"#{index + 1:02d}")
        self.lbl_idx.setStyleSheet(
            "font-weight: 700; color: #3b82f6; font-size: 12px; font-family: monospace;"
        )
        layout.addWidget(self.lbl_idx)

        # Segment Name & Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.lbl_name = QLabel(name)
        self.lbl_name.setStyleSheet("color: #f1f5f9; font-size: 12px; font-weight: 500;")
        self.lbl_name.setToolTip(name)

        tag = " [尾段自适应]" if is_tail else ""
        self.lbl_tag = QLabel(f"时长{tag}:")
        self.lbl_tag.setStyleSheet("color: #64748b; font-size: 11px;")

        info_layout.addWidget(self.lbl_name)
        info_layout.addWidget(self.lbl_tag)
        layout.addLayout(info_layout, stretch=1)

        # Duration SpinBox
        self.spin_dur = QDoubleSpinBox()
        self.spin_dur.setRange(MIN_SEGMENT_DURATION, 600.0)
        self.spin_dur.setSingleStep(0.5)
        self.spin_dur.setDecimals(2)
        self.spin_dur.setValue(duration)
        self.spin_dur.setSuffix("s")
        self.spin_dur.setFixedWidth(74)
        if is_tail:
            # Tail segment is dynamically balanced; show as read-only indicator
            self.spin_dur.setToolTip("尾部片段根据总音频时长自动平衡补全")
            self.spin_dur.setEnabled(False)
        else:
            self.spin_dur.valueChanged.connect(self._on_duration_spin_changed)
        layout.addWidget(self.spin_dur)

        # Move Up Button
        self.btn_up = QPushButton()
        self.btn_up.setFixedSize(26, 26)
        self.btn_up.setToolTip("上移片段")
        self._set_btn_icon(self.btn_up, "arrow-up.svg", "↑")
        self.btn_up.clicked.connect(lambda: self.move_up.emit(self.segment_id))
        layout.addWidget(self.btn_up)

        # Move Down Button
        self.btn_down = QPushButton()
        self.btn_down.setFixedSize(26, 26)
        self.btn_down.setToolTip("下移片段")
        self._set_btn_icon(self.btn_down, "arrow-down.svg", "↓")
        self.btn_down.clicked.connect(lambda: self.move_down.emit(self.segment_id))
        layout.addWidget(self.btn_down)

        # Replace Clip Button
        self.btn_replace = QPushButton()
        self.btn_replace.setFixedSize(26, 26)
        self.btn_replace.setToolTip("替换视频文件")
        self._set_btn_icon(self.btn_replace, "folder-open.svg", "换")
        self.btn_replace.clicked.connect(lambda: self.replace_requested.emit(self.segment_id))
        layout.addWidget(self.btn_replace)

        # Delete Button
        self.btn_del = QPushButton()
        self.btn_del.setFixedSize(26, 26)
        self.btn_del.setToolTip("删除片段")
        self._set_btn_icon(self.btn_del, "trash-2.svg", "删")
        self.btn_del.clicked.connect(lambda: self.delete_requested.emit(self.segment_id))
        layout.addWidget(self.btn_del)

    def _set_btn_icon(self, btn: QPushButton, icon_file: str, fallback_text: str):
        p = self.icons_dir / icon_file
        if p.is_file():
            btn.setIcon(QIcon(str(p)))
            btn.setIconSize(QSize(14, 14))
        else:
            btn.setText(fallback_text)

    def _on_duration_spin_changed(self, val: float):
        self.duration_changed.emit(self.segment_id, val)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selected.emit(self.segment_id)


class SegmentListWidget(QWidget):
    segment_selected = Signal(str, str)  # segment_id, clip_path
    project_modified = Signal()

    def __init__(self, icons_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.project: Optional[EditProject] = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header with Summary
        hdr = QHBoxLayout()
        self.lbl_title = QLabel("视频轨道片段")
        self.lbl_title.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
        self.lbl_summary = QLabel("0 片段 · 0.0s")
        self.lbl_summary.setStyleSheet("color: #64748b; font-size: 11px;")
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()
        hdr.addWidget(self.lbl_summary)
        layout.addLayout(hdr)

        # Scrollable Segment List
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(6)
        self.container_layout.addStretch()
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, stretch=1)

        # Bottom Add Button
        self.btn_add = QPushButton("添加素材片段")
        self.btn_add.setMinimumHeight(32)
        p = self.icons_dir / "plus.svg"
        if p.is_file():
            self.btn_add.setIcon(QIcon(str(p)))
            self.btn_add.setIconSize(QSize(14, 14))
        self.btn_add.clicked.connect(self._on_add_segment)
        layout.addWidget(self.btn_add)

    def set_project(self, project: EditProject):
        self.project = project
        self.refresh()

    def refresh(self):
        """Rebuilds segment item widgets based on current project.video_track."""
        # Clear existing items
        while self.container_layout.count() > 1:
            child = self.container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.project:
            self.lbl_summary.setText("无项目")
            return

        tracks = self.project.video_track
        total_dur = sum(s.duration for s in tracks)
        audio_dur = self.project.assets.audio_duration
        self.lbl_summary.setText(f"{len(tracks)} 片段 · 视频: {total_dur:.1f}s / 音频: {audio_dur:.1f}s")

        for idx, seg in enumerate(tracks):
            is_tail = (idx == len(tracks) - 1)
            item = SegmentItemWidget(
                segment_id=seg.segment_id,
                index=idx,
                name=seg.display_name,
                duration=seg.duration,
                is_tail=is_tail,
                icons_dir=self.icons_dir
            )
            item.selected.connect(self._on_item_selected)
            item.move_up.connect(self._on_move_up)
            item.move_down.connect(self._on_move_down)
            item.replace_requested.connect(self._on_replace)
            item.delete_requested.connect(self._on_delete)
            item.duration_changed.connect(self._on_duration_changed)

            # Insert before final stretch
            self.container_layout.insertWidget(self.container_layout.count() - 1, item)

    def _on_item_selected(self, segment_id: str):
        if not self.project:
            return
        for seg in self.project.video_track:
            if seg.segment_id == segment_id:
                self.segment_selected.emit(seg.segment_id, seg.clip_path)
                break

    def _on_move_up(self, segment_id: str):
        if not self.project:
            return
        try:
            self.project.move_segment(segment_id, -1)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "调整片段顺序失败", str(e))

    def _on_move_down(self, segment_id: str):
        if not self.project:
            return
        try:
            self.project.move_segment(segment_id, 1)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "调整片段顺序失败", str(e))

    def _on_duration_changed(self, segment_id: str, new_dur: float):
        if not self.project:
            return
        try:
            self.project.update_segment_duration(segment_id, new_dur)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "时长调整超出约束", str(e))
            self.refresh()

    def _on_replace(self, segment_id: str):
        if not self.project:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择替换视频素材", "", "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm)"
        )
        if not file_path:
            return
        try:
            from app.core.media_scanner import calculate_file_sha256
            sha = calculate_file_sha256(file_path)
            self.project.replace_segment(segment_id, file_path, sha)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "替换片段失败", str(e))

    def _on_delete(self, segment_id: str):
        if not self.project:
            return
        try:
            self.project.remove_segment(segment_id)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "删除片段失败", str(e))

    def _on_add_segment(self):
        if not self.project:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "添加视频素材片段", "", "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm)"
        )
        if not file_path:
            return
        try:
            from app.core.media_scanner import calculate_file_sha256
            sha = calculate_file_sha256(file_path)
            self.project.add_segment(clip_path=file_path, duration=3.0, clip_sha256=sha)
            self.refresh()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "添加片段失败", str(e))
