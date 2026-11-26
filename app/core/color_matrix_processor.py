"""
Color Matrix & Multi-Specification Batch Rendering Engine for ClipForge 3.0.
Supports 7 palette presets (original, red, yellow, purple, green, blue, black/white),
adjustable color grading strength (0-100%), landscape (1280x720) / portrait (720x1280) scaling,
custom corner badges, and dynamic anti-deduplication digital fingerprints.
Optimized for NVIDIA NVENC (GTX 1650 SUPER / Turing) hardware acceleration.
"""

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Optional

from app.core.hw_encoder import get_best_hardware_encoder, CPU_FAST_PROFILE, EncoderProfile
from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path
from app.utils.path_utils import normalize_path

logger = logging.getLogger(__name__)


# Standard Color Presets Supported by Matrix
COLOR_PRESETS = [
    ("original", "原视频", "#94a3b8"),
    ("red", "红", "#ef4444"),
    ("yellow", "黄", "#eab308"),
    ("purple", "紫", "#a855f7"),
    ("green", "绿", "#22c55e"),
    ("blue", "蓝", "#3b82f6"),
    ("black", "黑(黑白)", "#64748b"),
]


@dataclass
class ColorMatrixConfig:
    """User configuration for a matrix generation job."""
    colors: list[str] = field(default_factory=lambda: ["original", "red", "yellow", "purple", "green", "blue", "black"])
    strength: float = 0.6  # 0.0 to 1.0 (0% to 100%)
    output_landscape: bool = True   # 1280x720
    output_portrait: bool = True    # 720x1280
    output_original_size: bool = False
    enable_fingerprint: bool = True # Anti-deduplication noise + metadata purge
    add_badge: bool = True          # Watermark badge
    badge_text: str = "二创"
    landscape_badge_path: Optional[Path] = None
    portrait_badge_path: Optional[Path] = None
    copies_per_color: int = 1       # Output count per color
    output_dir: Optional[Path] = None
    max_concurrent_nvenc: int = 2   # Safe limit for GTX 1650 SUPER


@dataclass
class MatrixTaskUnit:
    """Single concrete video rendering task unit."""
    source_path: Path
    output_path: Path
    color: str            # 'original', 'red', 'yellow', 'purple', 'green', 'blue', 'black'
    strength: float       # 0.0 - 1.0
    layout: str           # 'landscape', 'portrait', 'original_size'
    add_badge: bool
    badge_text: str
    badge_image_path: Optional[Path] = None
    enable_fingerprint: bool = True
    copy_index: int = 1


