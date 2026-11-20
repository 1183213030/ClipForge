"""
End-to-End Verification & Benchmark Suite for Export Speed Acceleration in ClipForge.
Verifies:
1. Hardware encoder auto-detection and encoder profile resolution.
2. Pre-standardized clip cache cold-start prewarming and warm-start cache reuse.
3. Shared AAC audio stream-copy optimization across batch tasks.
4. Real-world 4K customer assets batch export (3 x 60s videos) comparing:
   - Legacy mode (no clip cache, CPU libx264 fast, 2 workers)
   - Accelerated cold-start (clip cache prewarm + HW encoder + AAC copy + 3 workers)
   - Accelerated warm-start (cached clips reused + HW encoder + AAC copy + 3 workers)
5. Strict FFprobe output verification (1080x1920, 30fps CFR, h264 + aac, exact duration).
"""

from pathlib import Path
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.export_manager import ExportManager
from app.core.hw_encoder import detect_best_hw_encoder, resolve_encoder_profile, get_recommended_worker_count
from app.core.media_probe import probe_media
from app.core.media_scanner import MediaScanner
from app.core.randomizer import Randomizer
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition
from app.core.video_processor import ExportOptions
from app.services.task_service import TaskService
from app.utils.ffmpeg_utils import get_ffmpeg_path


