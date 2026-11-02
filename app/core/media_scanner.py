"""
Media Scanner Module for ClipForge.
Scans folders for video assets, extracts metadata, validates streams,
and de-duplicates exact duplicate files via SHA-256 file hashing.
"""

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Optional

from app.core.media_probe import probe_media, MediaMetadata
from app.utils.path_utils import normalize_path


SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".m4v", ".wmv"
}


@dataclass
class ClipInfo:
    path: str
    sha256: str
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    has_audio: bool
    file_size: int

    @property
    def display_name(self) -> str:
        return Path(self.path).name


@dataclass
class ExcludedClipInfo:
    path: str
    reason: str
    details: str = ""


@dataclass
class ScanResult:
    folder_path: str
    valid_clips: list[ClipInfo] = field(default_factory=list)
    excluded_clips: list[ExcludedClipInfo] = field(default_factory=list)
    total_duration: float = 0.0

    @property
    def valid_count(self) -> int:
        return len(self.valid_clips)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_clips)


def calculate_file_sha256(file_path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculates SHA-256 hash of a file efficiently using chunk streaming."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


class MediaScanner:
    def __init__(self, supported_extensions: Optional[set[str]] = None):
        self.supported_extensions = supported_extensions or SUPPORTED_VIDEO_EXTENSIONS

    def scan_directory(self, folder_path: str | Path, recursive: bool = False) -> ScanResult:
        """
        Scans directory for supported video assets.
        Validates metadata and deduplicates identical files via SHA-256.
        """
        target_dir = Path(folder_path).resolve()
        if not target_dir.is_dir():
            raise FileNotFoundError(f"素材目录不存在: {target_dir}")

        result = ScanResult(folder_path=str(target_dir))
        seen_hashes: dict[str, str] = {}  # sha256 -> first_file_path

        # Gather files
        pattern = "**/*" if recursive else "*"
        candidate_files = [
            f for f in target_dir.glob(pattern)
            if f.is_file() and f.suffix.lower() in self.supported_extensions
        ]

        # Sort candidate files deterministically by name
        candidate_files.sort(key=lambda p: p.name.lower())

        for file_path in candidate_files:
            norm_path = normalize_path(file_path)

            # 1. Probe media
            try:
                meta: MediaMetadata = probe_media(norm_path)
            except Exception as e:
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="CORRUPTED_OR_UNREADABLE",
                        details=f"元数据读取失败: {str(e)}"
                    )
                )
                continue

            # 2. Check video validity
            if not meta.has_video:
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="NO_VIDEO_STREAM",
                        details="文件不包含有效视频流"
                    )
                )
                continue

            if meta.duration <= 0.05:
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="ZERO_OR_TOO_SHORT_DURATION",
                        details=f"视频时长过短 ({meta.duration:.2f}s)"
                    )
                )
                continue

            if meta.width <= 0 or meta.height <= 0:
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="INVALID_RESOLUTION",
                        details=f"异常分辨率 ({meta.width}x{meta.height})"
                    )
                )
                continue

            # 3. Calculate SHA-256 for exact file deduplication
            try:
                file_hash = calculate_file_sha256(norm_path)
            except Exception as e:
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="HASH_CALCULATION_FAILED",
                        details=str(e)
                    )
                )
                continue

            if file_hash in seen_hashes:
                first_file = seen_hashes[file_hash]
                result.excluded_clips.append(
                    ExcludedClipInfo(
                        path=norm_path,
                        reason="DUPLICATE_FILE",
                        details=f"与已有素材内容完全一致 (首见文件: {Path(first_file).name})"
                    )
                )
                continue

            seen_hashes[file_hash] = norm_path
            clip = ClipInfo(
                path=norm_path,
                sha256=file_hash,
                duration=meta.duration,
                width=meta.width,
                height=meta.height,
                fps=meta.fps,
                video_codec=meta.video_codec,
                audio_codec=meta.audio_codec,
                has_audio=meta.has_audio,
                file_size=file_path.stat().st_size
            )
            result.valid_clips.append(clip)
            result.total_duration += clip.duration

        return result