def get_default_badge_path(layout: str) -> Optional[Path]:
    """Resolves default landscape or portrait watermark badge PNG."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    if layout == "portrait":
        p = base_dir / "resources" / "badges" / "default_portrait_badge.png"
    else:
        p = base_dir / "resources" / "badges" / "default_landscape_badge.png"
    return p if p.is_file() else None


def build_color_filter(color: str, strength: float) -> str:
    """
    Builds the FFmpeg video filter string for the specified color and strength.
    Uses colorbalance and hue filters for smooth cinematic color casts.
    """
    st = max(0.0, min(1.0, strength))
    if color == "original" or st <= 0.001:
        return ""

    if color == "black":
        # Desaturate down according to strength
        sat = max(0.0, 1.0 - st)
        contrast = 1.0 + (0.15 * st)
        return f"hue=s={sat:.2f},eq=contrast={contrast:.2f}:brightness=0.01"

    if color == "red":
        # Warm red cast: boost red midtones and highlights, soften blue/green
        rm = 0.45 * st
        rh = 0.35 * st
        gm = -0.15 * st
        bm = -0.20 * st
        return f"colorbalance=rm={rm:.2f}:rh={rh:.2f}:gm={gm:.2f}:bm={bm:.2f}"

    if color == "yellow":
        # Warm golden yellow: boost red and green, reduce blue
        rm = 0.38 * st
        rh = 0.25 * st
        gm = 0.35 * st
        gh = 0.22 * st
        bm = -0.45 * st
        bh = -0.35 * st
        return f"colorbalance=rm={rm:.2f}:rh={rh:.2f}:gm={gm:.2f}:gh={gh:.2f}:bm={bm:.2f}:bh={bh:.2f}"

    if color == "purple":
        # Cyberpunk purple: boost red and blue, dampen green
        rm = 0.40 * st
        rh = 0.30 * st
        bm = 0.45 * st
        bh = 0.35 * st
        gm = -0.35 * st
        gh = -0.25 * st
        return f"colorbalance=rm={rm:.2f}:rh={rh:.2f}:bm={bm:.2f}:bh={bh:.2f}:gm={gm:.2f}:gh={gh:.2f}"

    if color == "green":
        # Emerald green: boost green, suppress red and blue
        gm = 0.45 * st
        gh = 0.35 * st
        rm = -0.22 * st
        rh = -0.15 * st
        bm = -0.25 * st
        bh = -0.18 * st
        return f"colorbalance=gm={gm:.2f}:gh={gh:.2f}:rm={rm:.2f}:rh={rh:.2f}:bm={bm:.2f}:bh={bh:.2f}"

    if color == "blue":
        # Cinematic cold blue: boost blue, suppress red
        bm = 0.50 * st
        bh = 0.38 * st
        rm = -0.25 * st
        rh = -0.18 * st
        gm = -0.10 * st
        return f"colorbalance=bm={bm:.2f}:bh={bh:.2f}:rm={rm:.2f}:rh={rh:.2f}:gm={gm:.2f}"

    return ""


def build_layout_filter(layout: str) -> str:
    """
    Builds FFmpeg filter for output resolution layout.
    - landscape: 1280x720 with aspect-ratio preserving pad
    - portrait: 720x1280 (9:16) with smart center crop or blurred background
    - original_size: keep source resolution
    """
    if layout == "landscape":
        return "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
    elif layout == "portrait":
        # High quality 9:16 portrait: center-fit crop then scale
        return "crop=min(iw\\,ih*9/16):min(ih\\,iw*16/9),scale=720:1280"
    return ""


def build_badge_filter(badge_text: str = "二创") -> str:
    """
    Builds a stylish corner badge overlay using FFmpeg drawtext or geometric box.
    """
    clean_text = badge_text.strip().replace(":", "\\:").replace("'", "\\'")
    if not clean_text:
        return ""
    # Render modern semi-transparent pill badge in top-right corner
    return (
        f"drawtext=text='{clean_text}':fontcolor=white@0.9:fontsize=22:"
        f"x=w-tw-24:y=24:box=1:boxcolor=black@0.55:boxborderw=8"
    )


def build_fingerprint_filter() -> str:
    """
    Anti-deduplication filter: injects imperceptible micro-noise and slight contrast jitter
    to guarantee a unique digital fingerprint while preserving pristine visual quality.
    """
    return "noise=c0s=1:c0f=t:all_flags=t"


def assemble_filter_chain(task: MatrixTaskUnit) -> str:
    """Combines all filters into a unified FFmpeg video filter chain."""
    filters = []

    # 1. Color grading
    color_filt = build_color_filter(task.color, task.strength)
    if color_filt:
        filters.append(color_filt)

    # 2. Digital fingerprint (if enabled)
    if task.enable_fingerprint:
        filters.append(build_fingerprint_filter())

    # 3. Layout geometry
    layout_filt = build_layout_filter(task.layout)
    if layout_filt:
        filters.append(layout_filt)

    # 4. Corner badge
    if task.add_badge and task.badge_text:
        badge_filt = build_badge_filter(task.badge_text)
        if badge_filt:
            filters.append(badge_filt)

    # Standardize pixel format for H.264 compatibility
    filters.append("format=yuv420p")
    return ",".join(filters)


class ColorMatrixProcessor:
    """
    Executes a single matrix task unit using FFmpeg with GPU acceleration detection.
    """
    def __init__(self, encoder_profile: Optional[EncoderProfile] = None):
        self.ffmpeg_path = get_ffmpeg_path()
        self.ffprobe_path = get_ffprobe_path()
        if encoder_profile is not None:
            self.encoder_profile = encoder_profile
        else:
            self.encoder_profile = get_best_hardware_encoder(self.ffmpeg_path) or CPU_FAST_PROFILE

    def render_unit(
        self,
        task: MatrixTaskUnit,
        progress_callback: Optional[Callable[[float], None]] = None,
        duration_sec: Optional[float] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> bool:
        """
        Renders a single MatrixTaskUnit to its destination file.
        Returns True on success, False otherwise.
        """
        task.output_path.parent.mkdir(parents=True, exist_ok=True)

        has_badge_img = bool(
            task.add_badge
            and task.badge_image_path
            and Path(task.badge_image_path).is_file()
        )

        if has_badge_img:
            # Multi-input filter_complex: Input 0 = Video, Input 1 = Watermark PNG (RGBA)
            base_filters = []
            color_f = build_color_filter(task.color, task.strength)
            if color_f:
                base_filters.append(color_f)
            if task.enable_fingerprint:
                base_filters.append(build_fingerprint_filter())
            layout_f = build_layout_filter(task.layout)
            if layout_f:
                base_filters.append(layout_f)

            base_chain = ",".join(base_filters) if base_filters else "null"

            if task.layout == "portrait":
                target_w, target_h = 720, 1280
            elif task.layout == "landscape":
                target_w, target_h = 1280, 720
            else:
                target_w, target_h = None, None

            if target_w and target_h:
                filter_complex = (
                    f"[0:v]{base_chain}[v_base];"
                    f"[1:v]scale={target_w}:{target_h}[b_scaled];"
                    f"[v_base][b_scaled]overlay=0:0,format=yuv420p[outv]"
                )
            else:
                filter_complex = (
                    f"[0:v]{base_chain}[v_base];"
                    f"[1:v]scale=w=main_w:h=main_h[b_scaled];"
                    f"[v_base][b_scaled]overlay=0:0,format=yuv420p[outv]"
                )

            cmd = [
                self.ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-stats",
                "-i", str(task.source_path),
                "-i", str(task.badge_image_path),
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-map", "0:a?",
                "-c:v", self.encoder_profile.codec,
            ]
        else:
            # Single-input filter chain (text badge or no badge)
            vf_chain = assemble_filter_chain(task)
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-stats",
                "-i", str(task.source_path),
                "-vf", vf_chain,
                "-c:v", self.encoder_profile.codec,
            ]

        # Add hardware or CPU encoder optimization arguments
        cmd.extend(self.encoder_profile.extra_args)

        # Audio stream copy for maximum speed and 0 loss
        cmd.extend(["-c:a", "copy"])

        # Strip metadata for clean fingerprint
        if task.enable_fingerprint:
            cmd.extend(["-map_metadata", "-1"])

        cmd.append(str(task.output_path))

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        logger.info(f"Rendering {task.output_path.name} with {self.encoder_profile.display_name}")
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
            )

            # Monitor progress
            time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            while True:
                if cancel_check and cancel_check():
                    process.kill()
                    if task.output_path.exists():
                        try:
                            task.output_path.unlink()
                        except Exception:
                            pass
                    return False

                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break

                if duration_sec and duration_sec > 0 and progress_callback:
                    match = time_regex.search(line)
                    if match:
                        hours, mins, secs = match.groups()
                        cur_sec = int(hours) * 3600 + int(mins) * 60 + float(secs)
                        progress = min(0.99, cur_sec / duration_sec)
                        progress_callback(progress)

            ret = process.wait()
            if ret == 0:
                if progress_callback:
                    progress_callback(1.0)
                return True
            else:
                err_msg = process.stderr.read()
                logger.error(f"FFmpeg render error: {err_msg}")
                # Fallback to CPU if hardware encoder failed
                if self.encoder_profile.is_hardware:
                    logger.warning("Hardware encoding failed. Falling back to CPU veryfast...")
                    self.encoder_profile = CPU_FAST_PROFILE
                    return self.render_unit(task, progress_callback, duration_sec, cancel_check)
                return False

        except Exception as e:
            logger.error(f"Failed to execute FFmpeg for task {task.output_path.name}: {e}")
            return False
