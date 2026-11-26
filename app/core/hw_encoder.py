"""
Hardware Video Encoder Detection & Selection Module for ClipForge.
Automatically probes available GPU/hardware H.264 encoders (NVENC, QSV, AMF, MediaFoundation)
with real 1-frame smoke tests, caches detection results, and provides safe fallback to libx264.
"""

from dataclasses import dataclass
import logging
import os
import subprocess
import threading
from typing import Optional

from app.utils.ffmpeg_utils import get_ffmpeg_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EncoderProfile:
    """Describes a concrete H.264 video encoder configuration."""
    codec: str                # e.g. "h264_nvenc", "h264_qsv", "h264_amf", "h264_mf", "libx264"
    display_name: str         # Human-readable label for UI
    is_hardware: bool
    extra_args: tuple[str, ...] = ()


# Priority order: dedicated GPU first, then integrated GPU, then OS MediaFoundation, finally CPU
_HW_CANDIDATES: list[EncoderProfile] = [
    EncoderProfile(
        codec="h264_nvenc",
        display_name="NVIDIA NVENC 硬件加速",
        is_hardware=True,
        extra_args=("-preset", "p4", "-rc", "vbr"),
    ),
    EncoderProfile(
        codec="h264_qsv",
        display_name="Intel QSV 硬件加速",
        is_hardware=True,
        extra_args=("-preset", "veryfast"),
    ),
    EncoderProfile(
        codec="h264_amf",
        display_name="AMD AMF 硬件加速",
        is_hardware=True,
        extra_args=("-quality", "speed"),
    ),
    EncoderProfile(
        codec="h264_mf",
        display_name="Windows MediaFoundation 硬件加速",
        is_hardware=True,
        extra_args=("-rate_control", "cbr"),
    ),
]

CPU_FAST_PROFILE = EncoderProfile(
    codec="libx264",
    display_name="CPU 极速软编 (veryfast)",
    is_hardware=False,
    extra_args=("-preset", "veryfast"),
)

CPU_QUALITY_PROFILE = EncoderProfile(
    codec="libx264",
    display_name="CPU 标准软编 (fast)",
    is_hardware=False,
    extra_args=("-preset", "fast"),
)

_detect_lock = threading.Lock()
_cached_best_hw: dict[str, Optional[EncoderProfile]] = {}
_cached_available_encoders: dict[str, set[str]] = {}


def _get_ffmpeg_listed_encoders(ffmpeg_path: str) -> set[str]:
    """Queries `ffmpeg -encoders` once and caches the set of compiled H.264 encoders."""
    if ffmpeg_path in _cached_available_encoders:
        return _cached_available_encoders[ffmpeg_path]

    found: set[str] = set()
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        res = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=10,
        )
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "264" in parts[1]:
                found.add(parts[1])
    except Exception as exc:
        logger.warning(f"查询 FFmpeg 支持的编码器列表失败: {exc}")

    _cached_available_encoders[ffmpeg_path] = found
    return found


def _smoke_test_encoder(ffmpeg_path: str, profile: EncoderProfile) -> bool:
    """
    Runs a tiny real 1-frame encode to verify that the hardware driver & device
    actually work on this machine (listing in `-encoders` alone is not sufficient).
    """
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=0.1",
        "-frames:v", "2",
        "-pix_fmt", "yuv420p",
        "-c:v", profile.codec,
        *profile.extra_args,
        "-b:v", "1M",
        "-f", "null", "-",
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=8,
        )
        return res.returncode == 0
    except Exception:
        return False


def detect_best_hw_encoder(ffmpeg_path: Optional[str] = None) -> Optional[EncoderProfile]:
    """
    Detects and caches the highest-priority working hardware H.264 encoder on this machine.
    Returns None if no hardware encoder passes the smoke test.
    """
    ff = ffmpeg_path or get_ffmpeg_path()
    with _detect_lock:
        if ff in _cached_best_hw:
            return _cached_best_hw[ff]

        listed = _get_ffmpeg_listed_encoders(ff)
        best: Optional[EncoderProfile] = None

        for candidate in _HW_CANDIDATES:
            if listed and candidate.codec not in listed:
                continue
            if _smoke_test_encoder(ff, candidate):
                best = candidate
                logger.info(f"检测到可用硬件视频编码器: {candidate.display_name} ({candidate.codec})")
                break

        if best is None:
            logger.info("未检测到可用的 GPU 硬件 H.264 编码器，将自动使用 CPU 极速软编 (libx264)。")

        _cached_best_hw[ff] = best
        return best


# Convenient alias
get_best_hardware_encoder = detect_best_hw_encoder


def resolve_encoder_profile(
    encode_mode: str = "auto",
    preset: str = "veryfast",
    ffmpeg_path: Optional[str] = None,
) -> EncoderProfile:
    """
    Resolves the concrete EncoderProfile based on user's encode_mode:
    - "auto" / "hw": Use best detected hardware encoder; fall back to CPU veryfast if unavailable.
    - "cpu_fast": Force libx264 veryfast.
    - "cpu_quality": Force libx264 fast (or user-specified preset).
    """
    mode = (encode_mode or "auto").lower()
    if mode in ("auto", "hw"):
        hw = detect_best_hw_encoder(ffmpeg_path)
        if hw is not None:
            return hw
        return EncoderProfile(
            codec="libx264",
            display_name=f"CPU 软编 ({preset})",
            is_hardware=False,
            extra_args=("-preset", preset or "veryfast"),
        )

    if mode == "cpu_quality":
        eff_preset = preset if preset in ("medium", "slow", "fast") else "fast"
        return EncoderProfile(
            codec="libx264",
            display_name=f"CPU 标准软编 ({eff_preset})",
            is_hardware=False,
            extra_args=("-preset", eff_preset),
        )

    # "cpu_fast" or any other CPU fallback
    eff_preset = preset if preset in ("ultrafast", "superfast", "veryfast", "faster") else "veryfast"
    return EncoderProfile(
        codec="libx264",
        display_name=f"CPU 极速软编 ({eff_preset})",
        is_hardware=False,
        extra_args=("-preset", eff_preset),
    )


def build_video_encode_args(
    profile: EncoderProfile,
    video_bitrate: str,
    max_threads: Optional[int] = None,
) -> list[str]:
    """
    Builds FFmpeg video encoder CLI arguments for the selected EncoderProfile.
    """
    args = [
        "-c:v", profile.codec,
        *profile.extra_args,
        "-b:v", video_bitrate,
    ]
    if not profile.is_hardware and max_threads and max_threads > 0:
        args.extend(["-threads", str(max_threads)])
    return args


def get_recommended_worker_count(ffmpeg_path: Optional[str] = None) -> int:
    """
    Returns a smart default parallel worker count balancing throughput and system responsiveness.
    """
    cpu = os.cpu_count() or 4
    hw = detect_best_hw_encoder(ffmpeg_path)
    if hw is not None:
        # Hardware encoders handle 2-3 streams smoothly with low CPU pressure
        return 3 if cpu >= 8 else 2
    # Pure CPU mode
    if cpu >= 12:
        return 3
    if cpu >= 6:
        return 2
    return 1
