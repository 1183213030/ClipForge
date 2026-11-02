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
from app.services.task_service import TaskService, TaskRecord, BatchStatistics


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
