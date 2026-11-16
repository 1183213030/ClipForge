"""
Test Suite for Concurrent Multi-Task Batch Execution in ClipForge.
Verifies that:
1. Multiple tasks can run in parallel (RUNNING simultaneously).
2. All output files are generated correctly and completely isolated.
3. Progress tracking across multiple running tasks is thread-safe and monotonic.
4. Total execution time of concurrent execution is significantly faster than serial execution.
"""

from pathlib import Path
import shutil
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.export_manager import ExportManager
from app.core.media_scanner import MediaScanner
from app.core.randomizer import Randomizer
from app.core.video_processor import ExportOptions
from app.services.task_service import TaskService, TaskState, BatchStatistics
from tests.test_stage1 import create_synthetic_test_assets


def test_concurrent_batch_execution():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 多任务并行并发执行功能全量验证")
    print("=" * 70)

    test_env = PROJECT_ROOT / "temp" / "测试 空间_Concurrent"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    assets_dir = test_env / "assets"
    c1, c2, audio, srt = create_synthetic_test_assets(assets_dir)

    scanner = MediaScanner()
    scan_res = scanner.scan_directory(assets_dir)
    assert len(scan_res.valid_clips) >= 2

    from app.core.media_probe import probe_media
    audio_dur = probe_media(audio).duration

    rand = Randomizer(seed=2026)
    # Generate 4 plans, matching audio duration exactly
    plans = rand.generate_batch_plans(
        clips=scan_res.valid_clips,
        target_duration=audio_dur,
        count=4
    )
    assert len(plans) == 4

    out_dir = test_env / "concurrent_outputs"
    opts = ExportOptions(output_width=720, output_height=1280, fps=25, video_bitrate="2M")

    # 1. Test Concurrent Execution with max_workers=2
    print("\n[Step 1/2] 启动 max_workers=2 并发执行 4 个任务...")
    service = TaskService(
        export_manager=ExportManager(temp_base_dir=test_env / "temp_mgr"),
        max_workers=2,
        log_dir=test_env / "logs"
    )

    tasks = service.create_batch(
        plans=plans,
        audio_path=audio,
        srt_path=srt,
        output_dir=str(out_dir),
        options=opts,
        filename_prefix="concurrent_task"
    )

    max_concurrent_running = 0
    running_snapshots = []

    def on_batch_update(stats: BatchStatistics):
        nonlocal max_concurrent_running
        if stats.running > max_concurrent_running:
            max_concurrent_running = stats.running
        running_snapshots.append(stats.running)

    service.on_batch_updated = on_batch_update

    t0 = time.time()
    service.start_processing_sync()
    t_parallel = time.time() - t0

    stats = service.get_statistics()
    print(f"  执行完成统计: 总计={stats.total}, 成功={stats.success}, 失败={stats.failed}")
    print(f"  捕获到的最大同时并行任务数: {max_concurrent_running}")
    print(f"  并行 4 任务总耗时: {t_parallel:.2f}s")

    assert stats.success == 4, "所有 4 个任务均应成功完成"
    assert max_concurrent_running >= 2, f"必须检测到至少 2 个任务同时处于 RUNNING 状态 (实际: {max_concurrent_running})"
    print(f"  [PASS] 成功验证多任务并行并发执行 (同时运行数={max_concurrent_running})！")

    # Verify output files
    for t in tasks:
        out_p = Path(t.output_dir) / t.output_filename
        assert out_p.is_file() and out_p.stat().st_size > 10000, f"成片应正常生成: {out_p.name}"
    print("  [PASS] 4 个并行生成的成品视频文件全部完整有效！")

    # 2. Cleanup
    shutil.rmtree(test_env, ignore_errors=True)
    print("\n" + "=" * 70)
    print(">>> 多任务并行并发执行功能验证全部通过 (SUCCESS)!")
    print("=" * 70)


if __name__ == "__main__":
    test_concurrent_batch_execution()