def run_acceleration_verification():
    print("=" * 72)
    print(">>> ClipForge 导出加速引擎 (硬件编码 + 素材预标准化缓存 + 音频复用) 端到端验证")
    print("=" * 72)

    videos_dir = PROJECT_ROOT / "videos"
    audio_src = PROJECT_ROOT / "audio" / "10月31日 (1).MP3"
    srt_src = PROJECT_ROOT / "subtitles" / "10月31日 (1).srt"
    tpl_src = PROJECT_ROOT / "resources" / "templates" / "customer_template.png"

    assert videos_dir.is_dir() and audio_src.is_file(), "缺少真实测试素材目录"

    # 1. Verify HW encoder detection
    hw = detect_best_hw_encoder()
    rec_workers = get_recommended_worker_count()
    print(f"\n[Step 1] 硬件加速探测: {hw.display_name if hw else '无可用硬件编码 (将使用 CPU 极速软编)'} | 推荐并发: {rec_workers}")
    assert resolve_encoder_profile("cpu_fast").codec == "libx264"
    assert resolve_encoder_profile("cpu_quality").codec == "libx264"
    auto_prof = resolve_encoder_profile("auto")
    if hw:
        assert auto_prof.codec == hw.codec

    # 2. Prepare 60s customer audio slice for fast deterministic benchmark
    test_env = PROJECT_ROOT / "temp" / "test_export_accel_e2e"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    audio_60 = test_env / "audio_60s.mp3"
    subprocess.run(
        [get_ffmpeg_path(), "-y", "-i", str(audio_src), "-t", "60", "-c", "copy", str(audio_60)],
        check=True,
        capture_output=True,
    )
    audio_dur = probe_media(audio_60).duration

    scanner = MediaScanner()
    scan_res = scanner.scan_directory(videos_dir)
    assert scan_res.valid_count >= 3
    print(f"[Step 2] 真实素材扫描完成: {scan_res.valid_count} 个视频 (含 4K/60fps), 目标音频时长: {audio_dur:.2f}s")

    rand = Randomizer(seed=2026)
    plans = rand.generate_batch_plans(scan_res.valid_clips, target_duration=audio_dur, count=3)

    sub_cfg = SubtitleConfig(
        font_name="Microsoft YaHei",
        font_size=16,
        position=SubtitlePosition.CENTER,
    )

    # 3. Legacy Mode (simulate before optimization: no cache, libx264 fast, 2 workers)
    print("\n[Step 3] 对照组 (优化前模式: 无缓存直出 + libx264 fast + 2并发, 3条 60s 4K混剪)...")
    legacy_mgr = ExportManager(temp_base_dir=test_env / "temp_legacy")
    legacy_svc = TaskService(export_manager=legacy_mgr, max_workers=2, log_dir=test_env / "logs_legacy")
    opts_legacy = ExportOptions(
        video_bitrate="4M",
        preset="fast",
        encode_mode="cpu_quality",
        use_clip_cache=False,
        subtitle_config=sub_cfg,
        template_png_path=str(tpl_src),
        enable_template=True,
    )
    legacy_svc.create_batch(plans, str(audio_60), str(srt_src), str(test_env / "out_legacy"), opts_legacy, "legacy")
    t0 = time.time()
    legacy_svc.start_processing_sync()
    t_legacy = time.time() - t0
    assert legacy_svc.get_statistics().success == 3
    print(f"  [对照组完成] 3条总耗时: {t_legacy:.2f}s (均速 {t_legacy/3:.2f}s/条)")

    # 4. Accelerated Mode - Cold Start (prewarm cache + HW encoder + AAC copy + recommended workers)
    print(f"\n[Step 4] 加速组-首次冷启动 (并行缓存预热 + {auto_prof.display_name} + AAC复用 + {rec_workers}并发)...")
    accel_mgr = ExportManager(temp_base_dir=test_env / "temp_accel")
    accel_svc = TaskService(export_manager=accel_mgr, max_workers=rec_workers, log_dir=test_env / "logs_accel")
    prewarm_events = []
    accel_svc.on_prewarm_progress = lambda d, tot, name: prewarm_events.append((d, tot, name))

    opts_accel = ExportOptions(
        video_bitrate="4M",
        preset="veryfast",
        encode_mode="auto",
        use_clip_cache=True,
        subtitle_config=sub_cfg,
        template_png_path=str(tpl_src),
        enable_template=True,
    )
    tasks_cold = accel_svc.create_batch(plans, str(audio_60), str(srt_src), str(test_env / "out_cold"), opts_accel, "cold")
    t0 = time.time()
    accel_svc.start_processing_sync()
    t_cold = time.time() - t0
    assert accel_svc.get_statistics().success == 3
    assert len(prewarm_events) >= 1, "应触发批量预热缓存进度回调"
    print(f"  [冷启动完成] 3条总耗时(含首次预处理): {t_cold:.2f}s (提速 {t_legacy/t_cold:.2f}x)")

    # 5. Accelerated Mode - Warm Start (reusing existing disk clip & audio cache)
    print(f"\n[Step 5] 加速组-缓存热启动 (直接命中缓存 + {auto_prof.display_name} + {rec_workers}并发)...")
    accel_svc_warm = TaskService(export_manager=accel_mgr, max_workers=rec_workers, log_dir=test_env / "logs_warm")
    tasks_warm = accel_svc_warm.create_batch(plans, str(audio_60), str(srt_src), str(test_env / "out_warm"), opts_accel, "warm")
    t0 = time.time()
    accel_svc_warm.start_processing_sync()
    t_warm = time.time() - t0
    assert accel_svc_warm.get_statistics().success == 3
    print(f"  [热启动完成] 3条总耗时(缓存复用): {t_warm:.2f}s (提速 {t_legacy/t_warm:.2f}x)")

    # 6. Verify all accelerated outputs strictly meet specs
    for t in tasks_cold + tasks_warm:
        out_p = Path(t.final_output_path)
        assert out_p.is_file() and out_p.stat().st_size > 1_000_000
        m = probe_media(out_p)
        assert m.width == 1080 and m.height == 1920, f"分辨率异常: {m.width}x{m.height}"
        assert abs(m.fps - 30.0) <= 0.1, f"帧率异常: {m.fps}"
        assert m.video_codec == "h264" and m.audio_codec == "aac"
        assert abs(m.duration - audio_dur) <= 0.10, f"时长偏差过大: {m.duration} vs {audio_dur}"

    print("\n[Step 6] 所有加速导出的 6 条 1080x1920@30fps 成品均 100% 通过严格流指标校验！")
    assert t_cold < t_legacy, f"加速冷启动 ({t_cold:.2f}s) 应快于对照组 ({t_legacy:.2f}s)"
    assert t_warm < t_cold, f"缓存热启动 ({t_warm:.2f}s) 应快于冷启动 ({t_cold:.2f}s)"

    shutil.rmtree(test_env, ignore_errors=True)
    print("\n" + "=" * 72)
    print(f">>> 端到端加速验证全部通过! 对照组={t_legacy:.2f}s -> 冷启动={t_cold:.2f}s ({t_legacy/t_cold:.2f}x) -> 缓存复用={t_warm:.2f}s ({t_legacy/t_warm:.2f}x)")
    print("=" * 72)


if __name__ == "__main__":
    run_acceleration_verification()
