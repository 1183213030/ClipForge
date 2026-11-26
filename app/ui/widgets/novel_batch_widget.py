"""
Novel Batch Management Widget for ClipForge.
Provides multi-novel task listing, directory auto-pairing (Option A),
and multi-file selection pairing (Option B) with high-density dark UI.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QSpinBox, QAbstractItemView
)

from app.core.novel_task import NovelTaskItem, NovelBatchMatcher
from app.utils.path_utils import normalize_path


class NovelBatchWidget(QFrame):
    """
    Multi-novel task manager widget.
    Integrates directory auto-pairing and multi-file pairing.
    """
    sig_tasks_changed = Signal()

    def __init__(self, icons_dir: Path, parent=None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.setProperty("class", "SubCardFrame")
        self.tasks: list[NovelTaskItem] = []

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Action bar
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.btn_scan_folder = QPushButton("目录自动配对")
        scan_icon = self.icons_dir / "folder-open.svg"
        if scan_icon.is_file():
            self.btn_scan_folder.setIcon(QIcon(str(scan_icon)))
        self.btn_scan_folder.setToolTip("选择包含小说配音与同名SRT字幕的文件夹，系统将自动识别配对")
        self.btn_scan_folder.clicked.connect(self._scan_folder_pairing)

        self.btn_add_files = QPushButton("多选文件配对")
        plus_icon = self.icons_dir / "plus.svg"
        if plus_icon.is_file():
            self.btn_add_files.setIcon(QIcon(str(plus_icon)))
        self.btn_add_files.setToolTip("多选添加多个配音音频文件，并可选择匹配的SRT字幕文件")
        self.btn_add_files.clicked.connect(self._multi_select_pairing)

        self.btn_add_single = QPushButton("添加单篇")
        if plus_icon.is_file():
            self.btn_add_single.setIcon(QIcon(str(plus_icon)))
        self.btn_add_single.clicked.connect(self._add_single_novel)

        self.btn_clear_all = QPushButton("清空")
        trash_icon = self.icons_dir / "trash-2.svg"
        if trash_icon.is_file():
            self.btn_clear_all.setIcon(QIcon(str(trash_icon)))
        self.btn_clear_all.clicked.connect(self._clear_all_tasks)

        act_row.addWidget(self.btn_scan_folder)
        act_row.addWidget(self.btn_add_files)
        act_row.addWidget(self.btn_add_single)
        act_row.addStretch()
        act_row.addWidget(self.btn_clear_all)
        layout.addLayout(act_row)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "#", "小说标题 / 导出前缀", "配音音频 (时长)", "字幕文件", "生成版本", "操作"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(260)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        # Bottom Summary Bar
        summary_row = QHBoxLayout()
        self.lbl_summary = QLabel("共 0 本小说任务 · 预计导出 0 个视频")
        self.lbl_summary.setProperty("class", "SubText")
        self.lbl_summary.setStyleSheet("font-size: 12px; color: #94a3b8;")

        summary_row.addWidget(self.lbl_summary)
        summary_row.addStretch()
        layout.addLayout(summary_row)

    def get_tasks(self) -> list[NovelTaskItem]:
        """Returns the list of current active novel tasks."""
        return list(self.tasks)

    def set_tasks(self, tasks: list[NovelTaskItem]):
        """Sets task list and refreshes the table."""
        self.tasks = list(tasks)
        self._refresh_table()
        self.sig_tasks_changed.emit()

    def add_task(self, task: NovelTaskItem):
        """Appends a new task item and refreshes the table."""
        self.tasks.append(task)
        self._refresh_table()
        self.sig_tasks_changed.emit()

    def _refresh_table(self):
        """Re-populates the QTableWidget with current tasks."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.tasks))

        for row, item in enumerate(self.tasks):
            # 0. Index
            item_idx = QTableWidgetItem(f"{row + 1:02d}")
            item_idx.setTextAlignment(Qt.AlignCenter)
            item_idx.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, item_idx)

            # 1. Novel Title (Editable)
            item_title = QTableWidgetItem(item.novel_title)
            item_title.setToolTip("双击可修改该小说导出的文件名前缀")
            self.table.setItem(row, 1, item_title)

            # 2. Audio & Duration
            dur_text = item.formatted_duration
            audio_info = f"{item.audio_file_name} [{dur_text}]"
            item_audio = QTableWidgetItem(audio_info)
            item_audio.setToolTip(item.audio_path)
            item_audio.setFlags(Qt.ItemIsEnabled)
            if not item.is_valid:
                item_audio.setForeground(Qt.red)
            self.table.setItem(row, 2, item_audio)

            # 3. Subtitle
            sub_info = item.srt_file_name
            item_sub = QTableWidgetItem(sub_info)
            if item.srt_path:
                item_sub.setToolTip(item.srt_path)
            else:
                item_sub.setForeground(Qt.darkYellow)
                item_sub.setToolTip("未匹配到SRT字幕，导出时将不包含字幕图层")
            item_sub.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 3, item_sub)

            # 4. Export Count (SpinBox)
            spin_box = QSpinBox()
            spin_box.setRange(1, 20)
            spin_box.setValue(max(1, item.export_count))
            spin_box.setFixedWidth(65)
            spin_box.valueChanged.connect(
                lambda val, r=row: self._on_count_changed(r, val)
            )
            self.table.setCellWidget(row, 4, spin_box)

            # 5. Remove button
            btn_del = QPushButton()
            trash_icon = self.icons_dir / "trash-2.svg"
            if trash_icon.is_file():
                btn_del.setIcon(QIcon(str(trash_icon)))
            btn_del.setToolTip("移除此任务")
            btn_del.setFixedSize(28, 24)
            btn_del.setProperty("class", "DangerBtn")
            btn_del.clicked.connect(lambda _, r=row: self._remove_task(r))
            self.table.setCellWidget(row, 5, btn_del)

        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self):
        total_novels = len(self.tasks)
        total_exports = sum(t.export_count for t in self.tasks)
        no_sub_count = sum(1 for t in self.tasks if not t.srt_path)
        total_dur = sum(t.audio_duration for t in self.tasks)

        mins = int(total_dur // 60)
        secs = total_dur % 60

        sub_tag = f" · {no_sub_count}篇无字幕" if no_sub_count > 0 else ""
        self.lbl_summary.setText(
            f"共 {total_novels} 本小说任务 · 预计导出 {total_exports} 个成片 · 总音频时长 {mins:02d}:{secs:04.1f}{sub_tag}"
        )

    def _on_count_changed(self, row: int, val: int):
        if 0 <= row < len(self.tasks):
            self.tasks[row].export_count = val
            self._update_summary()
            self.sig_tasks_changed.emit()

    def _on_cell_changed(self, row: int, col: int):
        if col == 1 and 0 <= row < len(self.tasks):
            new_title = self.table.item(row, col).text().strip()
            if new_title:
                self.tasks[row].novel_title = new_title
                self.sig_tasks_changed.emit()

    def _remove_task(self, row: int):
        if 0 <= row < len(self.tasks):
            self.tasks.pop(row)
            self._refresh_table()
            self.sig_tasks_changed.emit()

    def _clear_all_tasks(self):
        if not self.tasks:
            return
        res = QMessageBox.question(
            self, "清空确认", "确定清空当前所有小说任务吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if res == QMessageBox.Yes:
            self.tasks.clear()
            self._refresh_table()
            self.sig_tasks_changed.emit()

    def _scan_folder_pairing(self):
        """Option A: Directory auto-pairing."""
        folder = QFileDialog.getExistingDirectory(self, "选择小说配音与字幕所在文件夹")
        if not folder:
            return

        try:
            matched_items, orphans = NovelBatchMatcher.scan_and_pair_folder(
                folder_path=folder,
                recursive=False,
                probe_durations=True,
                default_count=1
            )
            if not matched_items:
                QMessageBox.information(
                    self, "扫描结果",
                    f"在目录中未找到受支持的配音音频文件 (*.mp3, *.wav, *.m4a, *.aac, *.flac):\n{folder}"
                )
                return

            self.tasks.extend(matched_items)
            self._refresh_table()
            self.sig_tasks_changed.emit()

            matched_with_sub = sum(1 for m in matched_items if m.srt_path)
            orphan_info = f"\n发现 {len(orphans)} 个未匹配的独立字幕文件。" if orphans else ""
            QMessageBox.information(
                self, "导入成功",
                f"成功识别并载入 {len(matched_items)} 本小说！\n"
                f"- 已成功自动配对字幕: {matched_with_sub} 本\n"
                f"- 无字幕纯音频: {len(matched_items) - matched_with_sub} 本{orphan_info}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "扫描失败", f"扫描小说目录异常:\n{exc}")

    def _multi_select_pairing(self):
        """Option B: Multi-select audio and subtitle files."""
        audio_files, _ = QFileDialog.getOpenFileNames(
            self, "选择多个小说配音音频", "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if not audio_files:
            return

        srt_files, _ = QFileDialog.getOpenFileNames(
            self, "选择对应的 SRT 字幕文件 (可多选，系统将按文件名自动匹配，可取消)", "",
            "SRT 字幕文件 (*.srt)"
        )

        try:
            matched_items, orphans = NovelBatchMatcher.pair_files(
                audio_paths=audio_files,
                srt_paths=srt_files or [],
                probe_durations=True,
                default_count=1
            )
            self.tasks.extend(matched_items)
            self._refresh_table()
            self.sig_tasks_changed.emit()

            matched_with_sub = sum(1 for m in matched_items if m.srt_path)
            QMessageBox.information(
                self, "导入成功",
                f"成功添加 {len(matched_items)} 本小说任务！\n"
                f"- 已配对字幕: {matched_with_sub} 本\n"
                f"- 未配对字幕: {len(matched_items) - matched_with_sub} 本"
            )
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", f"配对文件异常:\n{exc}")

    def _add_single_novel(self):
        """Add single novel entry."""
        a_file, _ = QFileDialog.getOpenFileName(
            self, "选择单篇小说配音音频", "",
            "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if not a_file:
            return

        s_file, _ = QFileDialog.getOpenFileName(
            self, "选择对应 SRT 字幕 (可选，无则取消)", "",
            "SRT 字幕文件 (*.srt)"
        )

        item = NovelBatchMatcher.create_single_task(
            audio_path=a_file,
            srt_path=s_file or None,
            export_count=1,
            probe=True
        )
        self.tasks.append(item)
        self._refresh_table()
        self.sig_tasks_changed.emit()
