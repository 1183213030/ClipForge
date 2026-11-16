"""
Test Suite for 10-Video Batch Generation with Unique Openers and Global Footage Dispersion.
Verifies that:
1. When generating 10 videos with sufficient clips (e.g. 30 clips):
   - All 10 videos have 100% DISTINCT opening clips (开头绝对互斥，零重复).
   - Video clips across the batch are globally dispersed to minimize/eliminate overlap.
   - Each video has zero intra-video clip repetition when duration allows.
2. When generating with moderate clips (e.g. 15 clips):
   - All 10 videos still have 100% DISTINCT opening clips.
   - Global clip usage across the batch is completely balanced (every clip used ~2 times).
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.media_scanner import ClipInfo
from app.core.randomizer import Randomizer


def test_batch_10_unique_openers():
    print("=" * 70)
    print(">>> 验证 10 条视频批量混剪: 开头绝对互斥不重复 + 全局画面最大分散")
    print("=" * 70)

    # -------------------------------------------------------------
    # Scenario 1: User provides 30 clips, generates 10 videos
    # Target duration: 20s (each clip 5s -> 4 clips per video, total 40 slots needed)
    # -------------------------------------------------------------
    print("\n[Scenario 1] 用户提供 30 个解压素材，批量生成 10 个视频...")
    clips_30 = [
        ClipInfo(
            path=f"/path/to/decompression_clip_{i:02d}.mp4",
            sha256=f"sha256_clip_{i:02d}",
            duration=5.0,
            width=1080,
            height=1920,
            fps=30.0,
            video_codec="h264",
            audio_codec="",
            has_audio=False,
            file_size=1024 * 1024
        )
        for i in range(30)
    ]

    rand = Randomizer(seed=2026)
    plans = rand.generate_batch_plans(
        clips=clips_30,
        target_duration=20.0,
        count=10
    )

    assert len(plans) == 10, "应当成功生成 10 个视频方案"

    # 1. Verify 100% Unique Openers
    openers = [p.segments[0].clip_sha256 for p in plans]
    opener_names = [p.segments[0].display_name for p in plans]
    print(f"  各视频开头镜头列表 (共 10 个):")
    for idx, name in enumerate(opener_names):
        print(f"    视频 #{idx+1:02d} 开头: {name}")

    unique_openers_count = len(set(openers))
    assert unique_openers_count == 10, f"10 个视频的开头必须 100% 互斥不重复，实际唯一数: {unique_openers_count}"
    print(f"  [PASS] 10 个视频开头镜头 100% 独立，零重复！")

    # 2. Verify Internal & Cross-Video Dispersion
    # Check no intra-video repetition (since 30 clips > 4 clips per video)
    for idx, p in enumerate(plans):
        seq = [s.clip_sha256 for s in p.segments]
        assert len(seq) == len(set(seq)), f"视频 #{idx+1} 内部不应出现重复素材"

    # Check pairwise clip overlap
    overlaps = []
    for i in range(10):
        for j in range(i + 1, 10):
            s1 = set(s.clip_sha256 for s in plans[i].segments)
            s2 = set(s.clip_sha256 for s in plans[j].segments)
            overlaps.append(len(s1.intersection(s2)))

    avg_overlap = sum(overlaps) / len(overlaps)
    max_overlap = max(overlaps)
    print(f"  跨视频画面重合统计 (每条成片包含 4 个镜头):")
    print(f"    平均两两重合镜头数: {avg_overlap:.2f} 个")
    print(f"    最大两两重合镜头数: {max_overlap} 个")
    assert avg_overlap < 1.0, f"充分素材下跨视频重合度应极低 (< 1.0)，实际: {avg_overlap:.2f}"
    print("  [PASS] 内部画面高度分散，素材充分下实现最低重合！")

    # -------------------------------------------------------------
    # Scenario 2: Moderate clip pool (15 clips, 10 videos)
    # -------------------------------------------------------------
    print("\n[Scenario 2] 用户提供 15 个素材，批量生成 10 个视频 (素材库略少于需求总量)...")
    clips_15 = clips_30[:15]
    plans_15 = rand.generate_batch_plans(
        clips=clips_15,
        target_duration=20.0,
        count=10
    )
    assert len(plans_15) == 10

    openers_15 = [p.segments[0].clip_sha256 for p in plans_15]
    assert len(set(openers_15)) == 10, "15 个素材足够分配 10 个视频互不相同的开头！"
    print(f"  [PASS] 15 个素材库下，10 个视频开头依然 100% 互斥不重复！")

    # Verify global usage balance
    from collections import Counter
    all_used = [s.clip_sha256 for p in plans_15 for s in p.segments]
    counts = Counter(all_used)
    print(f"  素材全局调用频次统计: 最小={min(counts.values())} 次, 最大={max(counts.values())} 次")
    assert max(counts.values()) - min(counts.values()) <= 2, "全局素材调度应当高度平稳均衡，无极端倾斜"
    print("  [PASS] 全局调度算法完全平衡，每个素材使用频率近乎完全一致！")

    print("\n" + "=" * 70)
    print(">>> 10 条视频批量混剪不重复测试全部通过 (SUCCESS)!")
    print("=" * 70)


if __name__ == "__main__":
    test_batch_10_unique_openers()
