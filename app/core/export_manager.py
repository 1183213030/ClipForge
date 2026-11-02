"""
Export Manager Module for ClipForge.
Manages individual render task execution, temp-file sandboxing,
strict FFprobe post-render validation, and atomic final file renaming.
"""

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Callable, Optional

from app.core.media_probe import probe_media, MediaMetadata
from app.core.randomizer import TimelinePlan
from app.core.timeline_builder import TimelineBuilder
from app.core.video_processor import (
    VideoProcessor, ExportOptions, CancellationToken, TaskCancelledError
)
from app.utils.ffmpeg_utils import FFmpegError
from app.utils.path_utils import normalize_path, ensure_dir


class ValidationError(Exception):
    """Raised when generated video fails FFprobe post-render verification."""
    pass


@dataclass
class RenderTaskParams:
    task_id: str
    plan: TimelinePlan
    audio_path: str
    srt_path: Optional[str]
    output_filename: str
    output_dir: str
    options: ExportOptions


class ExportManager:
    def __init__(self, temp_base_dir: str | Path = "temp"):
        self.temp_base_dir = ensure_dir(temp_base_dir)
        self.video_processor = VideoProcessor(temp_dir=self.temp_base_dir / "processor_temp")

    def resolve_unique_output_path(self, target_dir: Path, filename: str) -> Path:
        """Resolves filename conflicts by appending index e.g. name_1.mp4."""
        target_path = target_dir / filename
        if not target_path.exists():
            return target_path

        stem = target_path.stem
        suffix = target_path.suffix
        counter = 1
        while True:
            candidate = target_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def execute_render_task(
        self,
        params: RenderTaskParams,
        on_progress: Optional[Callable[[float], None]] = None,
        token: Optional[CancellationToken] = None
    ) -> Path:
        """
        Executes rendering safely:
        1. Writes to isolated temp file first.
        2. Validates output video via probe_media.
        3. Atomically moves valid video to final output destination.
        4. Cleans up temp file on failure or cancellation.
        """
        out_dir = ensure_dir(params.output_dir)
        final_dest = self.resolve_unique_output_path(out_dir, params.output_filename)

        # Isolated temp file path
        task_temp_dir = ensure_dir(self.temp_base_dir / f"task_{params.task_id}")
        temp_dest = task_temp_dir / f"in_progress_{final_dest.name}"

        segments = TimelineBuilder.plan_to_video_segments(params.plan)

        try:
            # 1. Render to temp destination
            rendered_temp = self.video_processor.render_mixed_video(
                segments=segments,
                audio_path=params.audio_path,
                srt_path=params.srt_path,
                output_path=temp_dest,
                options=params.options,
                on_progress=on_progress,
                token=token
            )

            # Check if cancelled right after render
            if token and token.is_cancelled:
                raise TaskCancelledError("任务已被用户取消。")

            # 2. Strict FFprobe post-render validation
            self._validate_output_file(Path(rendered_temp), params)

            # 3. Atomic rename to final destination
            if final_dest.exists():
                final_dest.unlink()
            shutil.move(rendered_temp, final_dest)

            # Cleanup task temp folder
            shutil.rmtree(task_temp_dir, ignore_errors=True)
            return final_dest

        except Exception as e:
            # Cleanup temp file on failure / cancellation to avoid leaving corrupted MP4s
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            shutil.rmtree(task_temp_dir, ignore_errors=True)
            raise e

    def _validate_output_file(self, file_path: Path, params: RenderTaskParams):
        """
        Validates generated video:
        - Must be readable and non-empty (>100KB).
        - Must contain valid video and audio streams.
        - Resolution must match requested output_width x output_height.
        - Framerate must match requested fps.
        - Duration must closely match plan.total_duration (within 0.25s).
        """
        if not file_path.is_file() or file_path.stat().st_size < 100 * 1024:
            raise ValidationError(f"输出文件不存在或体积异常过小 (<100KB): {file_path}")

        meta: MediaMetadata = probe_media(file_path)

        if not meta.has_video:
            raise ValidationError("输出视频缺少有效视频流。")

        if not meta.has_audio:
            raise ValidationError("输出视频缺少有效音频流。")

        opts = params.options
        if meta.width != opts.output_width or meta.height != opts.output_height:
            raise ValidationError(
                f"分辨率不匹配: 期望 {opts.output_width}x{opts.output_height}, 实际 {meta.width}x{meta.height}"
            )

        if abs(meta.fps - opts.fps) > 1.0:
            raise ValidationError(f"帧率不匹配: 期望 {opts.fps}fps, 实际 {meta.fps}fps")

        expected_dur = params.plan.total_duration
        if abs(meta.duration - expected_dur) > 0.25:
            raise ValidationError(
                f"时长不匹配: 期望 {expected_dur:.2f}s, 实际 {meta.duration:.2f}s (误差超过 0.25s)"
            )
