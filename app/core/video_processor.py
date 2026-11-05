"""
Video Processor Engine for ClipForge.
Responsible for video standardization (1080x1920, 30fps), video segment concatenation,
audio stream replacement, subtitle hard-coding, bitrate control, and export.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import subprocess
from typing import Callable, Optional
import uuid

logger = logging.getLogger(__name__)


from app.core.media_probe import probe_media, MediaMetadata
from app.core.subtitle_processor import SubtitleConfig, normalize_srt_to_utf8, build_subtitles_filter
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command, FFmpegError
from app.utils.path_utils import normalize_path, ensure_dir


class TaskCancelledError(Exception):
    """Raised when a rendering task is explicitly cancelled by user."""
    pass


class CancellationToken:
    def __init__(self):
        self._cancelled = False
        self._current_process: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancelled = True
        if self._current_process:
            try:
                self._current_process.kill()
            except Exception:
                pass

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def bind_process(self, process: subprocess.Popen):
        self._current_process = process
        if self._cancelled:
            try:
                process.kill()
            except Exception:
                pass


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
    video_bitrate: str = "4M"   # e.g. "2M", "4M", "6M", "8M", "10M"
    audio_bitrate: str = "128k"
    audio_samplerate: int = 44100
    preset: str = "fast"
    subtitle_config: Optional[SubtitleConfig] = None
    template_png_path: Optional[str] = None  # Transparent overlay template
    enable_template: bool = True


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
        on_progress: Optional[Callable[[float], None]] = None,
        token: Optional[CancellationToken] = None
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

        # Calculate exact required video frames based on audio duration and target FPS
        import math
        target_frames = math.ceil(target_duration * opts.fps)

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

        # Add novel audio input
        audio_input_idx = len(segments)
        cmd.extend(["-i", norm_audio])

        # Optional: Add transparent template PNG input
        template_input_idx = None
        if opts.enable_template and opts.template_png_path and Path(opts.template_png_path).is_file():
            template_input_idx = len(segments) + 1
            cmd.extend(["-i", normalize_path(opts.template_png_path)])

        # 4. Build FilterGraph with frame synchronization & layer ordering
        filter_parts = []
        concat_inputs = []
        for i in range(len(segments)):
            # Force 1080x1920 crop, 1:1 SAR, monotonic 30 FPS with near rounding
            filter_parts.append(
                f"[{i}:v]scale={opts.output_width}:{opts.output_height}:force_original_aspect_ratio=increase,"
                f"crop={opts.output_width}:{opts.output_height},setsar=1,"
                f"fps=fps={opts.fps}:round=near:start_time=0[v{i}]"
            )
            concat_inputs.append(f"[v{i}]")

        # Concat video streams (video only, audio completely discarded)
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=0[raw_concat]")

        # Frame alignment & safety buffer (pad with clone until exact target_frames trim is reached)
        filter_parts.append(
            f"[raw_concat]tpad=stop_mode=clone:stop=-1,trim=start_frame=0:end_frame={target_frames},"
            f"setpts=PTS-STARTPTS[bg_video]"
        )
        current_v_label = "[bg_video]"

        # Layer 1: Overlay transparent template PNG if provided (below subtitles)
        if template_input_idx is not None:
            filter_parts.append(
                f"[{template_input_idx}:v]scale={opts.output_width}:{opts.output_height}[tpl_scaled]"
            )
            filter_parts.append(
                f"{current_v_label}[tpl_scaled]overlay=0:0[with_template]"
            )
            current_v_label = "[with_template]"

        # Layer 2: Hard-code subtitles on top of everything
        if subtitles_filter_str:
            filter_parts.append(f"{current_v_label}{subtitles_filter_str}[outv]")
            video_map_label = "[outv]"
        else:
            video_map_label = current_v_label

        filter_complex_str = ";\n".join(filter_parts)

        # Write filter complex into an isolated temp script file to eliminate Windows CLI length limits
        filter_script_path = self.temp_dir / f"filter_script_{uuid.uuid4().hex[:8]}.txt"
        try:
            filter_script_path.write_text(filter_complex_str, encoding="utf-8")
        except Exception as e:
            raise FFmpegError(f"写入 FFmpeg 滤镜脚本失败: {e}")

        cmd.extend([
            "-filter_complex_script", str(filter_script_path.resolve()),
            "-map", video_map_label,
            "-map", f"{audio_input_idx}:a",
            "-c:v", "libx264",
            "-r", str(opts.fps),
            "-video_track_timescale", str(opts.fps * 1000),
            "-b:v", opts.video_bitrate,
            "-pix_fmt", "yuv420p",
            "-preset", opts.preset,
            "-frames:v", str(target_frames),
            "-c:a", "aac",
            "-b:a", opts.audio_bitrate,
            "-ar", str(opts.audio_samplerate),
            "-t", f"{target_duration:.3f}",
            norm_output
        ])

        # Validate command line length against Windows OS CreateProcess physical limit (32,767 chars)
        cmd_str = subprocess.list2cmdline(cmd)
        cmd_length = len(cmd_str)
        logger.info(f"FFmpeg 命令行总字符长度: {cmd_length} (Windows 安全水位: 32,000 / 物理上限: 32,767)")
        if subprocess.os.name == "nt" and cmd_length > 32000:
            raise FFmpegError(
                f"生成的 FFmpeg 命令行参数过长 ({cmd_length} 字符)，超出 Windows 安全水位限制 (32,000 字符)。\n"
                f"请减少素材分段数量或缩短素材文件夹路径以避免 CreateProcess 失败。"
            )

        # 5. Execute with live progress parsing
        startupinfo = None
        if subprocess.os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                encoding="utf-8",
                errors="replace"
            )

            if token:
                token.bind_process(process)

            stderr_collector = []
            time_regex = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")

            assert process.stderr is not None
            for line in process.stderr:
                stderr_collector.append(line)
                if token and token.is_cancelled:
                    process.kill()
                    raise TaskCancelledError("任务已被用户取消。")

                if on_progress and target_duration > 0:
                    match = time_regex.search(line)
                    if match:
                        h, m, s = match.groups()
                        current_sec = int(h) * 3600 + int(m) * 60 + float(s)
                        ratio = min(max(current_sec / target_duration, 0.0), 1.0)
                        on_progress(ratio)

            process.wait()
            if token and token.is_cancelled:
                raise TaskCancelledError("任务已被用户取消。")

            ret_code = process.poll()
            if ret_code != 0:
                err_msg = "".join(stderr_collector[-30:])
                raise FFmpegError(f"视频混剪渲染失败 (Exit code {ret_code}):\n{err_msg}")

            if on_progress:
                on_progress(1.0)

            return norm_output
        finally:
            if filter_script_path.exists():
                try:
                    filter_script_path.unlink()
                except Exception as ex:
                    logger.warning(f"清理临时滤镜脚本文件失败: {filter_script_path} ({ex})")

