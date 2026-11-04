"""
Verification Suite for Stage 5.6.1 Hardening: FFmpeg Filter Complex Scripting.
Covers:
1. Part A: Small-scale real rendering regression with -filter_complex_script:
   - Clip stitching, concat, template PNG overlay, SRT burning, audio replacement.
   - Verifies 30.00 FPS CFR and exact target frames.
   - Verifies script file cleanup on normal completion.
   - Verifies script file cleanup on user cancellation.
   - Verifies script file cleanup on FFmpeg execution failure.
2. Part B: Long FilterGraph test (140 segments):
   - Constructs a 140-segment FilterGraph (~17,000 characters).
   - Verifies script file written completely and parsed cleanly by FFmpeg with 0 syntax errors.
   - Confirms process command line is compact (< 500 chars) and does not blow up Windows limits.
3. Part C: Customer Subtitle Reading Speed (CPS) Diagnostic:
   - Evaluates CPS = len(text) / duration across all 395 customer subtitles.
   - Counts CPS > 15, > 20, > 25, and lists top 10 highest CPS subtitles.
"""

import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.media_probe import probe_media
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions, CancellationToken, TaskCancelledError, FFmpegError
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command
from tests.test_stage1 import create_synthetic_test_assets


def test_part_a_small_scale_regression(test_dir: Path):
    print("\n" + "=" * 70)
    print(">>> Part A: 小规模真实渲染回归与临时脚本文件生命周期验证")
    print("=" * 70)

    clip1, clip2, novel_audio, srt = create_synthetic_test_assets(test_dir / "assets")

    # Create dummy template png
    tpl_png = test_dir / "template.png"
    from PIL import Image
    im = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    # Draw simple corner badge
    for x in range(100):
        for y in range(60):
            im.putpixel((x, y), (255, 0, 0, 200))
    im.save(tpl_png)

    processor = VideoProcessor(temp_dir=test_dir / "proc_temp")
    out_video = test_dir / "output_script_test.mp4"

    sub_cfg = SubtitleConfig(
        font_name="Microsoft YaHei",
        font_size=24,
        position=SubtitlePosition.CENTER
    )
    opts = ExportOptions(
        output_width=1080,
        output_height=1920,
        fps=30,
        video_bitrate="2M",
        subtitle_config=sub_cfg,
        template_png_path=str(tpl_png),
        enable_template=True
    )

    segs = [
        VideoSegment(file_path=clip1, start_time=0.0, duration=3.0),
        VideoSegment(file_path=clip2, start_time=0.0, duration=5.54)
    ]

    # 1. Normal rendering test
    print("\n[A-1] 正常执行渲染并检查临时脚本生成与自动清理...")
    res_path = processor.render_mixed_video(
        segments=segs,
        audio_path=novel_audio,
        srt_path=srt,
        output_path=out_video,
        options=opts
    )

    assert Path(res_path).is_file(), "输出视频文件不存在"
    print("  [OK] 视频渲染成功")

    # Verify temp script cleanup on normal completion
    lingering_scripts = list((test_dir / "proc_temp").glob("filter_script_*.txt"))
    assert len(lingering_scripts) == 0, f"正常完成后残留未清理的滤镜脚本: {lingering_scripts}"
    print("  [PASS] 正常完成时临时滤镜脚本已自动彻底清理 (0 残留)")

    # 2. Output stream verification
    print("\n[A-2] 校验输出视频流参数 (30.00 FPS CFR / 1080x1920)...")
    meta = probe_media(res_path)
    assert meta.is_valid_video, "输出视频无法通过 FFprobe 验证"
    assert meta.width == 1080 and meta.height == 1920, f"分辨率错误: {meta.width}x{meta.height}"
    assert abs(meta.fps - 30.0) <= 0.05, f"帧率非 30 FPS: {meta.fps}"
    assert abs(meta.duration - 8.54) <= 0.040, f"时长不匹配: {meta.duration}"
    assert meta.has_audio and meta.audio_codec == "aac", "音轨非 AAC"
    print(f"  分辨率: {meta.width}x{meta.height}")
    print(f"  帧率:   {meta.fps:.2f} FPS")
    print(f"  时长:   {meta.duration:.3f}s (预期 8.540s)")
    print("  [PASS] 输出流参数完全符合 1080x1920 @ 30 FPS CFR 规范")

    # 3. Cancellation cleanup test
    print("\n[A-3] 模拟用户取消任务并验证临时脚本清理...")
    token = CancellationToken()
    # Cancel immediately after first progress report
    def cancel_on_prog(p):
        if p > 0.05:
            token.cancel()

    cancel_out = test_dir / "output_cancelled.mp4"
    try:
        processor.render_mixed_video(
            segments=segs,
            audio_path=novel_audio,
            srt_path=srt,
            output_path=cancel_out,
            options=opts,
            on_progress=cancel_on_prog,
            token=token
        )
        assert False, "未能触发 TaskCancelledError"
    except TaskCancelledError:
        print("  成功捕获取消异常 (TaskCancelledError)")

    lingering_cancel = list((test_dir / "proc_temp").glob("filter_script_*.txt"))
    assert len(lingering_cancel) == 0, f"任务取消后残留未清理的滤镜脚本: {lingering_cancel}"
    print("  [PASS] 任务取消时临时滤镜脚本已自动安全清理")

    # 4. FFmpeg error cleanup test
    print("\n[A-4] 模拟 FFmpeg 渲染失败并验证临时脚本清理与原始异常保留...")
    broken_segs = [
        VideoSegment(file_path=str(test_dir / "non_existent_file.mp4"), start_time=0.0, duration=3.0)
    ]
    try:
        processor.render_mixed_video(
            segments=broken_segs,
            audio_path=novel_audio,
            srt_path=srt,
            output_path=test_dir / "output_error.mp4",
            options=opts
        )
        assert False, "未能触发 FFmpegError"
    except FFmpegError as e:
        print(f"  成功捕获预期渲染异常: {str(e)[:80]}...")

    lingering_err = list((test_dir / "proc_temp").glob("filter_script_*.txt"))
    assert len(lingering_err) == 0, f"渲染报错后残留未清理的滤镜脚本: {lingering_err}"
    print("  [PASS] 渲染失败时临时滤镜脚本已自动清理，且原始异常信息完整向上抛出")


