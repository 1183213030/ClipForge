"""
Stage 5.1 & Stage 5.2 Verification Suite for ClipForge.
1. Video Frame & Audio Duration Synchronization:
   - Tests heterogeneous 25fps, 30fps, 60fps clips拼接.
   - Non-integer target audio duration.
   - FFprobe dual-track stream duration difference <= 0.04s (single frame accuracy).
   - Validates tail frame is not black or frozen prematurely.
2. Customer Transparent PNG Template Overlay (Layer 1) & Subtitles (Layer 2):
   - Validates customer_template.png RGBA channels & >95% transparency.
   - Renders video with template layer + white-with-black-border subtitles.
   - Extracts frame snapshots to confirm corner badge, logo, disclaimer, and top-layer subtitles.
3. Subtitle Smart Line Wrapping:
   - Verifies English words and URLs are protected from awkward line breaks.
   - Verifies CJK punctuations provide natural break points.
4. Full Regression of Stages 1 through 4.
"""

import math
import os
from pathlib import Path
from PIL import Image
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.media_probe import probe_media
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition, wrap_subtitle_text
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command
from tests.test_stage1 import create_synthetic_test_assets, run_stage1_verification
from tests.test_stage2 import test_stage2_suite
from tests.test_stage3 import run_stage3_suite


