"""
Qt Worker Threads Module for ClipForge.
Enforces UI responsiveness by delegating media probing, folder scanning,
and batch export queue execution to background QThreads.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app.core.media_probe import probe_media, MediaMetadata
from app.core.media_scanner import MediaScanner, ScanResult
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions, CancellationToken
from app.core.edit_project import EditProject
from app.services.task_service import TaskService, TaskRecord, BatchStatistics

import time
import uuid


class ProjectReExportThread(QThread):
    sig_progress = Signal(float)       # 0.0 - 100.0
    sig_finished = Signal(str, float)  # output_path, elapsed_seconds
    sig_error = Signal(str)

    def __init__(self, project: EditProject, output_path: str, temp_dir: Path, parent=None):
        super().__init__(parent)
        self.project = project
        self.output_path = output_path
        self.temp_dir = temp_dir
        self.token = CancellationToken()

    def run(self):
        t0 = time.time()
        try:
            # 1. Deterministic TimelinePlan
            plan = self.project.to_timeline_plan()
            render_segs = [
                VideoSegment(
                    file_path=s.clip_path,
                    start_time=s.start_time,
                    duration=s.duration
                )
                for s in plan.segments
            ]

            # 2. Options and Subtitles
            options = self.project.to_export_options()
            temp_srt = self.temp_dir / f"reexport_sub_{uuid.uuid4().hex[:6]}.srt"
            srt_path = self.project.export_edited_srt_file(temp_srt)

            # 3. Video Processing Pipeline
            processor = VideoProcessor(temp_dir=self.temp_dir)
            processor.render_mixed_video(
                segments=render_segs,
                audio_path=self.project.assets.audio_path,
                srt_path=srt_path,
                output_path=self.output_path,
                options=options,
                on_progress=lambda p: self.sig_progress.emit(p),
                token=self.token
            )

            # 4. Post-export FFprobe validation
            meta = probe_media(self.output_path)
            if not meta.is_valid_video:
                raise RuntimeError("导出的视频文件无效或无法被 FFprobe 解析。")

            elapsed = round(time.time() - t0, 2)
            self.project.add_export_history(
                output_path=self.output_path,
                status="SUCCESS",
                elapsed=elapsed
            )
            self.sig_finished.emit(self.output_path, elapsed)
        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            self.project.add_export_history(
                output_path=self.output_path,
                status="FAILED",
                elapsed=elapsed,
                error=str(e)
            )
            self.sig_error.emit(str(e))



class ScanFolderThread(QThread):
    sig_finished = Signal(object)  # ScanResult
    sig_error = Signal(str)

    def __init__(self, folder_path: str, recursive: bool = False, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.recursive = recursive

    def run(self):
        try:
            scanner = MediaScanner()
            result = scanner.scan_directory(self.folder_path, recursive=self.recursive)
            self.sig_finished.emit(result)
        except Exception as e:
            self.sig_error.emit(str(e))


class ProbeAudioThread(QThread):
    sig_finished = Signal(object)  # MediaMetadata
    sig_error = Signal(str)

    def __init__(self, audio_path: str, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path

    def run(self):
        try:
            meta = probe_media(self.audio_path)
            self.sig_finished.emit(meta)
        except Exception as e:
            self.sig_error.emit(str(e))


class BatchExportThread(QThread):
    sig_task_updated = Signal(object)      # TaskRecord
    sig_batch_updated = Signal(object)     # BatchStatistics
    sig_finished = Signal(object)          # BatchStatistics

    def __init__(self, task_service: TaskService, parent=None):
        super().__init__(parent)
        self.task_service = task_service

        # Bind TaskService internal callbacks to Qt thread-safe signals
        self.task_service.on_task_updated = lambda t: self.sig_task_updated.emit(t)
        self.task_service.on_batch_updated = lambda b: self.sig_batch_updated.emit(b)

    def run(self):
        try:
            # Process entire queue synchronously within this worker QThread
            self.task_service.start_processing_sync()
            final_stats = self.task_service.get_statistics()
            self.sig_finished.emit(final_stats)
        except Exception as e:
            # In case unexpected error occurs
            final_stats = self.task_service.get_statistics()
            self.sig_finished.emit(final_stats)
