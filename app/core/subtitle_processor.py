"""
Subtitle Processor Module for ClipForge.
Handles SRT encoding normalization, intelligent line wrapping (protecting words & URLs),
custom styling, position alignment, and FFmpeg subtitles filter syntax generation.
"""

from enum import Enum
from pathlib import Path
import re
from typing import Optional

from app.utils.path_utils import escape_ffmpeg_filter_path, ensure_dir


class SubtitlePosition(str, Enum):
    BOTTOM = "bottom"    # 底部居中 (Alignment=2)
    CENTER = "center"    # 画面正中 (Alignment=5)
    TOP = "top"          # 顶部居中 (Alignment=6)


class SubtitleConfig:
    def __init__(
        self,
        font_name: str = "Microsoft YaHei",
        font_size: int = 22,
        primary_color: str = "&H00FFFFFF",  # ASS Hex: &HAABBGGRR (White)
        outline_color: str = "&H00000000",  # Black outline
        outline_width: int = 2,
        shadow: int = 1,
        position: SubtitlePosition = SubtitlePosition.BOTTOM,
        margin_v: int = 100,  # Vertical margin in pixels
        margin_l: int = 60,   # Left safety margin
        margin_r: int = 60,   # Right safety margin
        max_line_chars: int = 18  # Max CJK characters per line before wrapping
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.shadow = shadow
        self.position = position
        self.margin_v = margin_v
        self.margin_l = margin_l
        self.margin_r = margin_r
        self.max_line_chars = max_line_chars

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
        return (
            f"FontName={self.font_name},"
            f"FontSize={self.font_size},"
            f"PrimaryColour={self.primary_color},"
            f"OutlineColour={self.outline_color},"
            f"Outline={self.outline_width},"
            f"Shadow={self.shadow},"
            f"Alignment={alignment},"
            f"MarginV={self.margin_v},"
            f"MarginL={self.margin_l},"
            f"MarginR={self.margin_r}"
        )


# CJK characters that should NOT start a new line (Hangul/Chinese punctuation rules)
NO_START_PUNCTUATIONS = set("，。？！；：、’”）》}】…~·?!,;:!\"')]>}")


def wrap_subtitle_text(text: str, max_chars: int = 18) -> str:
    """
    Intelligently wraps subtitle lines:
    - Protects URLs and English words from being broken across lines.
    - Favors punctuation break points (，。？！；：, . ! ?).
    - Enforces typography rules: never start a new line with trailing punctuations.
      Trailing punctuation clusters (e.g. ……！！！) always stick to preceding text.
    - Preserves short sentences without unnecessary line breaks.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    # If already contains manual line breaks, process line by line
    if "\n" in text:
        return "\n".join(wrap_subtitle_text(line, max_chars) for line in text.split("\n"))

    # Tokenize into chunks: URLs, English words/numbers, CJK characters, punctuations
    pattern = re.compile(
        r'(https?://\S+|www\.\S+|[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fa5]|[，。？！；：“”‘’（）《》、…~·\s]|\S)'
    )
    tokens = pattern.findall(text)

    lines = []
    current_line = []
    current_len = 0.0

    for token in tokens:
        is_cjk = bool(re.match(r'[\u4e00-\u9fa5]', token))
        t_len = 1.0 if is_cjk else max(0.55 * len(token), 0.5)

        # If adding token exceeds max_chars
        if current_len + t_len > max_chars and current_line:
            # Trailing punctuation attaches to current line regardless of length
            if token in NO_START_PUNCTUATIONS:
                current_line.append(token)
                current_len += t_len
            else:
                lines.append("".join(current_line))
                current_line = [token]
                current_len = t_len
        else:
            current_line.append(token)
            current_len += t_len

    if current_line:
        lines.append("".join(current_line))

    # Second pass: ensure NO line starts with trailing punctuation
    final_lines = []
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        if final_lines and cleaned_line[0] in NO_START_PUNCTUATIONS:
            # Shift leading punctuations to previous line
            punc_idx = 0
            while punc_idx < len(cleaned_line) and cleaned_line[punc_idx] in NO_START_PUNCTUATIONS:
                punc_idx += 1
            leading_puncs = cleaned_line[:punc_idx]
            rest = cleaned_line[punc_idx:].strip()
            final_lines[-1] += leading_puncs
            if rest:
                final_lines.append(rest)
        else:
            final_lines.append(cleaned_line)

    return "\n".join(final_lines)


def normalize_srt_to_utf8(
    srt_path: str | Path,
    temp_dir: str | Path,
    max_line_chars: int = 18
) -> str:
    """
    Reads an SRT file, auto-detects encoding (UTF-8, UTF-8-SIG, GBK, CP936),
    applies smart line wrapping, and saves a clean UTF-8 copy in temp_dir.
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

    # Process subtitle blocks
    # Standard SRT block regex: index \n timestamp --> timestamp \n text \n\n
    blocks = re.split(r'\r?\n\r?\n', content.strip())
    cleaned_blocks = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3:
            idx = lines[0]
            timestamp = lines[1]
            text = " ".join(lines[2:])
            # Wrap text intelligently
            wrapped_text = wrap_subtitle_text(text, max_chars=max_line_chars)
            cleaned_blocks.append(f"{idx}\n{timestamp}\n{wrapped_text}")
        elif len(lines) == 2 and "-->" in lines[1]:
            cleaned_blocks.append("\n".join(lines))
        elif block.strip():
            cleaned_blocks.append(block.strip())

    cleaned_content = "\n\n".join(cleaned_blocks) + "\n"

    # Ensure UTF-8 clean file
    out_dir = ensure_dir(temp_dir)
    target_path = out_dir / f"clean_{raw_path.stem}.srt"
    target_path.write_text(cleaned_content, encoding="utf-8")
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
