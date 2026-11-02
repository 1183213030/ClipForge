"""
Path and String Utility Module for ClipForge.
Handles Windows path conversions, FFmpeg filter escaping, and directory checks.
"""

from pathlib import Path
import re


def normalize_path(path_str: str | Path) -> str:
    """Convert path to normalized string with forward slashes."""
    return str(Path(path_str).resolve()).replace("\\", "/")


def escape_ffmpeg_filter_path(path_str: str | Path) -> str:
    r"""
    Escape file path specifically for FFmpeg filter arguments (such as subtitles filter).
    In FFmpeg filtergraph:
    - Backslashes must be avoided or escaped.
    - Drive colon 'C:' must be escaped as 'C\:'
    - Single quotes must be escaped or avoided.
    """
    p = str(Path(path_str).resolve()).replace("\\", "/")
    # Escape drive colon if present (e.g. D:/ -> D\:/)
    # Match Windows drive letter at start of string
    if re.match(r"^[a-zA-Z]:", p):
        drive = p[0]
        rest = p[2:]
        p = f"{drive}\\:{rest}"
    # Escape single quotes and brackets if present
    p = p.replace("'", r"\'").replace("[", r"\[").replace("]", r"\]")
    return p


def ensure_dir(dir_path: str | Path) -> Path:
    """Ensure directory exists and return Path object."""
    p = Path(dir_path)
    p.mkdir(parents=True, exist_ok=True)
    return p