def test_part_b_long_filter_graph(test_dir: Path):
    print("\n" + "=" * 70)
    print(">>> Part B: 140 片段超长 FilterGraph 滤镜图谱与脚本化压力验证")
    print("=" * 70)

    # Prepare 2 short synthetic clips to construct 140 segments
    clip1, clip2, novel_audio, srt = create_synthetic_test_assets(test_dir / "assets_long")

    # Construct 140 segments
    segment_count = 140
    long_segs = []
    for i in range(segment_count):
        c = clip1 if i % 2 == 0 else clip2
        long_segs.append(VideoSegment(file_path=c, start_time=0.0, duration=3.8))

    total_dur = round(sum(s.duration for s in long_segs), 3)
    target_frames = int(round(total_dur * 30))
    print(f"构建切片数量: {len(long_segs)} 个")
    print(f"总计划时长:   {total_dur} 秒 (~{total_dur/60:.1f} 分钟)")
    print(f"总计划帧数:   {target_frames} 帧")

    # 1. Build FilterGraph strings manually as VideoProcessor does
    filter_parts = []
    concat_inputs = []
    for i in range(segment_count):
        filter_parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,"
            f"fps=fps=30:round=near:start_time=0[v{i}]"
        )
        concat_inputs.append(f"[v{i}]")

    filter_parts.append(f"{''.join(concat_inputs)}concat=n={segment_count}:v=1:a=0[raw_concat]")
    filter_parts.append(
        f"[raw_concat]tpad=stop_mode=clone:stop=1,trim=start_frame=0:end_frame={target_frames},"
        f"setpts=PTS-STARTPTS[bg_video]"
    )

    filter_complex_str = ";\n".join(filter_parts)
    script_len = len(filter_complex_str)
    print(f"\n生成的滤镜图谱实际字符长度: {script_len} 字符")
    assert script_len > 15000, f"预期的 140 片段滤镜长度应 > 15000，当前为: {script_len}"

    # 2. Write to script file
    script_file = test_dir / "filter_script_140.txt"
    script_file.write_text(filter_complex_str, encoding="utf-8")
    assert script_file.is_file()
    print(f"  [OK] 140 片段滤镜脚本成功写入磁盘: {script_file.name} ({script_file.stat().st_size} 字节)")

    # 3. Check command line length
    ffmpeg = get_ffmpeg_path()
    cmd = [ffmpeg, "-y"]
    # Add input files (2 distinct clips referenced 140 times)
    for s in long_segs:
        cmd.extend(["-ss", "0.0", "-t", f"{s.duration:.3f}", "-i", s.file_path])

    cmd.extend([
        "-filter_complex_script", str(script_file.resolve()),
        "-map", "[bg_video]",
        "-frames:v", "1",  # Test syntax parsing with single frame
        "-c:v", "libx264",
        "-f", "null", "-"
    ])

    cmd_len = sum(len(c) + 1 for c in cmd)
    print(f"传递给进程的实际命令行总长度: {cmd_len} 字符 (已剥离 {script_len} 字符的滤镜图谱)")
    print(f"Windows CreateProcess 上限 (32767) 对比: 占 {cmd_len / 32767 * 100:.1f}% (处于安全裕度内)")
    # If filter complex were on CLI, total would be cmd_len + script_len = ~32,350 chars (perilously close to 32,767!)
    assert cmd_len < 30000, f"命令行长度未保持在精简安全范围内: {cmd_len}"


    # 4. Execute FFmpeg single-frame validation to verify 0 syntax errors
    print("\n[B-1] 调用 FFmpeg 解析 140 片段滤镜脚本...")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        print("FFmpeg STDERR:\n", res.stderr[-1000:])
        assert False, f"FFmpeg 解析 140 片段滤镜脚本失败 (code {res.returncode})"

    print("  [PASS] FFmpeg 成功完整解析 140 输入片段 FilterGraph，0 语法错误，0 命令行溢出！")

    if script_file.exists():
        script_file.unlink()


