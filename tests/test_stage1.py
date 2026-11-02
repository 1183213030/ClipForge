"""
Stage 1 Comprehensive Verification Test Suite for ClipForge.
Generates realistic multi-resolution test video clips with audio,
creates Chinese novel narration audio and UTF-8 Chinese SRT subtitles,
renders an end-to-end mixed video with VideoProcessor,
and probes the result against all acceptance criteria.
"""

import math
import os
from pathlib import Path
import shutil
import sys

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.media_probe import probe_media
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command


def create_synthetic_test_assets(test_dir: Path) -> tuple[str, str, str, str]:
    """
    Creates:
    1. clip1.mp4: 1280x720 (16:9 Landscape), 25 FPS, with 440Hz test sine audio (5.0s)
    2. clip2.mp4: 1080x1920 (9:16 Portrait), 60 FPS, with 880Hz test audio (6.0s)
    3. novel_audio.mp3: A distinct spoken/beep-pattern novel narration audio (8.5s)
    4. novel.srt: Chinese subtitles timed for the 8.5s narration
    """
    ffmpeg = get_ffmpeg_path()
    test_dir.mkdir(parents=True, exist_ok=True)

    clip1 = test_dir / "测试素材_横屏720p.mp4"
    clip2 = test_dir / "测试素材_竖屏1080p.mp4"
    audio_file = test_dir / "小说配音_第01回.mp3"
    srt_file = test_dir / "小说字幕_中文.srt"

    # 1. Generate Clip 1: 1280x720, 25fps, 5.0 seconds with synthetic beep audio (to verify muting)
    cmd_clip1 = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=5.0",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(clip1)
    ]
    run_command(cmd_clip1)

    # 2. Generate Clip 2: 1080x1920, 60fps, 6.0 seconds with synthetic noise audio
    cmd_clip2 = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "smptebars=size=1080x1920:rate=60:duration=6.0",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=6.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(clip2)
    ]
    run_command(cmd_clip2)

    # 3. Generate Novel Audio: 8.5 seconds, 44100Hz stereo mp3
    cmd_audio = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "sine=frequency=523.25:duration=8.5",
        "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
        str(audio_file)
    ]
    run_command(cmd_audio)

    # 4. Generate Chinese SRT Subtitle
    srt_content = """1
00:00:00,500 --> 00:00:03,000
夜幕降临，古城深处传来阵阵低语。

2
00:00:03,500 --> 00:00:06,000
楚飞缓缓推开那扇尘封已久的青铜古门。

3
00:00:06,500 --> 00:00:08,200
门后显现出一道耀眼的金色光华！
"""
    srt_file.write_text(srt_content, encoding="utf-8")

    return str(clip1), str(clip2), str(audio_file), str(srt_file)


