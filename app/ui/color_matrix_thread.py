"""
Batch Color Matrix Export Thread for ClipForge 3.0.
Coordinates parallel execution of video color grading, resolution adaptation,
and badge burning with smooth cancellation and progress reporting.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app.core.color_matrix_processor import (
    ColorMatrixConfig,
    MatrixTaskUnit,
    ColorMatrixProcessor,
    COLOR_PRESETS,
    get_default_badge_path,
)
from app.core.hw_encoder import get_best_hardware_encoder, CPU_FAST_PROFILE
from app.utils.ffmpeg_utils import get_ffmpeg_path

logger = logging.getLogger(__name__)


@dataclass
class VideoQueueItem:
    """Represents a video in the batch queue."""
    source_path: Path
    duration_sec: float = 0.0
    status: str = "等待"      # 等待, 处理中, 完成, 失败, 已取消
    progress_pct: float = 0.0 # 0.0 - 100.0
    generated_count: int = 0
    total_target_count: int = 14
    elapsed_str: str = "00:00"


class ColorMatrixExportThread(QThread):
    """
    QThread for non-blocking batch rendering of multiple videos through the color matrix pipeline.
    """
    # Signals for UI synchronization
    video_item_started = Signal(int, str)  # (item_idx, filename)
    video_item_progress = Signal(int, int, int, float)  # (item_idx, done_units, total_units, current_unit_pct)
    video_item_finished = Signal(int, str, int, int)  # (item_idx, status, done_units, fail_units)
    batch_progress = Signal(int, int, int, str)  # (total_done, total_fail, grand_total, current_status_text)
    batch_finished = Signal(int, int)  # (total_success, total_fail)
    log_message = Signal(str, str)  # (message, level: "info" | "warn" | "error")

    def __init__(
        self,
        queue_items: list[VideoQueueItem],
        config: ColorMatrixConfig,
        parent=None,
    ):
        super().__init__(parent)
        self.queue_items = queue_items
        self.config = config
        self._is_cancelled = False
        self._cancel_lock = threading.Lock()

    def cancel(self):
        with self._cancel_lock:
            self._is_cancelled = True
        self.log_message.emit("收到终止请求，正在安全停止任务...", "warn")

    def is_cancelled(self) -> bool:
        with self._cancel_lock:
            return self._is_cancelled

    def run(self):
        ffmpeg_path = get_ffmpeg_path()
        best_hw = get_best_hardware_encoder(ffmpeg_path)
        encoder_profile = best_hw or CPU_FAST_PROFILE

        self.log_message.emit(
            f"启动矩阵调色渲染管线，检测到编码器: {encoder_profile.display_name} (硬件加速: {encoder_profile.is_hardware})",
            "info",
        )

        total_videos = len(self.queue_items)
        grand_total_units = 0

        # Calculate layouts to render
        layouts = []
        if self.config.output_landscape:
            layouts.append(("landscape", "横板"))
        if self.config.output_portrait:
            layouts.append(("portrait", "竖版"))
        if self.config.output_original_size or not layouts:
            layouts.append(("original_size", "原尺寸"))

        # Map color names
        color_name_map = {k: name for k, name, _ in COLOR_PRESETS}

        # Calculate total units
        for item in self.queue_items:
            item_units = len(self.config.colors) * len(layouts) * max(1, self.config.copies_per_color)
            item.total_target_count = item_units
            grand_total_units += item_units

        self.log_message.emit(
            f"待处理队列: {total_videos} 个视频，总计将生成 {grand_total_units} 个矩阵视频",
            "info",
        )

        grand_success = 0
        grand_fail = 0

        for item_idx, item in enumerate(self.queue_items):
            if self.is_cancelled():
                item.status = "已取消"
                self.video_item_finished.emit(item_idx, "已取消", item.generated_count, 0)
                break

            src_file = item.source_path
            out_dir = self.config.output_dir or src_file.parent
            out_dir.mkdir(parents=True, exist_ok=True)

            item.status = "处理中"
            self.video_item_started.emit(item_idx, src_file.name)

            # Build all units for this video
            units: list[MatrixTaskUnit] = []
            for color_key in self.config.colors:
                color_label = color_name_map.get(color_key, color_key)
                for layout_key, layout_label in layouts:
                    # Select layout-specific badge image
                    badge_img = None
                    if self.config.add_badge:
                        if layout_key == "portrait":
                            badge_img = self.config.portrait_badge_path or get_default_badge_path("portrait")
                        else:
                            badge_img = self.config.landscape_badge_path or get_default_badge_path("landscape")

                    for copy_i in range(1, max(1, self.config.copies_per_color) + 1):
                        copy_suffix = f"_{copy_i:02d}" if self.config.copies_per_color > 1 else ""
                        badge_tag = "+角标" if self.config.add_badge else ""
                        stem = src_file.stem
                        out_name = f"{stem}_{layout_label}_{color_label}{badge_tag}{copy_suffix}.mp4"
                        out_path = out_dir / out_name

                        unit = MatrixTaskUnit(
                            source_path=src_file,
                            output_path=out_path,
                            color=color_key,
                            strength=self.config.strength,
                            layout=layout_key,
                            add_badge=self.config.add_badge,
                            badge_text=self.config.badge_text,
                            badge_image_path=badge_img,
                            enable_fingerprint=self.config.enable_fingerprint,
                            copy_index=copy_i,
                        )
                        units.append(unit)

            item_done = 0
            item_fail = 0
            total_item_units = len(units)

            # Render units using configured concurrency pool (Safe for NVENC)
            concurrency = max(1, min(self.config.max_concurrent_nvenc, 3))
            processor = ColorMatrixProcessor(encoder_profile=encoder_profile)

            # Process units sequentially or with 2-way pool
            # For Turing 1650 SUPER, 2 concurrent sessions is the sweet spot
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_map = {}

                def make_progress_cb(u_idx):
                    def cb(pct):
                        if not self.is_cancelled():
                            self.video_item_progress.emit(item_idx, item_done, total_item_units, pct)
                    return cb

                for u_idx, u in enumerate(units):
                    if self.is_cancelled():
                        break
                    fut = executor.submit(
                        processor.render_unit,
                        u,
                        make_progress_cb(u_idx),
                        item.duration_sec,
                        self.is_cancelled,
                    )
                    future_map[fut] = u

                for fut in as_completed(future_map):
                    if self.is_cancelled():
                        break
                    u = future_map[fut]
                    try:
                        ok = fut.result()
                        if ok:
                            item_done += 1
                            grand_success += 1
                        else:
                            item_fail += 1
                            grand_fail += 1
                    except Exception as exc:
                        logger.error(f"Unit render exception: {exc}")
                        item_fail += 1
                        grand_fail += 1

                    item.generated_count = item_done
                    self.video_item_progress.emit(item_idx, item_done, total_item_units, 1.0)
                    self.batch_progress.emit(
                        grand_success,
                        grand_fail,
                        grand_total_units,
                        f"正在导出: {src_file.name} ({item_done}/{total_item_units}) ... 完成 {grand_success}, 失败 {grand_fail}",
                    )

            if self.is_cancelled():
                item.status = "已取消"
                self.video_item_finished.emit(item_idx, "已取消", item_done, item_fail)
                break

            item.status = "完成" if item_fail == 0 else ("部分完成" if item_done > 0 else "失败")
            self.video_item_finished.emit(item_idx, item.status, item_done, item_fail)

        self.log_message.emit(
            f"调色批处理结束: 成功导出 {grand_success} 个，失败 {grand_fail} 个",
            "info" if grand_fail == 0 else "warn",
        )
        self.batch_finished.emit(grand_success, grand_fail)
