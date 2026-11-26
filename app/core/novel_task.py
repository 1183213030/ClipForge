"""
Novel Task Management and Batch Pairing Module for ClipForge.
Enables multi-novel batch video generation, directory auto-pairing,
and multi-select file pairing with audio duration probing.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Optional

from app.core.media_probe import probe_media
from app.utils.path_utils import normalize_path

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SUPPORTED_SUBTITLE_EXTENSIONS = {".srt"}


@dataclass
class NovelTaskItem:
    """Represents a single novel unit containing audio and optional SRT subtitle."""
    task_id: str
    novel_title: str
    audio_path: str
    srt_path: Optional[str] = None
    audio_duration: float = 0.0
    audio_codec: str = ""
    export_count: int = 1
    is_valid: bool = True
    status_text: str = ""

    @property
    def audio_file_name(self) -> str:
        return Path(self.audio_path).name if self.audio_path else ""

    @property
    def srt_file_name(self) -> str:
        return Path(self.srt_path).name if self.srt_path else "未配置字幕"

    @property
    def formatted_duration(self) -> str:
        if self.audio_duration <= 0:
            return "未知时长"
        mins = int(self.audio_duration // 60)
        secs = self.audio_duration % 60
        return f"{mins:02d}:{secs:04.1f} ({self.audio_duration:.1f}s)"

    def probe(self, force: bool = False) -> bool:
        """Probes audio duration and codec metadata if not yet probed."""
        if not self.audio_path or not Path(self.audio_path).is_file():
            self.is_valid = False
            self.status_text = "音频文件不存在"
            return False

        if self.audio_duration > 0 and not force:
            return True

        try:
            norm_audio = normalize_path(self.audio_path)
            meta = probe_media(norm_audio)
            if not meta.is_valid_audio:
                self.is_valid = False
                self.status_text = "无效或损坏的音频"
                return False

            self.audio_duration = float(meta.duration or 0.0)
            self.audio_codec = meta.audio_codec or ""
            self.is_valid = True
            if not self.srt_path:
                self.status_text = "就绪 (无字幕烧录)"
            else:
                self.status_text = "就绪"
            return True
        except Exception as exc:
            logger.warning(f"探测音频元数据失败: {self.audio_path}, error={exc}")
            self.is_valid = False
            self.status_text = f"探测失败: {exc}"
            return False


class NovelBatchMatcher:
    """Utilities for scanning directories and auto-pairing novel audio and SRT subtitles."""

    @staticmethod
    def normalize_stem(path_or_str: str | Path) -> str:
        """Normalizes file stem for fuzzy matching (case-insensitive, trimmed)."""
        stem = Path(path_or_str).stem.strip().lower()
        return stem

    @classmethod
    def scan_and_pair_folder(
        cls,
        folder_path: str | Path,
        recursive: bool = False,
        probe_durations: bool = True,
        default_count: int = 1
    ) -> tuple[list[NovelTaskItem], list[str]]:
        """
        Scans a directory for audio and SRT files, matching them by base name.
        Returns:
            (matched_tasks, orphan_notes)
        """
        target_dir = Path(folder_path).resolve()
        if not target_dir.is_dir():
            raise FileNotFoundError(f"指定的目录不存在: {target_dir}")

        pattern = "**/*" if recursive else "*"
        all_files = [f for f in target_dir.glob(pattern) if f.is_file()]

        audio_files: list[Path] = []
        srt_files: list[Path] = []

        for f in all_files:
            ext = f.suffix.lower()
            if ext in SUPPORTED_AUDIO_EXTENSIONS:
                audio_files.append(f)
            elif ext in SUPPORTED_SUBTITLE_EXTENSIONS:
                srt_files.append(f)

        return cls.pair_files(
            audio_paths=audio_files,
            srt_paths=srt_files,
            probe_durations=probe_durations,
            default_count=default_count
        )

    @classmethod
    def pair_files(
        cls,
        audio_paths: list[Path | str],
        srt_paths: list[Path | str],
        probe_durations: bool = True,
        default_count: int = 1
    ) -> tuple[list[NovelTaskItem], list[str]]:
        """
        Pairs audio files and SRT files by filename stem.
        Handles exact matches, case-insensitive matches, and orphan reports.
        """
        # Map normalized stem -> list of srt paths
        srt_map: dict[str, list[Path]] = {}
        for s in srt_paths:
            p = Path(s).resolve()
            stem = cls.normalize_stem(p)
            srt_map.setdefault(stem, []).append(p)

        matched_items: list[NovelTaskItem] = []
        orphan_notes: list[str] = []
        used_srts: set[Path] = set()

        # Sort audio paths deterministically
        sorted_audios = sorted(
            [Path(a).resolve() for a in audio_paths],
            key=lambda p: p.name.lower()
        )

        for i, a_path in enumerate(sorted_audios):
            task_id = f"NOVEL_{i + 1:03d}"
            novel_title = a_path.stem
            stem = cls.normalize_stem(a_path)

            matched_srt: Optional[str] = None
            if stem in srt_map and srt_map[stem]:
                # Pick first unused matching SRT
                for candidate in srt_map[stem]:
                    if candidate not in used_srts:
                        matched_srt = str(candidate)
                        used_srts.add(candidate)
                        break

            item = NovelTaskItem(
                task_id=task_id,
                novel_title=novel_title,
                audio_path=str(a_path),
                srt_path=matched_srt,
                export_count=default_count,
                status_text="就绪" if matched_srt else "无字幕 (仅音频)"
            )

            if probe_durations:
                item.probe()

            matched_items.append(item)

        # Detect unused orphan SRT files
        for s in srt_paths:
            p = Path(s).resolve()
            if p not in used_srts:
                orphan_notes.append(f"未配对字幕: {p.name}")

        return matched_items, orphan_notes

    @classmethod
    def create_single_task(
        cls,
        audio_path: str | Path,
        srt_path: Optional[str | Path] = None,
        export_count: int = 1,
        probe: bool = True
    ) -> NovelTaskItem:
        """Creates a single NovelTaskItem instance."""
        p_audio = Path(audio_path).resolve()
        item = NovelTaskItem(
            task_id="NOVEL_001",
            novel_title=p_audio.stem,
            audio_path=str(p_audio),
            srt_path=str(Path(srt_path).resolve()) if srt_path else None,
            export_count=export_count
        )
        if probe:
            item.probe()
        return item
