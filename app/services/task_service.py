"""
Task Management and Batch Scheduler Service for ClipForge.
Coordinates serial task execution, weighted overall progress calculation,
isolated error handling, cancellation token binding, task retry, and export manifest logging.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
import concurrent.futures
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

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
        self._batch_cancelled = False
        self._queue_thread: Optional[threading.Thread] = None

        # Event callbacks
        self.on_task_updated: Optional[Callable[[TaskRecord], None]] = None
        self.on_batch_updated: Optional[Callable[[BatchStatistics], None]] = None
        self.on_prewarm_progress: Optional[Callable[[int, int, str], None]] = None

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
            self._batch_cancelled = True
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

    def _prewarm_batch_assets(self, pending_tasks: list[TaskRecord], workers_count: int):
        """
        Pre-standardizes unique video clips in parallel and pre-transcodes shared audio to AAC once
        before the batch rendering workers start, avoiding redundant 4K decoding/scaling across tasks.
        """
        if not pending_tasks:
            return

        clip_cache = getattr(self.export_manager, "clip_cache", None)
        if clip_cache is None:
            return

        # Group clips by (width, height, fps) for cacheable tasks
        spec_to_clips: dict[tuple[int, int, int], list[str]] = {}
        total_segments = 0
        for t in pending_tasks:
            if not t.options.use_clip_cache:
                continue
            spec = (t.options.output_width, t.options.output_height, t.options.fps)
            bucket = spec_to_clips.setdefault(spec, [])
            for seg in t.plan.segments:
                bucket.append(seg.clip_path)
                total_segments += 1

        # Decide if clip prewarming pays off (multiple tasks, reused clips, or >= 4 segments)
        for (w, h, fps), clip_paths in spec_to_clips.items():
            if self._batch_cancelled:
                return
            unique_clips = list(dict.fromkeys(clip_paths))
            should_prewarm = (
                len(pending_tasks) >= 2
                or total_segments > len(unique_clips)
                or total_segments >= 4
            )
            if not should_prewarm:
                # Also prewarm if any source clip is >1080p or >fps
                for cp in unique_clips:
                    try:
                        sw, sh, sfps, _ = clip_cache.get_source_info(cp)
                        if (sw * sh) > (w * h * 1.2) or sfps > fps + 5:
                            should_prewarm = True
                            break
                    except Exception:
                        continue

            if should_prewarm and unique_clips:
                try:
                    clip_cache.prewarm_clips(
                        clip_paths=unique_clips,
                        width=w,
                        height=h,
                        fps=fps,
                        on_progress=self._notify_prewarm_progress,
                        cancel_check=lambda: self._batch_cancelled,
                    )
                except Exception as exc:
                    logger.warning(f"批量素材预热缓存跳过，将按需渲染: {exc}")

        if self._batch_cancelled:
            return

        # Pre-transcode shared audio to AAC once when >= 2 tasks reuse the same audio file
        audio_groups: dict[tuple[str, str, int], list[TaskRecord]] = {}
        for t in pending_tasks:
            key = (normalize_path(t.audio_path), t.options.audio_bitrate, t.options.audio_samplerate)
            audio_groups.setdefault(key, []).append(t)

        for (audio_p, a_br, a_sr), group_tasks in audio_groups.items():
            if self._batch_cancelled:
                return
            if len(group_tasks) >= 2:
                prepared_aac = clip_cache.prepare_audio_aac(
                    audio_path=audio_p,
                    audio_bitrate=a_br,
                    audio_samplerate=a_sr,
                )
                if prepared_aac:
                    for gt in group_tasks:
                        gt.options = replace(
                            gt.options,
                            prepared_audio_path=str(prepared_aac),
                            audio_duration_hint=gt.target_duration if gt.target_duration > 0 else gt.options.audio_duration_hint,
                        )

        # Assign balanced per-worker CPU thread budgets when running multiple concurrent workers
        if workers_count > 1:
            cpu = os.cpu_count() or 4
            per_worker_threads = max(2, cpu // workers_count)
            for t in pending_tasks:
                if t.options.max_threads is None:
                    t.options = replace(t.options, max_threads=per_worker_threads)

    def _notify_prewarm_progress(self, done: int, total: int, clip_name: str):
        if self.on_prewarm_progress:
            try:
                self.on_prewarm_progress(done, total, clip_name)
            except Exception:
                pass

    def _process_queue_internal(self):
        try:
            with self._lock:
                self._batch_cancelled = False
                initial_pending = [t for t in self.tasks if t.state == TaskState.PENDING]

            workers_count = max(1, self.max_workers)

            # Pre-standardize shared clips & audio once before spawning render workers
            if initial_pending and not self._batch_cancelled:
                self._prewarm_batch_assets(initial_pending, workers_count)

            if workers_count == 1:
                # Serial mode: sequential execution
                while True:
                    next_task: Optional[TaskRecord] = None
                    with self._lock:
                        for t in self.tasks:
                            if t.state == TaskState.PENDING:
                                next_task = t
                                break
                    if not next_task:
                        break
                    self._execute_single_task(next_task)
            else:
                # Concurrent multi-worker mode: parallel execution up to workers_count
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as executor:
                    active_futures: dict[concurrent.futures.Future, TaskRecord] = {}

                    while True:
                        with self._lock:
                            pending_tasks = [t for t in self.tasks if t.state == TaskState.PENDING]

                            while pending_tasks and len(active_futures) < workers_count:
                                task_to_run = pending_tasks.pop(0)
                                task_to_run.state = TaskState.RUNNING
                                task_to_run.started_at = datetime.now().isoformat()
                                task_to_run.progress = 0.0
                                self._notify_task_update(task_to_run)
                                self._notify_batch_update()

                                fut = executor.submit(self._execute_single_task, task_to_run)
                                active_futures[fut] = task_to_run

                        if not active_futures:
                            break

                        done, _ = concurrent.futures.wait(
                            active_futures.keys(),
                            timeout=0.2,
                            return_when=concurrent.futures.FIRST_COMPLETED
                        )
                        for fut in done:
                            active_futures.pop(fut, None)
        finally:
            with self._lock:
                self._is_running_queue = False
                self._notify_batch_update()

    def _execute_single_task(self, task: TaskRecord):
        # Check if already cancelled
        if task.token.is_cancelled:
            with self._lock:
                task.state = TaskState.CANCELLED
                task.completed_at = datetime.now().isoformat()
                self._notify_task_update(task)
                self._notify_batch_update()
            return

        with self._lock:
            if task.state != TaskState.RUNNING:
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