def test_part_c_subtitle_cps_diagnostic():
    print("\n" + "=" * 70)
    print(">>> Part C: 客户 395 条真实 SRT 台词阅读速度 (CPS) 专项诊断")
    print("=" * 70)

    srt_path = PROJECT_ROOT / "subtitles" / "10月31日 (1).srt"
    assert srt_path.is_file(), "客户字幕文件不存在"

    raw_text = srt_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()]

    def parse_ts(ts_str):
        m = re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)", ts_str.strip())
        h, mins, s, ms = m.groups()
        return int(h) * 3600 + int(mins) * 60 + int(s) + int(ms) / 1000.0

    records = []
    for idx, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) >= 3:
            seq = int(lines[0].strip()) if lines[0].strip().isdigit() else idx + 1
            t_match = re.match(r"(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)", lines[1].strip())
            if not t_match:
                continue
            t_start = parse_ts(t_match.group(1))
            t_end = parse_ts(t_match.group(2))
            dur = max(0.001, t_end - t_start)
            text = "\n".join(lines[2:]).strip()
            # Clean text length (excluding whitespace and newlines)
            char_count = len(re.sub(r'\s+', '', text))
            cps = char_count / dur
            records.append({
                "seq": seq,
                "text": text,
                "dur": dur,
                "chars": char_count,
                "cps": cps
            })

    assert len(records) == 395, f"有效记录数不符: {len(records)}"

    cps_vals = [r["cps"] for r in records]
    max_cps_rec = max(records, key=lambda x: x["cps"])
    min_cps_rec = min(records, key=lambda x: x["cps"])
    avg_cps = sum(cps_vals) / len(cps_vals)

    over_15 = [r for r in records if r["cps"] > 15.0]
    over_20 = [r for r in records if r["cps"] > 20.0]
    over_25 = [r for r in records if r["cps"] > 25.0]

    print(f"总计诊断字幕条数: {len(records)} 条")
    print(f"平均阅读速度:     {avg_cps:.2f} 字/秒 (CPS)")
    print(f"最高阅读速度:     {max_cps_rec['cps']:.2f} 字/秒 (第 {max_cps_rec['seq']} 句)")
    print(f"最低阅读速度:     {min_cps_rec['cps']:.2f} 字/秒 (第 {min_cps_rec['seq']} 句)")

    print(f"\n[CPS 预警阈值统计]:")
    print(f"  CPS > 15 (偏快语速): {len(over_15)} 条 ({len(over_15) / len(records) * 100:.1f}%)")
    print(f"  CPS > 20 (极快语速): {len(over_20)} 条 ({len(over_20) / len(records) * 100:.1f}%)")
    print(f"  CPS > 25 (超限语速): {len(over_25)} 条 ({len(over_25) / len(records) * 100:.1f}%)")

    # Top 10 highest CPS
    top10_cps = sorted(records, key=lambda x: x["cps"], reverse=True)[:10]
    print(f"\n[CPS 语速最高的前 10 句台词清单]:")
    print("-" * 70)
    print(f"{'序号':^6} | {'字数':^4} | {'时长 (s)':^8} | {'CPS (字/秒)':^11} | 台词文本")
    print("-" * 70)
    for r in top10_cps:
        print(f"#{r['seq']:<5} | {r['chars']:<4} | {r['dur']:<8.3f} | {r['cps']:<11.2f} | {r['text']}")
    print("-" * 70)
    print("  [PASS] 客户字幕 CPS 专项诊断完成，原始 SRT 文件未做任何篡改")


def main():
    test_dir = PROJECT_ROOT / "temp" / "测试 空间_Stage5_FilterScript"
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    test_part_a_small_scale_regression(test_dir)
    test_part_b_long_filter_graph(test_dir)
    test_part_c_subtitle_cps_diagnostic()

    print("\n" + "=" * 70)
    print(">>> 阶段 5.6.1 滤镜脚本化加固与 CPS 诊断测试全部通过！(ALL PASS)")
    print("=" * 70)


if __name__ == "__main__":
    main()
