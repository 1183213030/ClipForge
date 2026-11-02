"""
Video Processor Engine for ClipForge.
Responsible for video standardization (1080x1920, 30fps), video segment concatenation,
audio stream replacement, subtitle hard-coding, bitrate control, and export.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable, Optional

from app.core.media_probe import probe_media, MediaMetadata
from app.core.subtitle_processor import SubtitleConfig, normalize_srt_to_utf8, build_subtitles_filter
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command, FFmpegError
from app.utils.path_utils import normalize_path, ensure_dir


@dataclass
class VideoSegment:
    file_path: str
    start_time: float
    duration: float


@dataclass
class ExportOptions:
    output_width: int = 1080
    output_height: int = 1920
    fps: int = 30
    video_bitrate: str = "6M"   # e.g. "2M", "4M", "6M", "8M", "10M"
    audio_bitrate: str = "128k"
    audio_samplerate: int = 44100
    preset: str = "fast"
    subtitle_config: Optional[SubtitleConfig] = None


class VideoProcessor:
    def __init__(self, temp_dir: str | Path = "temp"):
        self.temp_dir = ensure_dir(temp_dir)
        self.ffmpeg_path = get_ffmpeg_path()

    def render_mixed_video(
        self,
        segments: list[VideoSegment],
        audio_path: str | Path,
        srt_path: Optional[str | Path],
        output_path: str | Path,
        options: Optional[ExportOptions] = None,
        on_progress: Optional[Callable[[float], None]] = None
    ) -> str:
        """
        Renders the final MP4 video using the Direct FilterGraph pipeline.
        - Scales & crops all segments into 1080x1920 @ 30 FPS.
        - Concatenates video frames without original sound.
        - Replaces audio entirely with novel audio track.
        - Subtitle burning with custom alignment & font.
        - Output duration strictly aligned to audio duration.
        """
        if not segments:
            raise ValueError("渲染片段列表不能为空。")

        opts = options or ExportOptions()
        norm_output = normalize_path(output_path)
        ensure_dir(Path(norm_output).parent)

        # 1. Probe novel audio to obtain exact duration
        norm_audio = normalize_path(audio_path)
        audio_meta = probe_media(norm_audio)
        if not audio_meta.is_valid_audio:
            raise ValueError(f"小说音频无效或无法读取: {norm_audio}")
        target_duration = audio_meta.duration

        # 2. Normalize and prepare SRT if supplied
        subtitles_filter_str = ""
        if srt_path:
            norm_srt = normalize_path(srt_path)
            clean_srt = normalize_srt_to_utf8(norm_srt, self.temp_dir)
            sub_cfg = opts.subtitle_config or SubtitleConfig()
            subtitles_filter_str = build_subtitles_filter(clean_srt, sub_cfg)

        # 3. Construct FFmpeg command
        cmd = [self.ffmpeg_path, "-y"]

        # Add segment inputs
        for seg in segments:
            cmd.extend([
                "-ss", f"{seg.start_time:.3f}",
                "-t", f"{seg.duration:.3f}",
                "-i", normalize_path(seg.file_path)
            ])

        # Add novel audio input as the last input
        audio_input_idx = len(segments)
        cmd.extend(["-i", norm_audio])

        # 4. Build FilterGraph
        filter_parts = []
        concat_inputs = []
        for i in range(len(segments)):
            # Force 1080x1920 crop, 1:1 SAR, 30 FPS
            filter_parts.append(
                f"[{i}:v]scale={opts.output_width}:{opts.output_height}:force_original_aspect_ratio=increase,"
                f"crop={opts.output_width}:{opts.output_height},setsar=1,fps={opts.fps}[v{i}]"
            )
            concat_inputs.append(f"[v{i}]")

        # Concat video streams (video only, audio completely discarded)
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=0[rawv]")

        # Apply subtitles filter if available
        if subtitles_filter_str:
            filter_parts.append(f"[rawv]{subtitles_filter_str}[outv]")
            video_map_label = "[outv]"
        else:
            video_map_label = "[rawv]"

        filter_complex_str = ";".join(filter_parts)

        cmd.extend([
            "-filter_complex", filter_complex_str,
            "-map", video_map_label,
            "-map", f"{audio_input_idx}:a",
            "-c:v", "libx264",
            "-b:v", opts.video_bitrate,
            "-pix_fmt", "yuv420p",
            "-preset", opts.preset,
            "-c:a", "aac",
            "-b:a", opts.audio_bitrate,
            "-ar", str(opts.audio_samplerate),
            "-t", f"{target_duration:.3f}",  # Strictly clamp output to audio duration
            norm_output
        ])

        # 5. Execute with live progress parsing
        startupinfo = None
        if subprocess.os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            encoding="utf-8",
            errors="replace"
        )

        stderr_collector = []
        time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")

        assert process.stderr is not None
        for line in process.stderr:
            stderr_collector.append(line)
            if on_progress and target_duration > 0:
                match = time_regex.search(line)
                if match:
                    h, m, s = match.groups()
                    current_sec = int(h) * 3600 + int(m) * 60 + float(s)
                    ratio = min(max(current_sec / target_duration, 0.0), 1.0)
                    on_progress(ratio)

        process.wait()
        ret_code = process.poll()
        if ret_code != 0:
            err_msg = "".join(stderr_collector[-30:])
            raise FFmpegError(f"视频混剪渲染失败 (Exit code {ret_code}):\n{err_msg}")

        if on_progress:
            on_progress(1.0)

        return norm_output
