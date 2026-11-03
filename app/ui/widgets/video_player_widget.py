"""
Video Player Widget for ClipForge Stage 5.4.
Provides a 9:16 vertical video preview using PySide6 QtMultimedia (QMediaPlayer + QVideoWidget),
with play/pause toggles, seek bar, timecode display, and volume control.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFrame, QSizePolicy
)


class VideoPlayerWidget(QWidget):
    position_changed = Signal(int)  # ms
    duration_changed = Signal(int)  # ms

    def __init__(self, icons_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.current_media_path: Optional[str] = None
        self._is_seeking = False

        self._init_player()
        self._init_ui()

    def _init_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)
        self.player.errorOccurred.connect(self._on_player_error)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. 9:16 Aspect-Ratio Viewport Container
        self.video_container = QFrame()
        self.video_container.setStyleSheet(
            "background-color: #050608; border-radius: 8px; border: 1px solid #1e222d;"
        )
        container_layout = QVBoxLayout(self.video_container)
        container_layout.setContentsMargins(2, 2, 2, 2)
        container_layout.setAlignment(Qt.AlignCenter)

        self.video_widget = QVideoWidget(self.video_container)
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        # 9:16 ideal vertical preview size
        self.video_widget.setMinimumSize(270, 480)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container_layout.addWidget(self.video_widget)

        self.player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_container, stretch=1)

        # Status / Error Banner (Hidden unless error occurs)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 11px;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.hide()
        layout.addWidget(self.lbl_status)

        # 2. Scrub / Seek Slider
        self.slider_progress = QSlider(Qt.Horizontal)
        self.slider_progress.setRange(0, 1000)
        self.slider_progress.setValue(0)
        self.slider_progress.setCursor(Qt.PointingHandCursor)
        self.slider_progress.sliderPressed.connect(self._on_slider_pressed)
        self.slider_progress.sliderMoved.connect(self._on_slider_moved)
        self.slider_progress.sliderReleased.connect(self._on_slider_released)
        layout.addWidget(self.slider_progress)

        # 3. Controls Toolbar
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setContentsMargins(4, 0, 4, 0)
        ctrl_layout.setSpacing(10)

        # Play / Pause Button
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(34, 34)
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self._update_play_icon(False)
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.btn_play)

        # Timecode Label: 00:00 / 00:00
        self.lbl_timecode = QLabel("00:00 / 00:00")
        self.lbl_timecode.setStyleSheet(
            "color: #94a3b8; font-family: monospace; font-size: 12px; font-weight: 500;"
        )
        ctrl_layout.addWidget(self.lbl_timecode)

        ctrl_layout.addStretch()

        # Volume Controls
        lbl_vol = QLabel()
        vol_icon = self.icons_dir / "volume-2.svg"
        if vol_icon.is_file():
            lbl_vol.setPixmap(QIcon(str(vol_icon)).pixmap(QSize(16, 16)))
        ctrl_layout.addWidget(lbl_vol)

        self.slider_volume = QSlider(Qt.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(80)
        self.slider_volume.setFixedWidth(80)
        self.slider_volume.setCursor(Qt.PointingHandCursor)
        self.audio_output.setVolume(0.8)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        ctrl_layout.addWidget(self.slider_volume)

        layout.addLayout(ctrl_layout)

    def load_media(self, file_path: str | Path):
        """Loads video file for playback."""
        p = Path(file_path).resolve()
        if not p.is_file():
            self.lbl_status.setText(f"预览视频未找到: {p.name}")
            self.lbl_status.show()
            return

        self.current_media_path = str(p)
        self.lbl_status.hide()
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self._update_play_icon(False)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self._update_play_icon(False)
        else:
            self.player.play()
            self._update_play_icon(True)

    def play(self):
        self.player.play()
        self._update_play_icon(True)

    def pause(self):
        self.player.pause()
        self._update_play_icon(False)

    def seek(self, position_ms: int):
        self.player.setPosition(position_ms)

    def _update_play_icon(self, is_playing: bool):
        icon_file = "pause.svg" if is_playing else "play.svg"
        p = self.icons_dir / icon_file
        if p.is_file():
            self.btn_play.setIcon(QIcon(str(p)))
            self.btn_play.setIconSize(QSize(18, 18))
        else:
            self.btn_play.setText("暂停" if is_playing else "播放")

    def _on_player_position_changed(self, pos_ms: int):
        if not self._is_seeking:
            dur_ms = self.player.duration()
            if dur_ms > 0:
                self.slider_progress.setValue(int(pos_ms * 1000 / dur_ms))
            self._update_timecode(pos_ms, dur_ms)
        self.position_changed.emit(pos_ms)

    def _on_player_duration_changed(self, dur_ms: int):
        self._update_timecode(self.player.position(), dur_ms)
        self.duration_changed.emit(dur_ms)

    def _update_timecode(self, pos_ms: int, dur_ms: int):
        cur_sec = int(pos_ms // 1000)
        tot_sec = int(dur_ms // 1000) if dur_ms > 0 else 0
        cur_str = f"{cur_sec // 60:02d}:{cur_sec % 60:02d}"
        tot_str = f"{tot_sec // 60:02d}:{tot_sec % 60:02d}"
        self.lbl_timecode.setText(f"{cur_str} / {tot_str}")

    def _on_slider_pressed(self):
        self._is_seeking = True

    def _on_slider_moved(self, val: int):
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_ms = int(val * dur_ms / 1000)
            self._update_timecode(target_ms, dur_ms)

    def _on_slider_released(self):
        dur_ms = self.player.duration()
        if dur_ms > 0:
            target_ms = int(self.slider_progress.value() * dur_ms / 1000)
            self.player.setPosition(target_ms)
        self._is_seeking = False

    def _on_volume_changed(self, val: int):
        self.audio_output.setVolume(val / 100.0)

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.NoError:
            self.lbl_status.setText(f"解码器播放提示: {error_string}")
            self.lbl_status.show()
