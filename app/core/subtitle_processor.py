"""
Subtitle Processor Module for ClipForge.
Handles SRT encoding normalization, custom styling, position alignment,
and FFmpeg subtitles filter syntax generation.
"""

from enum import Enum
from pathlib import Path
import re

from app.utils.path_utils import escape_ffmpeg_filter_path, ensure_dir


class SubtitlePosition(str, Enum):
    BOTTOM = "bottom"    # 底部居中 (Alignment=2)
    CENTER = "center"    # 画面正中 (Alignment=5)
    TOP = "top"          # 顶部居中 (Alignment=6)


class SubtitleConfig:
    def __init__(
        self,
        font_name: str = "Microsoft YaHei",
        font_size: int = 20,
        primary_color: str = "&H00FFFFFF",  # ASS Hex: &HAABBGGRR (White)
        outline_color: str = "&H00000000",  # Black outline
        outline_width: int = 2,
        shadow: int = 1,
        position: SubtitlePosition = SubtitlePosition.BOTTOM,
        margin_v: int = 70  # Vertical margin in pixels
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.shadow = shadow
        self.position = position
        self.margin_v = margin_v

    def get_alignment_code(self) -> int:
        """Returns ASS alignment number: 2=bottom-center, 5=middle-center, 6=top-center."""
        if self.position == SubtitlePosition.CENTER:
            return 5
        elif self.position == SubtitlePosition.TOP:
            return 6
        return 2

    def to_force_style_str(self) -> str:
        """Serializes styling into FFmpeg force_style string."""
        alignment = self.get_alignment_code()
        # Note: In ASS styles, MarginV is ignored if Alignment=5 (center), which aligns to exact center
        return (
            f"FontName={self.font_name},"
            f"FontSize={self.font_size},"
            f"PrimaryColour={self.primary_color},"
            f"OutlineColour={self.outline_color},"
            f"Outline={self.outline_width},"
            f"Shadow={self.shadow},"
            f"Alignment={alignment},"
            f"MarginV={self.margin_v}"
        )


def normalize_srt_to_utf8(srt_path: str | Path, temp_dir: str | Path) -> str:
    """
    Reads an SRT file, auto-detects encoding (UTF-8, UTF-8-SIG, GBK, CP936),
    and saves a clean UTF-8 copy in temp_dir.
    """
    raw_path = Path(srt_path).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"SRT 字幕文件不存在: {raw_path}")

    # Read bytes to inspect encoding
    data = raw_path.read_bytes()
    content = ""
    for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"]:
        try:
            content = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not content:
        raise ValueError(f"无法识别 SRT 字幕编码格式: {raw_path}")

    # Ensure UTF-8 clean file
    out_dir = ensure_dir(temp_dir)
    target_path = out_dir / f"clean_{raw_path.stem}.srt"
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def build_subtitles_filter(
    clean_srt_path: str | Path,
    config: SubtitleConfig
) -> str:
    """
    Generates a properly-escaped subtitles filter for FFmpeg:
    subtitles='<escaped_path>':force_style='<style_str>'
    """
    escaped_path = escape_ffmpeg_filter_path(clean_srt_path)
    style_str = config.to_force_style_str()
    return f"subtitles='{escaped_path}':force_style='{style_str}'"
