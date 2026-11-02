"""
Asset Selection and Scanning Card Widget for ClipForge.
Manages input paths for novel audio, SRT subtitles, and video clips directory.
Displays real-time scan statistics with background thread integration.
"""

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog
)

from app.core.media_scanner import ScanResult
from app.ui.threads import ScanFolderThread, ProbeAudioThread


class AssetCardWidget(QFrame):
    def __init__(self, icons_dir: Path, parent=None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.setProperty("class", "CardFrame")

        self.audio_path: Optional[str] = None
        self.srt_path: Optional[str] = None
        self.video_folder: Optional[str] = None
        self.scan_result: Optional[ScanResult] = None

        self._scan_thread: Optional[ScanFolderThread] = None
        self._probe_thread: Optional[ProbeAudioThread] = None

        # Callbacks
        self.on_assets_changed: Optional[Callable[[], None]] = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setPixmap(QIcon(str(self.icons_dir / "film.svg")).pixmap(QSize(18, 18)))
        title_lbl = QLabel("素材导入与管理")
        title_lbl.setProperty("class", "SectionTitle")
        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 1. Novel Audio row
        self.audio_input = QLineEdit()
        self.audio_input.setPlaceholderText("选择小说配音音频 (MP3, WAV, M4A)...")
        self.audio_input.setReadOnly(True)
        btn_browse_audio = QPushButton("浏览音频")
        btn_browse_audio.clicked.connect(self._browse_audio)

        self.audio_info_lbl = QLabel("未选择音频")
        self.audio_info_lbl.setProperty("class", "SubText")

        audio_row = QHBoxLayout()
        audio_row.addWidget(self.audio_input)
        audio_row.addWidget(btn_browse_audio)
        layout.addLayout(audio_row)
        layout.addWidget(self.audio_info_lbl)

        # 2. SRT Subtitle row
        self.srt_input = QLineEdit()
        self.srt_input.setPlaceholderText("选择对应 SRT 字幕文件 (UTF-8 / GBK)...")
        self.srt_input.setReadOnly(True)
        btn_browse_srt = QPushButton("浏览字幕")
        btn_browse_srt.clicked.connect(self._browse_srt)

        self.srt_info_lbl = QLabel("未选择字幕")
        self.srt_info_lbl.setProperty("class", "SubText")

        srt_row = QHBoxLayout()
        srt_row.addWidget(self.srt_input)
        srt_row.addWidget(btn_browse_srt)
        layout.addLayout(srt_row)
        layout.addWidget(self.srt_info_lbl)

        # 3. Video folder row
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("选择解压视频素材文件夹...")
        self.folder_input.setReadOnly(True)
        btn_browse_folder = QPushButton("选择文件夹")
        btn_browse_folder.clicked.connect(self._browse_folder)

        self.btn_rescan = QPushButton("重新扫描")
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.clicked.connect(self._start_scan)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_input)
        folder_row.addWidget(btn_browse_folder)
        folder_row.addWidget(self.btn_rescan)
        layout.addLayout(folder_row)

        # 4. Scan stats sub-card
        self.stats_frame = QFrame()
        self.stats_frame.setProperty("class", "SubCardFrame")
        stats_layout = QHBoxLayout(self.stats_frame)
        stats_layout.setContentsMargins(12, 10, 12, 10)

        self.lbl_valid_stat = QLabel("有效素材: 0")
        self.lbl_valid_stat.setStyleSheet("color: #34d399; font-weight: 600;")
        self.lbl_dup_stat = QLabel("重复排除: 0")
        self.lbl_dup_stat.setStyleSheet("color: #94a3b8;")
        self.lbl_bad_stat = QLabel("损坏/无效: 0")
        self.lbl_bad_stat.setStyleSheet("color: #f87171;")
        self.lbl_dur_stat = QLabel("总时长: 0.0s")
        self.lbl_dur_stat.setStyleSheet("color: #60a5fa; font-weight: 600;")

        stats_layout.addWidget(self.lbl_valid_stat)
        stats_layout.addWidget(self.lbl_dup_stat)
        stats_layout.addWidget(self.lbl_bad_stat)
        stats_layout.addStretch()
        stats_layout.addWidget(self.lbl_dur_stat)

        layout.addWidget(self.stats_frame)

    def _browse_audio(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择小说配音音频", "", "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac)"
        )
        if f:
            self.audio_path = f
            self.audio_input.setText(Path(f).name)
            self.audio_info_lbl.setText("正在探测音频元数据...")
            
            # Probe audio asynchronously
            self._probe_thread = ProbeAudioThread(f)
            self._probe_thread.sig_finished.connect(self._on_audio_probed)
            self._probe_thread.sig_error.connect(lambda err: self.audio_info_lbl.setText(f"音频错误: {err}"))
            self._probe_thread.start()

    def _on_audio_probed(self, meta):
        mins = int(meta.duration // 60)
        secs = meta.duration % 60
        self.audio_info_lbl.setText(f"音频时长: {mins:02d}:{secs:04.1f} ({meta.duration:.2f}s) | 编码: {meta.audio_codec}")
        self._notify_change()

    def _browse_srt(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择对应中文字幕", "", "SRT 字幕文件 (*.srt)"
        )
        if f:
            self.srt_path = f
            self.srt_input.setText(Path(f).name)
            self.srt_info_lbl.setText(f"字幕文件就绪: {Path(f).name}")
            self._notify_change()

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频素材文件夹")
        if d:
            self.video_folder = d
            self.folder_input.setText(d)
            self.btn_rescan.setEnabled(True)
            self._start_scan()

    def _start_scan(self):
        if not self.video_folder:
            return
        self.btn_rescan.setEnabled(False)
        self.lbl_valid_stat.setText("扫描中...")
        self.lbl_dup_stat.setText("")
        self.lbl_bad_stat.setText("")
        self.lbl_dur_stat.setText("")

        self._scan_thread = ScanFolderThread(self.video_folder)
        self._scan_thread.sig_finished.connect(self._on_scan_finished)
        self._scan_thread.sig_error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_scan_finished(self, result: ScanResult):
        self.scan_result = result
        self.btn_rescan.setEnabled(True)

        dup_count = sum(1 for e in result.excluded_clips if "DUPLICATE_FILE" in e.reason)
        bad_count = result.excluded_count - dup_count

        self.lbl_valid_stat.setText(f"有效素材: {result.valid_count}")
        self.lbl_dup_stat.setText(f"重复排除: {dup_count}")
        self.lbl_bad_stat.setText(f"损坏/无效: {bad_count}")
        self.lbl_dur_stat.setText(f"总时长: {result.total_duration:.1f}s")

        self._notify_change()

    def _on_scan_error(self, err: str):
        self.btn_rescan.setEnabled(True)
        self.lbl_valid_stat.setText("扫描失败")
        self.lbl_bad_stat.setText(err[:40])

    def _notify_change(self):
        if self.on_assets_changed:
            self.on_assets_changed()
