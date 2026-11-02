"""
Task Item Widget for ClipForge Batch Monitor.
Displays real-time status badge, individual progress bar, elapsed time,
and context action buttons (Open Folder, Retry, Cancel, View Error).
"""

import os
from pathlib import Path
import subprocess
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QProgressBar, QPushButton, QMessageBox
)

from app.services.task_service import TaskRecord, TaskState


class TaskItemWidget(QFrame):
    def __init__(
        self,
        task: TaskRecord,
        icons_dir: Path,
        on_cancel: Optional[Callable[[str], None]] = None,
        on_retry: Optional[Callable[[str], None]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.task = task
        self.icons_dir = icons_dir
        self.on_cancel = on_cancel
        self.on_retry = on_retry
        self.setProperty("class", "SubCardFrame")

        self._init_ui()
        self.update_task_state(task)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Top row: Task name, Badge, and Action buttons
        top_row = QHBoxLayout()
        self.lbl_title = QLabel(f"{self.task.task_id}: {self.task.output_filename}")
        self.lbl_title.setStyleSheet("font-weight: 600; color: #f1f2f6;")

        self.lbl_badge = QLabel("PENDING")
        self.lbl_badge.setProperty("class", "BadgePending")

        top_row.addWidget(self.lbl_title)
        top_row.addWidget(self.lbl_badge)
        top_row.addStretch()

        # Action Buttons
        self.btn_open = QPushButton("打开目录")
        self.btn_open.setVisible(False)
        self.btn_open.clicked.connect(self._open_output_folder)

        self.btn_retry = QPushButton("重试")
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(lambda: self.on_retry(self.task.task_id) if self.on_retry else None)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(lambda: self.on_cancel(self.task.task_id) if self.on_cancel else None)

        self.btn_detail = QPushButton("错误详情")
        self.btn_detail.setVisible(False)
        self.btn_detail.clicked.connect(self._show_error_dialog)

        top_row.addWidget(self.btn_open)
        top_row.addWidget(self.btn_retry)
        top_row.addWidget(self.btn_cancel)
        top_row.addWidget(self.btn_detail)
        layout.addLayout(top_row)

        # Bottom row: Progress bar and status info
        bot_row = QHBoxLayout()
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)

        self.lbl_info = QLabel("等待执行...")
        self.lbl_info.setProperty("class", "SubText")
        self.lbl_info.setMinimumWidth(80)

        bot_row.addWidget(self.prog_bar)
        bot_row.addWidget(self.lbl_info)
        layout.addLayout(bot_row)

    def update_task_state(self, task: TaskRecord):
        self.task = task
        percent = int(task.progress * 100)
        self.prog_bar.setValue(percent)

        if task.state == TaskState.PENDING:
            self.lbl_badge.setText("等待中")
            self.lbl_badge.setProperty("class", "BadgePending")
            self.lbl_info.setText("排队等待")
            self.btn_open.setVisible(False)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(True)
            self.btn_detail.setVisible(False)

        elif task.state == TaskState.RUNNING:
            self.lbl_badge.setText("导出中")
            self.lbl_badge.setProperty("class", "BadgeRunning")
            self.lbl_info.setText(f"{percent}%")
            self.btn_open.setVisible(False)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(True)
            self.btn_detail.setVisible(False)

        elif task.state == TaskState.SUCCESS:
            self.lbl_badge.setText("已完成")
            self.lbl_badge.setProperty("class", "BadgeSuccess")
            self.lbl_info.setText(f"耗时 {task.elapsed_seconds}s")
            self.btn_open.setVisible(True)
            self.btn_retry.setVisible(False)
            self.btn_cancel.setVisible(False)
            self.btn_detail.setVisible(False)

        elif task.state == TaskState.FAILED:
            self.lbl_badge.setText("失败")
            self.lbl_badge.setProperty("class", "BadgeFailed")
            self.lbl_info.setText("执行异常")
            self.btn_open.setVisible(False)
            self.btn_retry.setVisible(True)
            self.btn_cancel.setVisible(False)
            self.btn_detail.setVisible(True)

        elif task.state == TaskState.CANCELLED:
            self.lbl_badge.setText("已取消")
            self.lbl_badge.setProperty("class", "BadgeCancelled")
            self.lbl_info.setText("用户中止")
            self.btn_open.setVisible(False)
            self.btn_retry.setVisible(True)
            self.btn_cancel.setVisible(False)
            self.btn_detail.setVisible(False)

        # Re-apply CSS property style
        self.lbl_badge.style().unpolish(self.lbl_badge)
        self.lbl_badge.style().polish(self.lbl_badge)

    def _open_output_folder(self):
        if self.task.final_output_path and os.path.isfile(self.task.final_output_path):
            folder = str(Path(self.task.final_output_path).parent)
            if os.name == "nt":
                subprocess.Popen(f'explorer /select,"{self.task.final_output_path}"')
            else:
                os.system(f'open "{folder}"')

    def _show_error_dialog(self):
        QMessageBox.critical(
            self,
            f"任务失败 - {self.task.task_id}",
            f"错误原因:\n{self.task.error_message or '未知错误'}\n\n日志归档: {self.task.log_file}"
        )
