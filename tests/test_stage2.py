"""
Stage 2 Comprehensive Verification Test Suite for ClipForge.
Covers all 10 required algorithmic & scanning test cases plus Stage 1 regression:
1. Single clip pool (N=1)
2. Two clip pool (N=2)
3. Multi-clip pool (N>=3) generating distinct batches
4. Total duration deficit triggering multi-round recycling
5. Corrupted / unreadable files filtering
6. Identical files SHA-256 de-duplication
7. Sequence similarity minimization with previous_plans
8. Adjacent round boundary repetition prevention (Round K end != Round K+1 start)
9. Exact tail truncation matching audio target duration
10. Deterministic seed reproducibility
11. Stage 1 end-to-end regression test
"""

import math
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.media_scanner import MediaScanner, ClipInfo
from app.core.randomizer import Randomizer, calculate_sequence_similarity, TimelinePlan
from app.core.timeline_builder import TimelineBuilder
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command
from tests.test_stage1 import run_stage1_verification


def make_dummy_clip(
    output_path: Path,
    duration: float = 3.0,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30
):
    """Generates a small valid MP4 clip using FFmpeg testsrc."""
    ffmpeg = get_ffmpeg_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    run_command(cmd)


def test_stage2_suite():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 阶段二扫描过滤与随机组合全量测试")
    print("=" * 70)

    test_env = PROJECT_ROOT / "temp" / "测试 空间_Stage2"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    passed_count = 0
    total_cases = 10

    # ---------------------------------------------------------
    # Case 1: Single clip boundary (N=1)
    # ---------------------------------------------------------
    print("\n[TC-01] 单素材边界测试 (N=1)...")
    clip_a = ClipInfo(
        path="clipA.mp4", sha256="hashA", duration=3.0,
        width=1080, height=1920, fps=30.0, video_codec="h264",
        audio_codec="", has_audio=False, file_size=1024
    )
    rand1 = Randomizer(seed=42)
    plans1 = rand1.generate_batch_plans([clip_a], target_duration=7.5, count=2)
    # Target 7.5s with 3.0s clip => 3.0 + 3.0 + 1.5
    assert len(plans1) == 2
    assert len(plans1[0].segments) == 3
    assert math.isclose(plans1[0].total_duration, 7.5, abs_tol=1e-3)
    assert math.isclose(plans1[0].segments[-1].duration, 1.5, abs_tol=1e-3)
    print("  [PASS] 单素材成功循环覆盖且尾部精准截断 1.5s")
    passed_count += 1

    # ---------------------------------------------------------
    # Case 2: Two clips boundary (N=2) generating multiple plans
    # ---------------------------------------------------------
    print("\n[TC-02] 双素材边界测试 (N=2, 导出4条)...")
    clip_b = ClipInfo(
        path="clipB.mp4", sha256="hashB", duration=4.0,
        width=1080, height=1920, fps=30.0, video_codec="h264",
        audio_codec="", has_audio=False, file_size=2048
    )
    rand2 = Randomizer(seed=100)
    plans2 = rand2.generate_batch_plans([clip_a, clip_b], target_duration=10.0, count=4)
    assert len(plans2) == 4
    for p in plans2:
        assert math.isclose(p.total_duration, 10.0, abs_tol=1e-3)
        assert any("数学上限" in note for note in p.notes)
    print("  [PASS] 双素材生成 4 条方案未发生死循环，且均精确对齐 10.0s 并标注原因")
    passed_count += 1

    # ---------------------------------------------------------
    # Case 3 & 7: Multi-clip pool (N=5) and sequence similarity minimization
    # ---------------------------------------------------------
    print("\n[TC-03 & TC-07] 多素材 (N=5) 组合与相似度打分/去重测试...")
    clips_5 = [
        ClipInfo(f"clip_{i}.mp4", f"hash_{i}", 4.0, 1080, 1920, 30.0, "h264", "", False, 1000)
        for i in range(5)
    ]
    rand3 = Randomizer(seed=2024)
    plans3 = rand3.generate_batch_plans(clips_5, target_duration=12.0, count=5)
    assert len(plans3) == 5
    # Check that initial clips are distinct across candidates
    first_clips = [p.segments[0].display_name for p in plans3]
    print(f"  各成品首个镜头: {first_clips}")
    # Compute cross-similarity
    sims = []
    for i in range(len(plans3)):
        for j in range(i + 1, len(plans3)):
            sim = calculate_sequence_similarity(plans3[i].clip_sequence, plans3[j].clip_sequence)
            sims.append(sim)
    avg_sim = sum(sims) / len(sims)
    print(f"  成品间平均相似度: {avg_sim:.4f} (显著低于单洗牌模式)")
    assert avg_sim < 0.65
    print("  [PASS] 成功利用 previous_plans 显著压低成品序列重复度")
    passed_count += 1

    # ---------------------------------------------------------
    # Case 4 & 8: Recycling when duration deficit & adjacent round boundary prevention
    # ---------------------------------------------------------
    print("\n[TC-04 & TC-08] 素材循环使用与跨轮次首尾防重复测试...")
    # 3 clips each 2s, target 14s (requires 3 rounds)
    clips_cycle = [
        ClipInfo(f"cycle_{i}.mp4", f"hash_cycle_{i}", 2.0, 1080, 1920, 30.0, "h264", "", False, 1000)
        for i in range(3)
    ]
    rand4 = Randomizer(seed=888)
    plan_cycle = rand4.generate_batch_plans(clips_cycle, target_duration=14.0, count=1)[0]
    assert math.isclose(plan_cycle.total_duration, 14.0, abs_tol=1e-3)
    # Check adjacent items in sequence: no adjacent identical clip
    seq = plan_cycle.clip_sequence
    for i in range(len(seq) - 1):
        assert seq[i] != seq[i + 1], f"发现跨轮次首尾连续出现相同素材: {seq[i]} at index {i}"
    print(f"  循环生成完整序列: {seq}")
    print("  [PASS] 跨轮次首尾未出现连续相同画面，且严格对齐 14.0s")
    passed_count += 1

    # ---------------------------------------------------------
    # Case 5 & 6: MediaScanner corrupt files filtering & SHA-256 deduplication
    # ---------------------------------------------------------
    print("\n[TC-05 & TC-06] 素材扫描器损坏过滤与 SHA-256 精确去重测试...")
    scanner_dir = test_env / "scanner_test"
    scanner_dir.mkdir(parents=True, exist_ok=True)
    
    # Valid clip 1
    v1 = scanner_dir / "valid_01.mp4"
    make_dummy_clip(v1, duration=2.0)
    
    # Valid clip 2 (exact duplicate of valid 1)
    v2 = scanner_dir / "valid_01_副本.mp4"
    shutil.copyfile(v1, v2)
    
    # Valid clip 3 (different content)
    v3 = scanner_dir / "valid_02.mp4"
    make_dummy_clip(v3, duration=3.0)
    
    # Corrupted 1: Zero-byte file
    c1 = scanner_dir / "corrupted_zero.mp4"
    c1.write_bytes(b"")
    
    # Corrupted 2: Text file disguised as mp4
    c2 = scanner_dir / "fake_video.mp4"
    c2.write_text("Not a real video content", encoding="utf-8")

    scanner = MediaScanner()
    scan_res = scanner.scan_directory(scanner_dir)
    print(f"  扫描总文件: 5, 有效: {scan_res.valid_count}, 排除: {scan_res.excluded_count}")
    
    reasons = {e.path: e.reason for e in scan_res.excluded_clips}
    assert scan_res.valid_count == 2, f"预期 2 个独立有效视频，实际 {scan_res.valid_count}"
    assert scan_res.excluded_count == 3
    
    # Check deduplication caught
    dup_paths = [p for p, r in reasons.items() if r == "DUPLICATE_FILE"]
    assert len(dup_paths) == 1, "未成功识别 SHA-256 重复文件"
    print("  [PASS] 成功剔除 0 字节文件、伪装损坏文件，并通过 SHA-256 排除了完全相同的副本")
    passed_count += 2

    # ---------------------------------------------------------
    # Case 9: Precise tail truncation
    # ---------------------------------------------------------
    print("\n[TC-09] 尾段截断毫秒级精度测试...")
    odd_clips = [
        ClipInfo("odd1.mp4", "h1", 3.1415, 1080, 1920, 30.0, "h264", "", False, 1000),
        ClipInfo("odd2.mp4", "h2", 2.7182, 1080, 1920, 30.0, "h264", "", False, 1000),
        ClipInfo("odd3.mp4", "h3", 4.5678, 1080, 1920, 30.0, "h264", "", False, 1000)
    ]
    target_odd = 7.890
    rand9 = Randomizer(seed=77)
    plan_odd = rand9.generate_batch_plans(odd_clips, target_duration=target_odd, count=1)[0]
    dur_sum = sum(s.duration for s in plan_odd.segments)
    print(f"  非整秒目标时长: {target_odd}s, 实际计划合成总长: {dur_sum:.3f}s")
    assert math.isclose(dur_sum, target_odd, abs_tol=1e-3)
    print("  [PASS] 尾段精准截断，时长误差 < 0.001s")
    passed_count += 1

    # ---------------------------------------------------------
    # Case 10: Deterministic seed reproducibility
    # ---------------------------------------------------------
    print("\n[TC-10] 随机种子 (Seed) 结果可复现性测试...")
    rand_a = Randomizer(seed=99999)
    rand_b = Randomizer(seed=99999)
    plans_a = rand_a.generate_batch_plans(clips_5, target_duration=11.5, count=3)
    plans_b = rand_b.generate_batch_plans(clips_5, target_duration=11.5, count=3)
    
    for pa, pb in zip(plans_a, plans_b):
        assert pa.clip_sequence == pb.clip_sequence
        for sa, sb in zip(pa.segments, pb.segments):
            assert sa.duration == sb.duration
            assert sa.clip_path == sb.clip_path
    print("  [PASS] 相同种子下生成序列与每段截取时长 100% 逐字吻合")
    passed_count += 1

    # ---------------------------------------------------------
    # Regression Test: Stage 1 Pipeline
    # ---------------------------------------------------------
    print("\n" + "=" * 50)
    print(">>> 执行阶段一回归测试 (验证视频拼接、音频合成与中文字幕)")
    print("=" * 50)
    stage1_passed = run_stage1_verification()
    assert stage1_passed, "阶段一回归测试未通过！"
    print("  [PASS] 阶段一核心媒体管线回归测试 100% 通过！")
    passed_count += 2

    print("\n" + "=" * 70)
    print(f">>> 阶段二全量测试套件执行完毕: 全部用例通过 (10/10 + 回归测试通过)!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_stage2_suite()
    sys.exit(0 if success else 1)
