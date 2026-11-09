"""
Subtitle Editor Widget for ClipForge Stage 5.4.
Displays subtitle entries in an interactive table, supporting direct in-place editing
of subtitle text and start/end timestamps, updating EditProject without altering video or audio.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QSpinBox, QFrame
)

from app.core.edit_project import EditProject


class SubtitleEditorWidget(QWidget):
    subtitle_clicked = Signal(float)  # start_time (seconds)
    project_modified = Signal()

    def __init__(self, icons_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.project: Optional[EditProject] = None
        self._is_populating = False
        self._current_preview_text = "门后显现出一道耀眼的金色光华！"

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header with Title and Subtitle Count
        hdr = QHBoxLayout()
        self.lbl_title = QLabel("字幕台词列表 (双击修改)")
        self.lbl_title.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
        self.lbl_count = QLabel("0 条字幕")
        self.lbl_count.setStyleSheet("color: #64748b; font-size: 11px;")
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()
        hdr.addWidget(self.lbl_count)
        layout.addLayout(hdr)

        # Font Size Toolbar & Live Typography Preview Strip (Stage 5.6.3)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl_font_size = QLabel("渲染字号:")
        lbl_font_size.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")
        toolbar.addWidget(lbl_font_size)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(12, 36)
        self.spin_font_size.setValue(16)
        self.spin_font_size.setSingleStep(1)
        self.spin_font_size.setSuffix(" px")
        self.spin_font_size.setToolTip("调节推文字幕渲染字号 (范围 12 - 36 px，默认 16 px)")
        self.spin_font_size.setStyleSheet("""
            QSpinBox {
                background-color: #101217;
                color: #f8fafc;
                border: 1px solid #1e222d;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 12px;
                font-weight: 600;
                min-width: 70px;
            }
            QSpinBox:focus {
                border: 1px solid #3b82f6;
            }
        """)
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        toolbar.addWidget(self.spin_font_size)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Mini Live Typography Preview Strip
        self.preview_strip = QFrame()
        self.preview_strip.setStyleSheet("""
            QFrame {
                background-color: #0b0d13;
                border: 1px solid #1e222d;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        preview_layout = QHBoxLayout(self.preview_strip)
        preview_layout.setContentsMargins(6, 4, 6, 4)

        self.lbl_preview_text = QLabel(self._current_preview_text)
        self.lbl_preview_text.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.lbl_preview_text)
        layout.addWidget(self.preview_strip)
        self._update_preview_strip()

        # Subtitle Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "开始 (s)", "结束 (s)", "台词字幕内容"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #101217;
                border: 1px solid #1e222d;
                border-radius: 6px;
                gridline-color: #1e222d;
                color: #e2e8f0;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #161922;
                color: #94a3b8;
                border: 1px solid #1e222d;
                padding: 4px;
                font-weight: 600;
            }
            QTableWidget::item:selected {
                background-color: #1e3a8a;
                color: #ffffff;
            }
        """)

        self.table.cellChanged.connect(self._on_cell_changed)
        self.table.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.table, stretch=1)

    def set_project(self, project: EditProject):
        self.project = project
        self.refresh()

    def refresh(self):
        if not self.project:
            self.table.setRowCount(0)
            self.lbl_count.setText("0 条字幕")
            return

        self._is_populating = True
        subs = self.project.subtitle_track
        self.table.setRowCount(len(subs))
        self.lbl_count.setText(f"{len(subs)} 条字幕")

        # Synchronize font size control with project render_settings
        self.spin_font_size.blockSignals(True)
        self.spin_font_size.setValue(self.project.render_settings.font_size)
        self.spin_font_size.blockSignals(False)

        if subs:
            self._update_preview_strip(subs[0].edited_text)
        else:
            self._update_preview_strip()

        for row, item in enumerate(subs):
            # Index (read-only)
            idx_item = QTableWidgetItem(f"{item.subtitle_id:03d}")
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            idx_item.setTextAlignment(Qt.AlignCenter)
            idx_item.setForeground(Qt.GlobalColor.darkGray)

            # Start time
            start_item = QTableWidgetItem(f"{item.start_time:.2f}")
            start_item.setTextAlignment(Qt.AlignCenter)

            # End time
            end_item = QTableWidgetItem(f"{item.end_time:.2f}")
            end_item.setTextAlignment(Qt.AlignCenter)

            # Edited text
            text_item = QTableWidgetItem(item.edited_text)
            if item.is_modified:
                text_item.setForeground(Qt.GlobalColor.cyan)

            self.table.setItem(row, 0, idx_item)
            self.table.setItem(row, 1, start_item)
            self.table.setItem(row, 2, end_item)
            self.table.setItem(row, 3, text_item)

        self._is_populating = False

    def _on_item_clicked(self, item: QTableWidgetItem):
        if self._is_populating or not self.project:
            return
        row = item.row()
        if 0 <= row < len(self.project.subtitle_track):
            sub = self.project.subtitle_track[row]
            self._update_preview_strip(sub.edited_text)
            self.subtitle_clicked.emit(sub.start_time)

    def _on_font_size_changed(self, new_val: int):
        if self._is_populating or not self.project:
            return
        try:
            self.project.set_font_size(new_val)
            self._update_preview_strip()
            self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "字号设置无效", str(e))
            self.spin_font_size.setValue(self.project.render_settings.font_size)

    def _update_preview_strip(self, text: Optional[str] = None):
        if text:
            self._current_preview_text = text.replace("\n", " ")
        font_sz = self.spin_font_size.value() if hasattr(self, "spin_font_size") else 16
        if hasattr(self, "lbl_preview_text"):
            self.lbl_preview_text.setText(self._current_preview_text)
            # Map font_sz proportionally to UI preview (12 -> 11px, 16 -> 14px, 24 -> 18px, 36 -> 24px)
            ui_px = max(11, min(int(font_sz * 0.85), 24))
            self.lbl_preview_text.setStyleSheet(
                f"font-family: 'Microsoft YaHei', sans-serif; "
                f"font-size: {ui_px}px; "
                f"font-weight: 700; "
                f"color: #ffffff; "
                f"background: transparent;"
            )

    def _on_cell_changed(self, row: int, col: int):
        if self._is_populating or not self.project:
            return

        sub_id_item = self.table.item(row, 0)
        if not sub_id_item:
            return
        sub_id = int(sub_id_item.text())

        try:
            if col == 1 or col == 2:
                # Timing changed
                start_val = float(self.table.item(row, 1).text())
                end_val = float(self.table.item(row, 2).text())
                self.project.edit_subtitle_timing(sub_id, start_val, end_val)
                self.project_modified.emit()
            elif col == 3:
                # Text changed
                new_text = self.table.item(row, 3).text().strip()
                self.project.edit_subtitle_text(sub_id, new_text)
                self.table.item(row, 3).setForeground(Qt.GlobalColor.cyan)
                self.project_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "修改字幕无效", str(e))
            self.refresh()
