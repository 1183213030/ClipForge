"""
Timeline Builder Module for ClipForge.
Coordinates media scanning, audio probing, and batch timeline plan generation.
Prepares executable render tasks for the export manager.
"""

from pathlib import Path
from typing import Optional

from app.core.media_probe import probe_media
from app.core.media_scanner import MediaScanner, ScanResult, ClipInfo
from app.core.randomizer import Randomizer, TimelinePlan
from app.core.video_processor import VideoSegment
from app.utils.path_utils import normalize_path


class TimelineBuilder:
    def __init__(self, scanner: Optional[MediaScanner] = None, seed: Optional[int] = None):
        self.scanner = scanner or MediaScanner()
        self.seed = seed

    def build_plans_from_inputs(
        self,
        clips_folder: str | Path,
        audio_path: str | Path,
        count: int,
        previous_plans: Optional[list[TimelinePlan]] = None,
        recursive_scan: bool = False
    ) -> tuple[ScanResult, float, list[TimelinePlan]]:
        """
        1. Scans video clips folder (filtering and SHA-256 deduplicating).
        2. Probes novel audio duration.
        3. Generates 'count' distinct TimelinePlans using Randomizer.
        """
        # 1. Scan folder
        scan_res = self.scanner.scan_directory(clips_folder, recursive=recursive_scan)
        if not scan_res.valid_clips:
            raise ValueError(f"扫描目录中未找到任何有效视频素材: {clips_folder}")

        # 2. Probe audio
        norm_audio = normalize_path(audio_path)
        audio_meta = probe_media(norm_audio)
        if not audio_meta.is_valid_audio:
            raise ValueError(f"小说音频文件无效或无法读取: {norm_audio}")
        audio_duration = audio_meta.duration

        # 3. Randomize and build plans
        randomizer = Randomizer(seed=self.seed)
        plans = randomizer.generate_batch_plans(
            clips=scan_res.valid_clips,
            target_duration=audio_duration,
            count=count,
            previous_plans=previous_plans
        )

        return scan_res, audio_duration, plans

    @staticmethod
    def plan_to_video_segments(plan: TimelinePlan) -> list[VideoSegment]:
        """Converts high-level TimelinePlan segments to VideoProcessor segments."""
        return [
            VideoSegment(
                file_path=seg.clip_path,
                start_time=seg.start_time,
                duration=seg.duration
            )
            for seg in plan.segments
        ]
