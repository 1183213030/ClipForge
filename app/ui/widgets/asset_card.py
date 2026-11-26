"""
Asset Selection and Scanning Card Widget for ClipForge.
Manages input paths for novel audio, SRT subtitles, and video clips directory.
Supports both Single Novel Mode and Multi-Novel Batch Mode (Directory & Multi-file).
Displays real-time scan statistics with background thread integration.
"""

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QStackedWidget
)

from app.core.media_scanner import ScanResult
from app.core.novel_task import NovelTaskItem, NovelBatchMatcher
from app.ui.threads import ScanFolderThread, ProbeAudioThread
from app.ui.widgets.novel_batch_widget import NovelBatchWidget


class AssetCardWidget(QFrame):
    def __init__(self, icons_dir: Path, parent=None):
        super().__init__(parent)
        self.icons_dir = icons_dir
        self.setProperty("class", "CardFrame")

        self.project_root = self.icons_dir.parent.parent
        self.audio_path: Optional[str] = None
        self.audio_duration: float = 0.0
        self.srt_path: Optional[str] = None
        self.video_folder: Optional[str] = None
        self.template_path: Optional[str] = None
        self.enable_template: bool = True
        self.scan_result: Optional[ScanResult] = None
        self.is_batch_mode: bool = False

        self._scan_thread: Optional[ScanFolderThread] = None
        self._probe_thread: Optional[ProbeAudioThread] = None

        # Callbacks
        self.on_assets_changed: Optional[Callable[[], None]] = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header with Mode Switcher
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        icon_lbl = QLabel()
        film_icon = self.icons_dir / "film.svg"
        if film_icon.is_file():
            icon_lbl.setPixmap(QIcon(str(film_icon)).pixmap(QSize(18, 18)))
        title_lbl = QLabel("素材导入与管理")
        title_lbl.setProperty("class", "SectionTitle")

        header_layout.addWidget(icon_lbl)
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        # Mode Switcher Tabs
        self.btn_mode_single = QPushButton("单篇混剪")
        self.btn_mode_single.setProperty("class", "NavTabBtnActive")
        self.btn_mode_single.setCursor(Qt.PointingHandCursor)
        self.btn_mode_single.setToolTip("针对单篇小说音频与字幕进行快速混剪或生成多版差异成片")
        self.btn_mode_single.clicked.connect(lambda: self.set_mode(False))

        self.btn_mode_batch = QPushButton("多篇批量模式")
        self.btn_mode_batch.setProperty("class", "NavTabBtn")
        self.btn_mode_batch.setCursor(Qt.PointingHandCursor)
        self.btn_mode_batch.setToolTip("支持多本小说目录自动配对导入与任务清单管理")
        self.btn_mode_batch.clicked.connect(lambda: self.set_mode(True))

        header_layout.addWidget(self.btn_mode_single)
        header_layout.addWidget(self.btn_mode_batch)
        layout.addLayout(header_layout)

        # Novel Inputs Container (Stacked: 0=Single, 1=Batch)
        self.novel_stack = QStackedWidget()

        # Page 0: Single Novel Mode
        single_page = QWidget()
        single_layout = QVBoxLayout(single_page)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(8)

        # 1. Single Novel Audio row
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
        single_layout.addLayout(audio_row)
        single_layout.addWidget(self.audio_info_lbl)

        # 2. Single SRT Subtitle row
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
        single_layout.addLayout(srt_row)
        single_layout.addWidget(self.srt_info_lbl)

        self.novel_stack.addWidget(single_page)

        # Page 1: Multi-Novel Batch Mode
        self.novel_batch_widget = NovelBatchWidget(self.icons_dir)
        self.novel_batch_widget.sig_tasks_changed.connect(self._notify_change)
        self.novel_stack.addWidget(self.novel_batch_widget)

        layout.addWidget(self.novel_stack)

        # 3. Shared Video folder row
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("选择解压视频素材文件夹 (所有小说任务共享画面素材池)...")
        self.folder_input.setReadOnly(True)
        btn_browse_folder = QPushButton("选择素材文件夹")
        btn_browse_folder.clicked.connect(self._browse_folder)

        self.btn_rescan = QPushButton("重新扫描")
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.clicked.connect(self._start_scan)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_input)
        folder_row.addWidget(btn_browse_folder)
        folder_row.addWidget(self.btn_rescan)
        layout.addLayout(folder_row)

        # 4. Novel Tweet Template PNG Row (Corner badge, branding, bottom disclaimer)
        tpl_header_row = QHBoxLayout()
        self.chk_template = QCheckBox("启用推文模板图层 (PNG)")
        self.chk_template.setChecked(True)
        self.chk_template.setStyleSheet("color: #60a5fa; font-weight: 600; font-size: 12px;")
        self.chk_template.toggled.connect(self._on_template_toggled)
        tpl_header_row.addWidget(self.chk_template)
        tpl_header_row.addStretch()
        layout.addLayout(tpl_header_row)

        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("选择推文透明模板 PNG (含右上角角标、左下标识与底部免责声明)...")
        self.template_input.setReadOnly(True)
        self.btn_browse_template = QPushButton("浏览模板")
        self.btn_browse_template.clicked.connect(self._browse_template)

        tpl_row = QHBoxLayout()
        tpl_row.addWidget(self.template_input)
        tpl_row.addWidget(self.btn_browse_template)
        layout.addLayout(tpl_row)

        self.template_info_lbl = QLabel("未选择模板")
        self.template_info_lbl.setProperty("class", "SubText")
        layout.addWidget(self.template_info_lbl)

        # Auto-detect bundled template
        self._auto_detect_template()

        # 5. Scan stats sub-card
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

    def set_mode(self, is_batch: bool):
        """Switches between Single Novel Mode and Multi-Novel Batch Mode."""
        self.is_batch_mode = is_batch
        if is_batch:
            self.btn_mode_single.setProperty("class", "NavTabBtn")
            self.btn_mode_batch.setProperty("class", "NavTabBtnActive")
            self.novel_stack.setCurrentIndex(1)
            # Auto-migrate single novel to batch list if batch list is empty
            if self.audio_path and not self.novel_batch_widget.tasks:
                single_item = NovelTaskItem(
                    task_id="NOVEL_001",
                    novel_title=Path(self.audio_path).stem,
                    audio_path=self.audio_path,
                    srt_path=self.srt_path,
                    audio_duration=self.audio_duration,
                    export_count=1
                )
                self.novel_batch_widget.add_task(single_item)
        else:
            self.btn_mode_single.setProperty("class", "NavTabBtnActive")
            self.btn_mode_batch.setProperty("class", "NavTabBtn")
            self.novel_stack.setCurrentIndex(0)

        self.btn_mode_single.style().unpolish(self.btn_mode_single)
        self.btn_mode_single.style().polish(self.btn_mode_single)
        self.btn_mode_batch.style().unpolish(self.btn_mode_batch)
        self.btn_mode_batch.style().polish(self.btn_mode_batch)

        self._notify_change()

    def get_novel_tasks(self, default_count: int = 1) -> list[NovelTaskItem]:
        """Returns novel task items according to active mode."""
        if self.is_batch_mode:
            return self.novel_batch_widget.get_tasks()

        if self.audio_path and Path(self.audio_path).is_file():
            return [
                NovelTaskItem(
                    task_id="NOVEL_001",
                    novel_title=Path(self.audio_path).stem,
                    audio_path=self.audio_path,
                    srt_path=self.srt_path,
                    audio_duration=self.audio_duration,
                    export_count=default_count,
                    is_valid=True
                )
            ]
        return []

    def _auto_detect_template(self):
        """Auto-detect bundled customer novel tweet template."""
        candidates = [
            self.project_root / "resources" / "templates" / "customer_template.png",
            self.project_root / "templates" / "customer_template.png",
        ]
        for c in candidates:
            if c.is_file():
                self._set_template_file(str(c), auto=True)
                return

    def _browse_template(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择推文模板透明 PNG", "", "PNG 图片 (*.png)"
        )
        if f:
            self._set_template_file(f, auto=False)

    def _set_template_file(self, file_path: str, auto: bool = False):
        p = Path(file_path)
        if not p.is_file():
            return
        self.template_path = str(p.resolve())
        self.template_input.setText(p.name)

        # Inspect dimensions & transparency
        try:
            from PIL import Image
            with Image.open(self.template_path) as im:
                w, h = im.size
                mode = im.mode
                has_alpha = "A" in mode
                tag = " (默认模板已自动装载)" if auto else ""
                if has_alpha:
                    self.template_info_lbl.setText(f"模板就绪: {w}x{h} RGBA 透明通道正常{tag}")
                    self.template_info_lbl.setStyleSheet("color: #34d399;")
                else:
                    self.template_info_lbl.setText(f"警告: 模板为 {mode} 格式，未检测到透明 Alpha 通道{tag}")
                    self.template_info_lbl.setStyleSheet("color: #f59e0b;")
        except Exception:
            self.template_info_lbl.setText(f"模板就绪: {p.name}")
            self.template_info_lbl.setStyleSheet("color: #34d399;")

        self._notify_change()

    def _on_template_toggled(self, checked: bool):
        self.enable_template = checked
        self.template_input.setEnabled(checked)
        self.btn_browse_template.setEnabled(checked)
        self.template_info_lbl.setEnabled(checked)
        self._notify_change()

    def _browse_audio(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择小说配音音频", "", "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac)"
        )
        if f:
            self.audio_path = f
            self.audio_duration = 0.0
            self.audio_input.setText(Path(f).name)
            self.audio_info_lbl.setText("正在探测音频元数据...")

            # Probe audio asynchronously
            self._probe_thread = ProbeAudioThread(f)
            self._probe_thread.sig_finished.connect(self._on_audio_probed)
            self._probe_thread.sig_error.connect(lambda err: self.audio_info_lbl.setText(f"音频错误: {err}"))
            self._probe_thread.start()

    def _on_audio_probed(self, meta):
        self.audio_duration = float(meta.duration or 0.0)
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
