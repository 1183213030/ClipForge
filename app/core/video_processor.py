"""
Video Processor Engine for ClipForge.
Responsible for video standardization (1080x1920, 30fps), video segment concatenation,
audio stream replacement, subtitle hard-coding, bitrate control, hardware-accelerated encoding,
and pre-standardized clip caching for high-throughput batch export.
"""

from dataclasses import dataclass
import logging
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Optional
import uuid

logger = logging.getLogger(__name__)

from app.core.clip_cache import ClipStandardizationCache
from app.core.hw_encoder import (
    EncoderProfile,
    CPU_FAST_PROFILE,
    resolve_encoder_profile,
    build_video_encode_args,
)
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
    preset: str = "veryfast"
    subtitle_config: Optional[SubtitleConfig] = None
    template_png_path: Optional[str] = None  # Transparent overlay template
    enable_template: bool = True
    fonts_dir: Optional[str] = None
    encode_mode: str = "auto"   # "auto" | "hw" | "cpu_fast" | "cpu_quality"
    use_clip_cache: bool = True
    max_threads: Optional[int] = None
    prepared_audio_path: Optional[str] = None
    audio_duration_hint: Optional[float] = None


def _escape_concat_path(path_str: str) -> str:
    """Escapes a file path for FFmpeg concat demuxer `file '...'` directives."""
    return path_str.replace("\\", "/").replace("'", "'\\''")