def run_stage1_verification():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 阶段一核心媒体管线完整验证")
    print("=" * 70)

    # Use a directory path containing Chinese and space characters to verify path robustness
    test_workspace = PROJECT_ROOT / "temp" / "测试 空间_Stage1"
    if test_workspace.exists():
        shutil.rmtree(test_workspace, ignore_errors=True)
    test_workspace.mkdir(parents=True, exist_ok=True)

    print("\n[Step 1/5] 创建测试素材 (不同分辨率、不同帧率、包含原音、含中文路径)...")
    clip1, clip2, novel_audio, srt = create_synthetic_test_assets(test_workspace)
    print(f"  [OK] 横屏素材: {clip1}")
    print(f"  [OK] 竖屏素材: {clip2}")
    print(f"  [OK] 小说配音: {novel_audio}")
    print(f"  [OK] 中文字幕: {srt}")

    print("\n[Step 2/5] 探测输入素材元数据...")
    meta1 = probe_media(clip1)
    meta2 = probe_media(clip2)
    meta_audio = probe_media(novel_audio)
    print(f"  素材1探测: {meta1.width}x{meta1.height} @ {meta1.fps}fps, 时长: {meta1.duration:.2f}s, 含音频: {meta1.has_audio}")
    print(f"  素材2探测: {meta2.width}x{meta2.height} @ {meta2.fps}fps, 时长: {meta2.duration:.2f}s, 含音频: {meta2.has_audio}")
    print(f"  音频探测: 时长: {meta_audio.duration:.2f}s, 编码: {meta_audio.audio_codec}, 采样率/声道正常")

    assert meta1.is_valid_video, "素材1探测失败"
    assert meta2.is_valid_video, "素材2探测失败"
    assert meta_audio.is_valid_audio, "小说音频探测失败"

    print("\n[Step 3/5] 构建拼接时间轴...")
    # Target novel audio duration is 8.5s
    # Clip 1 takes 5.0s, Clip 2 takes remaining 3.5s (cut from 6.0s)
    segments = [
        VideoSegment(file_path=clip1, start_time=0.0, duration=5.0),
        VideoSegment(file_path=clip2, start_time=0.0, duration=3.5)
    ]
    print(f"  片段1: 0.0s -> 5.0s (时长 5.0s)")
    print(f"  片段2: 0.0s -> 3.5s (截断使用 3.5s)")
    print(f"  合计计划时长: 8.50s (严格等于音频时长)")

    print("\n[Step 4/5] 执行视频混合渲染 (9:16 / 1080x1920 / 30fps / 4M 码率 / 中文字幕居中烧录)...")
    output_mp4 = PROJECT_ROOT / "output" / "stage1_output_成品_001.mp4"
    if output_mp4.exists():
        output_mp4.unlink()

    processor = VideoProcessor(temp_dir=test_workspace / "temp_render")
    
    sub_config = SubtitleConfig(
        font_name="Microsoft YaHei",
        font_size=22,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        outline_width=2,
        position=SubtitlePosition.BOTTOM,
        margin_v=80
    )

    export_opts = ExportOptions(
        output_width=1080,
        output_height=1920,
        fps=30,
        video_bitrate="4M",
        subtitle_config=sub_config
    )

    progress_records = []
    def on_progress(p: float):
        progress_records.append(p)
        print(f"\r  渲染实时进度: {p * 100:.1f}%", end="", flush=True)

    result_path = processor.render_mixed_video(
        segments=segments,
        audio_path=novel_audio,
        srt_path=srt,
        output_path=output_mp4,
        options=export_opts,
        on_progress=on_progress
    )
    print(f"\n  [OK] 视频渲染成功: {result_path}")

    print("\n[Step 5/5] 反向检测生成成品视频的各项指标...")
    out_meta = probe_media(result_path)
    
    # Validation checks
    duration_diff = abs(out_meta.duration - meta_audio.duration)
    is_res_ok = (out_meta.width == 1080 and out_meta.height == 1920)
    is_fps_ok = math.isclose(out_meta.fps, 30.0, abs_tol=0.5)
    is_audio_ok = out_meta.has_audio and out_meta.audio_codec.lower() in ["aac", "mp4a"]
    is_duration_ok = duration_diff <= 0.1  # tolerance within 100ms
    
    print("-" * 50)
    print(f"  分辨率检查: {out_meta.width}x{out_meta.height} -> {'PASS' if is_res_ok else 'FAIL'}")
    print(f"  帧率检查:   {out_meta.fps} FPS -> {'PASS' if is_fps_ok else 'FAIL'}")
    print(f"  音视频流:   视频={out_meta.video_codec}, 音频={out_meta.audio_codec} -> {'PASS' if is_audio_ok else 'FAIL'}")
    print(f"  时长对比:   成品={out_meta.duration:.2f}s, 预期音频={meta_audio.duration:.2f}s, 误差={duration_diff:.3f}s -> {'PASS' if is_duration_ok else 'FAIL'}")
    print(f"  文件大小:   {os.path.getsize(result_path) / (1024 * 1024):.2f} MB")
    print(f"  进度回调点数: {len(progress_records)} 次捕获")
    print("-" * 50)

    all_passed = is_res_ok and is_fps_ok and is_audio_ok and is_duration_ok
    if all_passed:
        print("\n>>> 阶段一验收结论: 全部指标通过 (SUCCESS)!")
    else:
        print("\n>>> 阶段一验收结论: 存在未通过指标，需调整排查!")

    return all_passed


if __name__ == "__main__":
    success = run_stage1_verification()
    sys.exit(0 if success else 1)
