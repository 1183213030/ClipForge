"""
Media Probe Module for ClipForge.
Extracts duration, resolution, framerate, and stream details via ffprobe or ffmpeg.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Optional

from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path, run_command, FFmpegError
from app.utils.path_utils import normalize_path


@dataclass
class MediaMetadata:
    path: str
    duration: float  # seconds
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    has_video: bool = False
    has_audio: bool = False
    bitrate: int = 0  # bps

    @property
    def is_valid_video(self) -> bool:
        return self.has_video and self.duration > 0 and self.width > 0 and self.height > 0

    @property
    def is_valid_audio(self) -> bool:
        return self.has_audio and self.duration > 0


def probe_media(file_path: str | Path) -> MediaMetadata:
    """Probes media file using ffprobe if present, falling back to ffmpeg -i parsing."""
    norm_path = normalize_path(file_path)
    if not Path(norm_path).is_file():
        raise FFmpegError(f"媒体文件不存在: {norm_path}")

    ffprobe = get_ffprobe_path()
    if ffprobe:
        try:
            return _probe_with_ffprobe(ffprobe, norm_path)
        except Exception:
            # Fall back to ffmpeg if ffprobe fails
            pass

    return _probe_with_ffmpeg(norm_path)


def _probe_with_ffprobe(ffprobe_path: str, norm_path: str) -> MediaMetadata:
    """Probe using ffprobe json output."""
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,duration",
        "-of", "json",
        norm_path
    ]
    res = run_command(cmd, timeout_sec=15)
    data = json.loads(res.stdout)

    format_info = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(format_info.get("duration", 0.0))
    bitrate = int(format_info.get("bit_rate", 0))

    width = 0
    height = 0
    fps = 0.0
    video_codec = ""
    audio_codec = ""
    has_video = False
    has_audio = False

    for s in streams:
        c_type = s.get("codec_type")
        if c_type == "video" and not has_video:
            has_video = True
            video_codec = s.get("codec_name", "")
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            
            # Parse fps e.g. "30/1" or "30000/1001"
            r_frame_rate = s.get("r_frame_rate", "0/0")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                fps = round(float(num) / float(den), 2) if float(den) > 0 else 0.0

            # If container duration was 0, check stream duration
            if duration == 0 and "duration" in s:
                duration = float(s["duration"])

        elif c_type == "audio" and not has_audio:
            has_audio = True
            audio_codec = s.get("codec_name", "")
            if duration == 0 and "duration" in s:
                duration = float(s["duration"])

    return MediaMetadata(
        path=norm_path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video_codec,
        audio_codec=audio_codec,
        has_video=has_video,
        has_audio=has_audio,
        bitrate=bitrate
    )


def _probe_with_ffmpeg(norm_path: str) -> MediaMetadata:
    """Probe media by parsing ffmpeg -i stderr output."""
    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-i", norm_path]
    # ffmpeg -i with no output always exits with non-zero code, so we catch stderr directly
    import subprocess
    startupinfo = None
    if subprocess.os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=startupinfo,
        encoding="utf-8",
        errors="replace"
    )
    _, stderr = p.communicate(timeout=15)

    duration = 0.0
    bitrate = 0
    width = 0
    height = 0
    fps = 0.0
    video_codec = ""
    audio_codec = ""
    has_video = False
    has_audio = False

    # Extract Duration: 00:01:23.45, start: ..., bitrate: 2450 kb/s
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
    if dur_match:
        h, m, s = dur_match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    br_match = re.search(r"bitrate:\s*(\d+)\s*kb/s", stderr)
    if br_match:
        bitrate = int(br_match.group(1)) * 1000

    # Stream #0:0: Video: h264 (High), yuv420p, 1920x1080 [SAR 1:1 DAR 16:9], 30 fps...
    video_match = re.search(r"Stream.*Video:\s*([a-zA-Z0-9_\-]+).*?,\s*(\d{2,5})x(\d{2,5})", stderr)
    if video_match:
        has_video = True
        video_codec = video_match.group(1)
        width = int(video_match.group(2))
        height = int(video_match.group(3))

        fps_match = re.search(r",\s*(\d+(?:\.\d+)?)\s*fps", stderr)
        if fps_match:
            fps = float(fps_match.group(1))

    # Stream #0:1: Audio: aac (LC)...
    audio_match = re.search(r"Stream.*Audio:\s*([a-zA-Z0-9_\-]+)", stderr)
    if audio_match:
        has_audio = True
        audio_codec = audio_match.group(1)

    return MediaMetadata(
        path=norm_path,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video_codec,
        audio_codec=audio_codec,
        has_video=has_video,
        has_audio=has_audio,
        bitrate=bitrate
    )