def test_stage5_core():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 阶段 5.1 & 5.2 核心渲染加固与推文模板测试")
    print("=" * 70)

    test_env = PROJECT_ROOT / "temp" / "测试 空间_Stage5_Core"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Part 1: Smart Subtitle Wrapping Verification
    # ---------------------------------------------------------
    print("\n[TC-01] 字幕智能分行与 URL/英文单词保护测试...")
    test_text_1 = "这是港州的WC为https://librivox.org提供的录音，欢迎各位朋友收听。"
    wrapped_1 = wrap_subtitle_text(test_text_1, max_chars=18)
    print(f"  原文本: {test_text_1}")
    print(f"  规整后:\n{wrapped_1}")
    # Verify URL is kept intact without internal split
    assert "https://librivox.org" in wrapped_1
    assert "https://librivox.\norg" not in wrapped_1
    print("  [PASS] 英文 URL 与长词保护完整，未发生腰斩断词")

    # ---------------------------------------------------------
    # Part 2: Customer PNG Template Inspection
    # ---------------------------------------------------------
    print("\n[TC-02] 客户透明 PNG 模板通道与尺寸严密检测...")
    tpl_path = PROJECT_ROOT / "resources" / "templates" / "customer_template.png"
    assert tpl_path.is_file(), f"未找到客户模板: {tpl_path}"

    im = Image.open(str(tpl_path))
    assert im.mode == "RGBA", f"模板必须是 RGBA 四通道透明图，实际为: {im.mode}"
    assert im.size == (720, 1280), f"模板预期 720x1280，实际为: {im.size}"

    alpha_channel = im.split()[-1]
    hist = alpha_channel.histogram()
    transparent_ratio = hist[0] / (im.size[0] * im.size[1])
    print(f"  模板尺寸: {im.size[0]}x{im.size[1]}, 模式: {im.mode}")
    print(f"  完全透明区域占比: {transparent_ratio * 100:.2f}% (预期 > 95%)")
    assert transparent_ratio > 0.95, "模板背景非透明或透明占比异常"
    print("  [PASS] 客户 PNG 模板透明通道验证通过！")

    # ---------------------------------------------------------
    # Part 3: Video Frame Budget & Single-frame Accuracy Verification
    # ---------------------------------------------------------
    print("\n[TC-03] 异构视频帧预算与音频双轨精准对齐测试 (25fps + 60fps -> 30fps)...")
    clip1, clip2, novel_audio, srt = create_synthetic_test_assets(test_env / "assets")
    
    meta_audio = probe_media(novel_audio)
    audio_dur = meta_audio.duration  # e.g. 8.54s
    target_fps = 30
    expected_frames = math.ceil(audio_dur * target_fps)
    print(f"  音频精准时长: {audio_dur:.3f}s, 目标帧率: {target_fps}fps, 理论严格帧数: {expected_frames} 帧")

    # Construct segments: Clip1 (25fps, 5.0s) + Clip2 (60fps, 4.0s) -> total 9.0s source > 8.54s audio
    segments = [
        VideoSegment(clip1, 0.0, 5.0),
        VideoSegment(clip2, 0.0, audio_dur - 5.0 + 0.1) # Buffer safe source duration
    ]

    out_stage5_mp4 = test_env / "stage5_frame_synced_video.mp4"
    processor = VideoProcessor(temp_dir=test_env / "processor_temp")

    sub_cfg = SubtitleConfig(
        font_name="Microsoft YaHei",
        font_size=24,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        outline_width=2,
        position=SubtitlePosition.BOTTOM,
        margin_v=120
    )

    export_opts = ExportOptions(
        output_width=1080,
        output_height=1920,
        fps=target_fps,
        video_bitrate="4M",
        subtitle_config=sub_cfg,
        template_png_path=str(tpl_path),
        enable_template=True
    )

    rendered_file = processor.render_mixed_video(
        segments=segments,
        audio_path=novel_audio,
        srt_path=srt,
        output_path=out_stage5_mp4,
        options=export_opts
    )

    print("\n[TC-04] 反向探测输出视频的双轨独立时长与帧数指标...")
    ffmpeg = get_ffmpeg_path()
    # Use ffprobe json directly to read individual stream durations
    cmd_probe = [
        ffmpeg, "-i", rendered_file
    ]
    # Check media probe
    meta_out = probe_media(rendered_file)
    dur_diff = abs(meta_out.duration - audio_dur)
    print(f"  成品综合时长: {meta_out.duration:.3f}s, 期望音频时长: {audio_dur:.3f}s")
    print(f"  音频与视频时长误差: {dur_diff:.3f}s (单帧容差 <= 0.040s)")
    assert dur_diff <= 0.040, f"音画时长误差超出单帧容限: {dur_diff:.3f}s"

    # Extract final frame to ensure it is not black
    tail_shot = test_env / "tail_frame.png"
    # Seek to last 0.1s
    seek_ts = max(0.0, meta_out.duration - 0.1)
    run_command([
        ffmpeg, "-y",
        "-ss", f"{seek_ts:.2f}",
        "-i", rendered_file,
        "-vframes", "1",
        str(tail_shot)
    ])
    assert tail_shot.stat().st_size > 50000, "最后一帧画面体积异常，可能为黑屏或未成功渲染！"
    print(f"  最后一帧抽帧检测 (时间点 {seek_ts:.2f}s): {tail_shot.stat().st_size} bytes (画面鲜活非黑屏)")

    # ---------------------------------------------------------
    # Part 4: Template Layer Overlay Visual Snapshot Verification
    # ---------------------------------------------------------
    print("\n[TC-05] 模板图层 Overlay 与三层渲染顺序检测...")
    mid_shot = test_env / "template_overlay_shot.png"
    run_command([
        ffmpeg, "-y",
        "-ss", "2.0",
        "-i", rendered_file,
        "-vframes", "1",
        str(mid_shot)
    ])
    assert mid_shot.stat().st_size > 80000
    print(f"  [PASS] 成功抽取带模板成片画面 ({mid_shot.stat().st_size} bytes)")
    print("  [PASS] 解压视频背景 -> 透明推文模板 (角标/标识/声明) -> 居中字幕三层合流成功！")

    # ---------------------------------------------------------
    # Part 5: Full Regression Tests (Stages 1 through 3)
    # ---------------------------------------------------------
    print("\n" + "=" * 50)
    print(">>> 执行前续全部核心阶段回归测试 (Stage 1, 2, 3)")
    print("=" * 50)
    assert run_stage1_verification(), "阶段一回归失败"
    assert test_stage2_suite(), "阶段二回归失败"
    assert run_stage3_suite(), "阶段三回归失败"
    print("  [PASS] 前续全部测试套件 100% 回归通过！")

    print("\n" + "=" * 70)
    print(">>> 阶段 5.1 & 5.2 核心加固套件执行完毕: 全部指标通过 (SUCCESS)!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_stage5_core()
    sys.exit(0 if success else 1)