class VideoProcessor:
    def __init__(
        self,
        temp_dir: str | Path = "temp",
        clip_cache: Optional[ClipStandardizationCache] = None,
    ):
        self.temp_dir = ensure_dir(temp_dir)
        self.ffmpeg_path = get_ffmpeg_path()
        self.clip_cache = clip_cache or ClipStandardizationCache(
            cache_dir=self.temp_dir / "clip_cache",
            ffmpeg_path=self.ffmpeg_path,
        )

    def _should_use_clip_cache(
        self,
        segments: list[VideoSegment],
        opts: ExportOptions,
    ) -> bool:
        """
        Determines whether pre-standardized clip caching pays off for this render call.
        Returns True when:
        - Any clip is already cached (instant cache hit from batch prewarm or prior run), OR
        - Clips are reused within this video (multi-round looping), OR
        - Many segments (>= 4) are stitched, OR
        - Any source clip exceeds target resolution (e.g. 4K) or has higher framerate (e.g. 60fps).
        """
        if not opts.use_clip_cache or not self.clip_cache:
            return False

        unique_paths = list(dict.fromkeys(normalize_path(s.file_path) for s in segments))
        if len(segments) > len(unique_paths) or len(segments) >= 4:
            return True

        for p in unique_paths:
            if self.clip_cache.get_cached_clip_path(p, opts.output_width, opts.output_height, opts.fps):
                return True

        # Check if any source clip is high-res (e.g. >1080p) or high-fps (>target fps)
        for p in unique_paths:
            try:
                w, h, src_fps, _ = self.clip_cache.get_source_info(p)
                if (w * h) > (opts.output_width * opts.output_height * 1.2) or src_fps > opts.fps + 5:
                    return True
            except Exception:
                continue

        return False

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
        Renders the final MP4 video using the optimal pipeline:
        - Fast Path A: Pre-standardized Clip Cache + FFmpeg Concat Demuxer (single input, zero redundant 4K scale/crop).
        - Fast Path B: Pre-standardized Clip Cache + Lightweight FilterGraph (when non-zero segment start_time exists).
        - Direct Path C: Optimized Direct FilterGraph (bilinear scaling, smart fps/scale ordering, -an/-sn/-dn).
        Uses hardware H.264 acceleration (NVENC/QSV/AMF/MF) when available with automatic CPU fallback.
        """
        if not segments:
            raise ValueError("渲染片段列表不能为空。")

        opts = options or ExportOptions()
        norm_output = normalize_path(output_path)
        ensure_dir(Path(norm_output).parent)

        # Validate segment source files upfront for immediate, clear error reporting
        for seg in segments:
            norm_seg = normalize_path(seg.file_path)
            if not Path(norm_seg).is_file():
                raise FFmpegError(f"视频片段素材文件不存在: {norm_seg}")

        # 1. Obtain exact target duration from novel audio
        norm_audio = normalize_path(audio_path)
        if opts.audio_duration_hint and opts.audio_duration_hint > 0:
            target_duration = opts.audio_duration_hint
        else:
            audio_meta = probe_media(norm_audio)
            if not audio_meta.is_valid_audio:
                raise ValueError(f"小说音频无效或无法读取: {norm_audio}")
            target_duration = audio_meta.duration

        target_frames = math.ceil(target_duration * opts.fps)

        # 2. Check if pre-transcoded AAC audio is provided (allows zero-cost -c:a copy)
        use_audio_copy = False
        effective_audio_path = norm_audio
        if opts.prepared_audio_path and Path(opts.prepared_audio_path).is_file():
            effective_audio_path = normalize_path(opts.prepared_audio_path)
            use_audio_copy = True

        # 3. Prepare subtitles (clean UTF-8 SRT)
        clean_srt_file: Optional[Path] = None
        subtitles_filter_str = ""
        if srt_path:
            norm_srt = normalize_path(srt_path)
            clean_srt = normalize_srt_to_utf8(norm_srt, self.temp_dir)
            clean_srt_file = Path(clean_srt)
            sub_cfg = opts.subtitle_config or SubtitleConfig()
            effective_fonts_dir = opts.fonts_dir or sub_cfg.fonts_dir
            subtitles_filter_str = build_subtitles_filter(clean_srt, sub_cfg, fonts_dir=effective_fonts_dir)

        # 4. Prepare template PNG (pre-scaled once via Pillow to eliminate per-frame FFmpeg scale)
        effective_template_path: Optional[str] = None
        template_needs_scale = False
        if opts.enable_template and opts.template_png_path and Path(opts.template_png_path).is_file():
            prepared_tpl = self.clip_cache.prepare_template_png(
                opts.template_png_path, opts.output_width, opts.output_height
            )
            effective_template_path = normalize_path(prepared_tpl)
            # If prepare_template_png fell back to original file, double check size
            if effective_template_path == normalize_path(opts.template_png_path):
                try:
                    from PIL import Image
                    with Image.open(effective_template_path) as im:
                        template_needs_scale = (im.size != (opts.output_width, opts.output_height))
                except Exception:
                    template_needs_scale = True

        # 5. Decide pipeline & resolve cached clips if applicable
        use_cache = self._should_use_clip_cache(segments, opts)
        cached_clip_map: dict[str, Path] = {}
        cached_dur_map: dict[str, float] = {}

        if use_cache:
            unique_paths = list(dict.fromkeys(normalize_path(s.file_path) for s in segments))
            for src_p in unique_paths:
                if token and token.is_cancelled:
                    raise TaskCancelledError("任务已被用户取消。")
                cached_p = self.clip_cache.get_or_create_clip(
                    src_p,
                    width=opts.output_width,
                    height=opts.output_height,
                    fps=opts.fps,
                    threads=opts.max_threads,
                    token=token,
                )
                cached_clip_map[src_p] = cached_p
                try:
                    _, _, _, dur = self.clip_cache.get_source_info(src_p)
                    cached_dur_map[src_p] = dur
                except Exception:
                    cached_dur_map[src_p] = 0.0

        all_zero_start = all(seg.start_time <= 0.001 for seg in segments)
        use_concat_demuxer = use_cache and all_zero_start and bool(cached_clip_map)

        # 6. Build FFmpeg inputs & FilterGraph
        filter_script_path = self.temp_dir / f"filter_script_{uuid.uuid4().hex[:8]}.txt"
        concat_list_path: Optional[Path] = None

        try:
            input_args: list[str] = []
            filter_parts: list[str] = []

            if use_concat_demuxer:
                # === FAST PATH A: Single Concat Demuxer Input over Pre-Standardized Clips ===
                concat_list_path = self.temp_dir / f"concat_list_{uuid.uuid4().hex[:8]}.txt"
                concat_lines: list[str] = []
                for seg in segments:
                    src_norm = normalize_path(seg.file_path)
                    c_path = str(cached_clip_map[src_norm].resolve())
                    concat_lines.append(f"file '{_escape_concat_path(c_path)}'")
                    src_dur = cached_dur_map.get(src_norm, 0.0)
                    # Only emit outpoint when truncating shorter than full clip duration
                    if seg.duration > 0 and (src_dur <= 0 or seg.duration < src_dur - 0.05):
                        concat_lines.append(f"outpoint {seg.duration:.3f}")

                concat_list_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

                input_args.extend([
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list_path.resolve()),
                ])
                audio_input_idx = 1
                input_args.extend(["-i", effective_audio_path])

                template_input_idx = None
                if effective_template_path:
                    template_input_idx = 2
                    input_args.extend(["-i", effective_template_path])

                # Enforce strict CFR fps & exact target frame count
                filter_parts.append(
                    f"[0:v]fps=fps={opts.fps}:round=near:start_time=0,"
                    f"tpad=stop_mode=clone:stop=-1,trim=start_frame=0:end_frame={target_frames},"
                    f"setpts=PTS-STARTPTS[bg_video]"
                )
                current_v_label = "[bg_video]"

            elif use_cache and cached_clip_map:
                # === FAST PATH B: Pre-Standardized Clips with Non-Zero start_time ===
                concat_inputs = []
                for i, seg in enumerate(segments):
                    src_norm = normalize_path(seg.file_path)
                    c_path = normalize_path(cached_clip_map[src_norm])
                    input_args.extend([
                        "-an", "-sn", "-dn",
                        "-ss", f"{seg.start_time:.3f}",
                        "-t", f"{seg.duration:.3f}",
                        "-i", c_path,
                    ])
                    filter_parts.append(
                        f"[{i}:v]fps=fps={opts.fps}:round=near:start_time=0[v{i}]"
                    )
                    concat_inputs.append(f"[v{i}]")

                audio_input_idx = len(segments)
                input_args.extend(["-i", effective_audio_path])

                template_input_idx = None
                if effective_template_path:
                    template_input_idx = len(segments) + 1
                    input_args.extend(["-i", effective_template_path])

                filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=0[raw_concat]")
                filter_parts.append(
                    f"[raw_concat]tpad=stop_mode=clone:stop=-1,trim=start_frame=0:end_frame={target_frames},"
                    f"setpts=PTS-STARTPTS[bg_video]"
                )
                current_v_label = "[bg_video]"

            else:
                # === DIRECT PATH C: Optimized Direct FilterGraph ===
                concat_inputs = []
                for i, seg in enumerate(segments):
                    src_norm = normalize_path(seg.file_path)
                    input_args.extend([
                        "-an", "-sn", "-dn",
                        "-ss", f"{seg.start_time:.3f}",
                        "-t", f"{seg.duration:.3f}",
                        "-i", src_norm,
                    ])
                    # Pick optimal filter ordering based on source fps/resolution
                    try:
                        src_w, src_h, src_fps, _ = self.clip_cache.get_source_info(src_norm)
                    except Exception:
                        src_w, src_h, src_fps = 0, 0, 0.0

                    fps_part = f"fps=fps={opts.fps}:round=near:start_time=0"
                    scale_part = (
                        f"scale={opts.output_width}:{opts.output_height}"
                        f":force_original_aspect_ratio=increase:flags=bilinear,"
                        f"crop={opts.output_width}:{opts.output_height},setsar=1"
                    )
                    if src_w == opts.output_width and src_h == opts.output_height:
                        seg_chain = f"[{i}:v]setsar=1,{fps_part}[v{i}]"
                    elif src_fps > opts.fps + 0.5:
                        seg_chain = f"[{i}:v]{fps_part},{scale_part}[v{i}]"
                    else:
                        seg_chain = f"[{i}:v]{scale_part},{fps_part}[v{i}]"

                    filter_parts.append(seg_chain)
                    concat_inputs.append(f"[v{i}]")

                audio_input_idx = len(segments)
                input_args.extend(["-i", effective_audio_path])

                template_input_idx = None
                if effective_template_path:
                    template_input_idx = len(segments) + 1
                    input_args.extend(["-i", effective_template_path])

                filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=0[raw_concat]")
                filter_parts.append(
                    f"[raw_concat]tpad=stop_mode=clone:stop=-1,trim=start_frame=0:end_frame={target_frames},"
                    f"setpts=PTS-STARTPTS[bg_video]"
                )
                current_v_label = "[bg_video]"

            # Layer 1: Overlay transparent template PNG (below subtitles)
            if template_input_idx is not None:
                if template_needs_scale:
                    filter_parts.append(
                        f"[{template_input_idx}:v]scale={opts.output_width}:{opts.output_height}:flags=bilinear,"
                        f"format=yuva420p[tpl_scaled]"
                    )
                else:
                    filter_parts.append(f"[{template_input_idx}:v]format=yuva420p[tpl_scaled]")
                filter_parts.append(
                    f"{current_v_label}[tpl_scaled]overlay=0:0:eof_action=repeat[with_template]"
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
            try:
                filter_script_path.write_text(filter_complex_str, encoding="utf-8")
            except Exception as e:
                raise FFmpegError(f"写入 FFmpeg 滤镜脚本失败: {e}")

            # 7. Resolve encoder profile (HW accelerated or CPU) and execute with automatic CPU fallback
            primary_profile = resolve_encoder_profile(
                encode_mode=opts.encode_mode,
                preset=opts.preset,
                ffmpeg_path=self.ffmpeg_path,
            )

            def _build_cmd(enc_profile: EncoderProfile) -> list[str]:
                cmd_list = [self.ffmpeg_path, "-y"]
                cmd_list.extend(input_args)
                cmd_list.extend([
                    "-filter_complex_script", str(filter_script_path.resolve()),
                    "-map", video_map_label,
                    "-map", f"{audio_input_idx}:a",
                ])
                cmd_list.extend(
                    build_video_encode_args(
                        profile=enc_profile,
                        video_bitrate=opts.video_bitrate,
                        max_threads=opts.max_threads,
                    )
                )
                cmd_list.extend([
                    "-r", str(opts.fps),
                    "-video_track_timescale", str(opts.fps * 1000),
                    "-pix_fmt", "yuv420p",
                    "-frames:v", str(target_frames),
                ])
                if use_audio_copy:
                    cmd_list.extend(["-c:a", "copy"])
                else:
                    cmd_list.extend([
                        "-c:a", "aac",
                        "-b:a", opts.audio_bitrate,
                        "-ar", str(opts.audio_samplerate),
                    ])
                cmd_list.extend([
                    "-t", f"{target_duration:.3f}",
                    norm_output,
                ])
                return cmd_list

            cmd = _build_cmd(primary_profile)
            self._validate_cmd_length(cmd)

            logger.info(
                f"渲染管线: {'Concat缓存极速' if use_concat_demuxer else ('缓存直拼' if use_cache else '优化直出')} | "
                f"编码器: {primary_profile.display_name} ({primary_profile.codec}) | "
                f"音频: {'AAC流直拷' if use_audio_copy else 'AAC编码'}"
            )

            try:
                self._run_ffmpeg_render(cmd, target_duration, on_progress, token)
            except FFmpegError as hw_err:
                if primary_profile.is_hardware and not (token and token.is_cancelled):
                    logger.warning(
                        f"硬件编码器 ({primary_profile.codec}) 渲染异常，自动回退至 CPU 极速软编重试: {hw_err}"
                    )
                    fallback_cmd = _build_cmd(CPU_FAST_PROFILE)
                    self._validate_cmd_length(fallback_cmd)
                    self._run_ffmpeg_render(fallback_cmd, target_duration, on_progress, token)
                else:
                    raise

            if on_progress:
                on_progress(1.0)

            return norm_output
        finally:
            for tmp_p in (filter_script_path, concat_list_path, clean_srt_file):
                if tmp_p and tmp_p.exists():
                    for _attempt in range(3):
                        try:
                            tmp_p.unlink()
                            break
                        except PermissionError:
                            import time
                            time.sleep(0.05)
                        except Exception as ex:
                            logger.warning(f"清理临时文件失败: {tmp_p} ({ex})")
                            break

    @staticmethod
    def _validate_cmd_length(cmd: list[str]):
        cmd_str = subprocess.list2cmdline(cmd)
        cmd_length = len(cmd_str)
        logger.info(f"FFmpeg 命令行总字符长度: {cmd_length} (Windows 安全水位: 32,000 / 物理上限: 32,767)")
        if os.name == "nt" and cmd_length > 32000:
            raise FFmpegError(
                f"生成的 FFmpeg 命令行参数过长 ({cmd_length} 字符)，超出 Windows 安全水位限制 (32,000 字符)。\n"
                f"请减少素材分段数量或缩短素材文件夹路径以避免 CreateProcess 失败。"
            )

    @staticmethod
    def _run_ffmpeg_render(
        cmd: list[str],
        target_duration: float,
        on_progress: Optional[Callable[[float], None]],
        token: Optional[CancellationToken],
    ):
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            encoding="utf-8",
            errors="replace",
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
                try:
                    process.wait(timeout=3)
                except Exception:
                    pass
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
