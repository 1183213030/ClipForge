"""
Task Management and Batch Scheduler Service for ClipForge.
Coordinates serial task execution, weighted overall progress calculation,
isolated error handling, cancellation token binding, task retry, and export manifest logging.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
import threading
import time
from typing import Callable, Optional

from app.core.export_manager import ExportManager, RenderTaskParams
from app.core.randomizer import TimelinePlan
from app.core.video_processor import ExportOptions, CancellationToken, TaskCancelledError
from app.utils.path_utils import normalize_path, ensure_dir


class TaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TaskRecord:
    task_id: str
    output_filename: str
    plan: TimelinePlan
    audio_path: str
    srt_path: Optional[str]
    output_dir: str
    options: ExportOptions
    state: TaskState = TaskState.PENDING
    progress: float = 0.0  # 0.0 ~ 1.0
    target_duration: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    elapsed_seconds: float = 0.0
    final_output_path: Optional[str] = None
    error_message: Optional[str] = None
    log_file: Optional[str] = None
    token: CancellationToken = field(default_factory=CancellationToken)

    @property
    def is_finished(self) -> bool:
        return self.state in {TaskState.SUCCESS, TaskState.FAILED, TaskState.CANCELLED}


@dataclass
class BatchStatistics:
    total: int = 0
    pending: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0
    cancelled: int = 0
    weighted_progress: float = 0.0  # 0.0 ~ 1.0


class TaskService:
    def __init__(
        self,
        export_manager: Optional[ExportManager] = None,
        max_workers: int = 1,
        log_dir: str | Path = "logs"
    ):
        self.export_manager = export_manager or ExportManager()
        self.max_workers = max_workers
        self.log_dir = ensure_dir(log_dir)
        self.tasks: list[TaskRecord] = []
        self._lock = threading.RLock()
        self._is_running_queue = False
        self._queue_thread: Optional[threading.Thread] = None

        # Event callbacks
        self.on_task_updated: Optional[Callable[[TaskRecord], None]] = None
        self.on_batch_updated: Optional[Callable[[BatchStatistics], None]] = None

    def create_batch(
        self,
        plans: list[TimelinePlan],
        audio_path: str,
        srt_path: Optional[str],
        output_dir: str,
        options: ExportOptions,
        filename_prefix: str = "output"
    ) -> list[TaskRecord]:
        """Creates a batch of tasks from TimelinePlans."""
        with self._lock:
            new_tasks = []
            for i, plan in enumerate(plans):
                task_id = f"TASK_{len(self.tasks) + 1:03d}"
                out_name = f"{filename_prefix}_{i + 1:03d}.mp4"
                dur = plan.total_duration

                log_path = str(self.log_dir / f"{task_id}.log")
                rec = TaskRecord(
                    task_id=task_id,
                    output_filename=out_name,
                    plan=plan,
                    audio_path=audio_path,
                    srt_path=srt_path,
                    output_dir=output_dir,
                    options=options,
                    target_duration=dur,
                    log_file=log_path
                )
                self.tasks.append(rec)
                new_tasks.append(rec)

            self._notify_batch_update()
            return new_tasks

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            for t in self.tasks:
                if t.task_id == task_id:
                    return t
            return None

    def get_statistics(self) -> BatchStatistics:
        with self._lock:
            total = len(self.tasks)
            pending = sum(1 for t in self.tasks if t.state == TaskState.PENDING)
            running = sum(1 for t in self.tasks if t.state == TaskState.RUNNING)
            success = sum(1 for t in self.tasks if t.state == TaskState.SUCCESS)
            failed = sum(1 for t in self.tasks if t.state == TaskState.FAILED)
            cancelled = sum(1 for t in self.tasks if t.state == TaskState.CANCELLED)

            total_weight = sum(t.target_duration for t in self.tasks)
            if total_weight <= 0:
                weighted_prog = 0.0
            else:
                completed_prog = sum(
                    t.target_duration * (1.0 if t.state == TaskState.SUCCESS else t.progress)
                    for t in self.tasks
                )
                weighted_prog = round(min(max(completed_prog / total_weight, 0.0), 1.0), 4)

            return BatchStatistics(
                total=total,
                pending=pending,
                running=running,
                success=success,
                failed=failed,
                cancelled=cancelled,
                weighted_progress=weighted_prog
            )

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a single pending or running task."""
        with self._lock:
            task = self.get_task(task_id)
            if not task or task.is_finished:
                return False

            if task.state == TaskState.PENDING:
                task.state = TaskState.CANCELLED
                task.completed_at = datetime.now().isoformat()
                self._log_task(task, "Task cancelled while in PENDING state.")
                self._notify_task_update(task)
                self._notify_batch_update()
                return True

            if task.state == TaskState.RUNNING:
                task.token.cancel()
                # State will be finalized by the worker thread
                return True

            return False

    def cancel_all(self):
        """Cancels all pending and running tasks."""
        with self._lock:
            for task in self.tasks:
                if not task.is_finished:
                    self.cancel_task(task.task_id)

    def retry_task(self, task_id: str) -> bool:
        """Resets a failed or cancelled task back to PENDING."""
        with self._lock:
            task = self.get_task(task_id)
            if not task or task.state not in {TaskState.FAILED, TaskState.CANCELLED}:
                return False

            task.state = TaskState.PENDING
            task.progress = 0.0
            task.started_at = None
            task.completed_at = None
            task.error_message = None
            task.token = CancellationToken()
            self._log_task(task, "Task reset for retry.")
            self._notify_task_update(task)
            self._notify_batch_update()
            return True

    def start_processing_sync(self):
        """Processes task queue synchronously in the current thread (serial)."""
        self._process_queue_internal()

    def start_processing_async(self):
        """Spawns background thread to process task queue asynchronously."""
        with self._lock:
            if self._is_running_queue:
                return
            self._is_running_queue = True
            self._queue_thread = threading.Thread(
                target=self._process_queue_internal, daemon=True
            )
            self._queue_thread.start()

    def _process_queue_internal(self):
        try:
            while True:
                # Find next pending task
                next_task: Optional[TaskRecord] = None
                with self._lock:
                    for t in self.tasks:
                        if t.state == TaskState.PENDING:
                            next_task = t
                            break

                if not next_task:
                    break

                self._execute_single_task(next_task)
        finally:
            with self._lock:
                self._is_running_queue = False
                self._notify_batch_update()

    def _execute_single_task(self, task: TaskRecord):
        # Check if already cancelled
        if task.token.is_cancelled:
            task.state = TaskState.CANCELLED
            task.completed_at = datetime.now().isoformat()
            self._notify_task_update(task)
            self._notify_batch_update()
            return

        with self._lock:
            task.state = TaskState.RUNNING
            task.started_at = datetime.now().isoformat()
            task.progress = 0.0
            self._notify_task_update(task)
            self._notify_batch_update()

        start_time = time.time()
        self._log_task(task, f"Started execution of {task.task_id}")

        def on_prog(ratio: float):
            with self._lock:
                task.progress = ratio
                self._notify_task_update(task)
                self._notify_batch_update()

        params = RenderTaskParams(
            task_id=task.task_id,
            plan=task.plan,
            audio_path=task.audio_path,
            srt_path=task.srt_path,
            output_filename=task.output_filename,
            output_dir=task.output_dir,
            options=task.options
        )

        try:
            final_path = self.export_manager.execute_render_task(
                params=params,
                on_progress=on_prog,
                token=task.token
            )
            with self._lock:
                task.state = TaskState.SUCCESS
                task.progress = 1.0
                task.final_output_path = str(final_path)
                task.completed_at = datetime.now().isoformat()
                task.elapsed_seconds = round(time.time() - start_time, 2)
                self._log_task(
                    task,
                    f"Task succeeded in {task.elapsed_seconds}s. Output: {final_path}"
                )

        except TaskCancelledError:
            with self._lock:
                task.state = TaskState.CANCELLED
                task.completed_at = datetime.now().isoformat()
                task.elapsed_seconds = round(time.time() - start_time, 2)
                self._log_task(task, "Task execution was cancelled by user.")

        except Exception as e:
            with self._lock:
                task.state = TaskState.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.now().isoformat()
                task.elapsed_seconds = round(time.time() - start_time, 2)
                self._log_task(task, f"Task failed: {str(e)}")

        finally:
            with self._lock:
                self._notify_task_update(task)
                self._notify_batch_update()

    def generate_manifest(self, output_dir: str | Path, batch_name: str = "BATCH_001") -> Path:
        """Generates export manifest JSON documenting all materials and seeds used."""
        target_dir = ensure_dir(output_dir)
        manifest_file = target_dir / f"export_manifest_{batch_name}.json"

        records = []
        with self._lock:
            for t in self.tasks:
                records.append({
                    "task_id": t.task_id,
                    "output_filename": t.output_filename,
                    "final_output_path": t.final_output_path,
                    "state": t.state.value,
                    "elapsed_seconds": t.elapsed_seconds,
                    "target_duration": t.target_duration,
                    "audio_path": t.audio_path,
                    "used_clips_sequence": t.plan.clip_sequence,
                    "used_clip_segments": [
                        {
                            "name": s.display_name,
                            "sha256": s.clip_sha256,
                            "start": s.start_time,
                            "duration": s.duration
                        }
                        for s in t.plan.segments
                    ],
                    "video_bitrate": t.options.video_bitrate,
                    "fps": t.options.fps,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at,
                    "error_message": t.error_message
                })

        manifest_data = {
            "batch_name": batch_name,
            "generated_at": datetime.now().isoformat(),
            "statistics": self.get_statistics().__dict__,
            "tasks": records
        }

        manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return manifest_file

    def _log_task(self, task: TaskRecord, message: str):
        if not task.log_file:
            return
        try:
            p = Path(task.log_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass

    def _notify_task_update(self, task: TaskRecord):
        if self.on_task_updated:
            try:
                self.on_task_updated(task)
            except Exception:
                pass

    def _notify_batch_update(self):
        if self.on_batch_updated:
            try:
                self.on_batch_updated(self.get_statistics())
            except Exception:
                pass
