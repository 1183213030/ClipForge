"""
Timeline Track Widget for ClipForge Stage 5.4.
A custom-painted visual overview representing video segment blocks proportionally,
featuring a real-time playback cursor and interactive seeking.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QWidget

from app.core.edit_project import EditProject


class TimelineTrackWidget(QWidget):
    seek_requested = Signal(float)  # seconds

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.project: Optional[EditProject] = None
        self.current_time_sec: float = 0.0
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def set_project(self, project: EditProject):
        self.project = project
        self.update()

    def set_current_time(self, time_sec: float):
        self.current_time_sec = time_sec
        self.update()

    def mousePressEvent(self, event):
        if not self.project or self.project.assets.audio_duration <= 0:
            return
        w = self.width()
        if w <= 0:
            return
        ratio = max(0.0, min(1.0, event.position().x() / w))
        target_time = ratio * self.project.assets.audio_duration
        self.current_time_sec = target_time
        self.seek_requested.emit(target_time)
        self.update()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#0b0d13"))

        if not self.project or not self.project.video_track:
            painter.setPen(QColor("#475569"))
            painter.setFont(QFont("Microsoft YaHei", 9))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无时间轴片段")
            return

        total_dur = max(0.1, self.project.assets.audio_duration)
        colors = [
            QColor("#1e3a8a"),  # Deep blue
            QColor("#1e293b"),  # Slate dark
            QColor("#0369a1"),  # Sky dark
            QColor("#312e81"),  # Indigo dark
            QColor("#134e4a"),  # Teal dark
        ]

        curr_x = 0.0
        font = QFont("Microsoft YaHei", 8)
        painter.setFont(font)

        # Draw segment blocks
        for idx, seg in enumerate(self.project.video_track):
            seg_w = (seg.duration / total_dur) * w
            rect = QRectF(curr_x, 2, seg_w, h - 4)

            # Fill block
            c = colors[idx % len(colors)]
            painter.setBrush(QBrush(c))
            painter.setPen(QPen(QColor("#334155"), 1))
            painter.drawRoundedRect(rect, 4, 4)

            # Draw block label if wide enough
            if seg_w > 45:
                painter.setPen(QColor("#f8fafc"))
                txt = f"#{idx+1:02d} ({seg.duration:.1f}s)"
                painter.drawText(rect, Qt.AlignCenter, txt)

            curr_x += seg_w

        # Draw Playhead Cursor
        playhead_x = (self.current_time_sec / total_dur) * w
        playhead_x = max(0.0, min(float(w), playhead_x))

        painter.setPen(QPen(QColor("#ef4444"), 2))
        painter.drawLine(int(playhead_x), 0, int(playhead_x), h)

        # Playhead handle (small triangle at top)
        painter.setBrush(QBrush(QColor("#ef4444")))
        painter.setPen(Qt.NoPen)
        points = [
            (int(playhead_x) - 4, 0),
            (int(playhead_x) + 4, 0),
            (int(playhead_x), 6)
        ]
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint
        poly = QPolygon([QPoint(p[0], p[1]) for p in points])
        painter.drawPolygon(poly)
