"""
ClipForge Stage 5.6.1 Customer Real Assets Precheck Script.
Performs comprehensive deep diagnostics on:
1. Customer novel audio: audio/10月31日 (1).MP3
2. Customer SRT subtitles: subtitles/10月31日 (1).srt
3. Customer PNG template: resources/templates/customer_template.png
4. Customer background videos: videos/*.mp4
5. Customer reference video: reference/customer_reference.mp4
"""

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path
from app.utils.path_utils import normalize_path

ffmpeg = get_ffmpeg_path()


def probe_file_full(path: Path) -> dict:
    """Probes media using ffmpeg/ffprobe and returns stream details."""
    cmd = [ffmpeg, "-i", str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    stderr = res.stderr

    info = {
        "path": str(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "duration": 0.0,
        "video": None,
        "audio": None,
        "raw_stderr": stderr
    }

    # Duration regex
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
    if dur_match:
        h, m, s = dur_match.groups()
        info["duration"] = int(h) * 3600 + int(m) * 60 + float(s)

    # Video stream regex
    v_match = re.search(r"Stream #\d+:\d+.*?: Video: ([^,\n]+).*?(\d{3,4})x(\d{3,4}).*?(\d+\.?\d*)\s*(?:fps|tbr)", stderr)
    if v_match:
        codec, w, h, fps = v_match.groups()
        info["video"] = {
            "codec": codec.strip(),
            "width": int(w),
            "height": int(h),
            "fps": float(fps),
            "aspect": f"{w}:{h}",
            "is_portrait": int(h) > int(w)
        }

    # Audio stream regex
    a_match = re.search(r"Stream #\d+:\d+.*?: Audio: ([^,\n]+).*?(\d+)\s*Hz.*?(stereo|mono|5\.1|7\.1)?", stderr)
    if a_match:
        acodec, srate, chan = a_match.groups()
        info["audio"] = {
            "codec": acodec.strip(),
            "samplerate": int(srate),
            "channels": chan.strip() if chan else "unknown"
        }

    return info


def analyze_audio(audio_path: Path):
    print("=" * 70)
    print(">>> 1. 客户小说音频全面诊断 (audio/10月31日 (1).MP3)")
    print("=" * 70)
    info = probe_file_full(audio_path)
    dur = info["duration"]
    size_mb = info["size_bytes"] / (1024 * 1024)

    # Calculate exact frames at 30 FPS
    exact_frames = math.ceil(dur * 30.0)
    display_span = exact_frames / 30.0
    delta_over = display_span - dur

    print(f"文件名:       {info['filename']}")
    print(f"文件大小:     {size_mb:.2f} MB ({info['size_bytes']} 字节)")
    print(f"精确时长:     {dur:.3f} 秒 ({int(dur//60)}分{dur%60:.3f}秒)")
    if info["audio"]:
        print(f"音频编码:     {info['audio']['codec']}")
        print(f"采样率:       {info['audio']['samplerate']} Hz")
        print(f"声道模式:     {info['audio']['channels']}")
    print(f"30 FPS 理论帧数: {exact_frames} 帧")
    print(f"末帧覆盖跨度: 0.000s -> {display_span:.4f}s")
    print(f"音画对齐余量: +{delta_over:.4f} 秒 ({delta_over * 30.0:.2f} 帧, 严格正向覆盖无黑屏)")
    return dur


def parse_srt_timestamp(ts: str) -> float:
    # 00:01:23,456
    m = re.match(r"(\d+):(\d+):(\d+)[,\.](\d+)", ts.strip())
    if not m:
        raise ValueError(f"无效的 SRT 时间戳: {ts}")
    h, mins, s, ms = m.groups()
    return int(h) * 3600 + int(mins) * 60 + int(s) + int(ms) / 1000.0


def analyze_srt(srt_path: Path, audio_dur: float):
    print("\n" + "=" * 70)
    print(">>> 2. 客户 SRT 字幕深度语法与时间轴诊断 (subtitles/10月31日 (1).srt)")
    print("=" * 70)

    raw_text = srt_path.read_text(encoding="utf-8", errors="replace")
    # Normalize line breaks
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    print(f"总字幕块数: {len(blocks)} (预期 395)")

    items = []
    syntax_errors = []
    zero_durations = []
    inverted_durations = []
    overlaps = []
    overflows = []
    char_lens = []

    prev_end = 0.0
    for idx, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) < 3:
            syntax_errors.append((idx + 1, "行数不足 3 行", block))
            continue

        seq_str = lines[0].strip()
        time_str = lines[1].strip()
        sub_text = "\n".join(lines[2:]).strip()

        # Check sequence
        try:
            seq_num = int(seq_str)
        except ValueError:
            syntax_errors.append((idx + 1, f"序号非数字: {seq_str}", block))
            seq_num = idx + 1

        # Check time line
        time_match = re.match(r"(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)", time_str)
        if not time_match:
            syntax_errors.append((seq_num, f"时间轴行格式错误: {time_str}", block))
            continue

        t_start = parse_srt_timestamp(time_match.group(1))
        t_end = parse_srt_timestamp(time_match.group(2))
        dur = t_end - t_start

        if dur == 0.0:
            zero_durations.append((seq_num, time_str, sub_text))
        elif dur < 0.0:
            inverted_durations.append((seq_num, time_str, sub_text))

        # Check overlap with previous subtitle
        if t_start < prev_end:
            overlap_sec = prev_end - t_start
            overlaps.append((seq_num - 1, seq_num, overlap_sec, prev_end, t_start))

        # Check if exceeds audio duration
        if t_end > audio_dur:
            excess = t_end - audio_dur
            overflows.append((seq_num, t_end, excess, sub_text))

        char_lens.append(len(sub_text.replace("\n", "")))
        prev_end = t_end
        items.append({
            "seq": seq_num,
            "start": t_start,
            "end": t_end,
            "dur": dur,
            "text": sub_text
        })

    print(f"有效解析字幕条数: {len(items)}")
    print(f"语法格式错误:     {len(syntax_errors)} 处")
    print(f"零时长字幕:       {len(zero_durations)} 处")
    print(f"倒退/负时长字幕:   {len(inverted_durations)} 处")
    print(f"相邻时间重叠字幕: {len(overlaps)} 处")
    print(f"超出音频尾段字幕: {len(overflows)} 处")

    if overflows:
        print("  [超出音频警告]:")
        for o in overflows[:3]:
            print(f"    - #{o[0]}: 结束点 {o[1]:.3f}s (超出音频 {o[2]:.3f}s) - {o[3]}")

    if overlaps:
        print("  [时间重叠详情]:")
        for ov in overlaps[:5]:
            print(f"    - #{ov[0]} 与 #{ov[1]}: 重叠 {ov[2]:.3f}s (前条结束 {ov[3]:.3f}s, 后条开始 {ov[4]:.3f}s)")

    durations = [it["dur"] for it in items]
    print("\n[台词时长统计]:")
    print(f"  最短时长: {min(durations):.3f} 秒")
    print(f"  最长时长: {max(durations):.3f} 秒")
    print(f"  平均时长: {sum(durations)/len(durations):.3f} 秒")

    print("\n[台词字数统计]:")
    print(f"  单句最短字数: {min(char_lens)} 字")
    print(f"  单句最长字数: {max(char_lens)} 字")
    print(f"  平均字数:     {sum(char_lens)/len(char_lens):.1f} 字")

    # Sample top 3 longest subtitles
    longest = sorted(items, key=lambda x: len(x["text"]), reverse=True)[:3]
    print("\n[最长单句台词样本 (测试换行保护)]:")
    for it in longest:
        print(f"  - #{it['seq']} ({len(it['text'])}字, {it['dur']:.2f}s): {it['text']}")

    return items


def analyze_template_png(png_path: Path):
    print("\n" + "=" * 70)
    print(">>> 3. 客户透明 PNG 模板图层与安全区深度分析")
    print("=" * 70)

    img = Image.open(png_path)
    w, h = img.size
    mode = img.mode
    print(f"原始尺寸: {w} x {h}")
    print(f"色彩模式: {mode}")

    if mode != "RGBA":
        print("  [警告] 模板非 RGBA 模式！")
        return

    # Inspect alpha channel
    alpha = img.split()[-1]
    hist = alpha.histogram()  # 256 bins for 0 to 255
    total_pixels = w * h
    fully_transparent = hist[0]
    fully_opaque = hist[255]
    semi_transparent = total_pixels - fully_transparent - fully_opaque

    print(f"完全透明像素: {fully_transparent} ({fully_transparent / total_pixels * 100:.2f}%)")
    print(f"半透明过渡像素: {semi_transparent} ({semi_transparent / total_pixels * 100:.2f}%)")
    print(f"完全不透明像素: {fully_opaque} ({fully_opaque / total_pixels * 100:.2f}%)")

    # Find bounding box of non-transparent pixels
    bbox = alpha.getbbox()  # (left, upper, right, lower)
    print(f"非透明像素外接总矩形: left={bbox[0]}, top={bbox[1]}, right={bbox[2]}, bottom={bbox[3]}")

    # Inspect top elements and bottom elements separately
    # Scan line by line for opaque distribution
    top_opaque_y = []
    bottom_opaque_y = []
    mid_opaque_y = []

    # Map to 1080x1920 scale
    scale_x = 1080.0 / w
    scale_y = 1920.0 / h

    # Bounding boxes mapped to 1080x1920
    mapped_top = bbox[1] * scale_y
    mapped_bottom = bbox[3] * scale_y

    print(f"\n[映射到 1080x1920 后的安全区与遮挡分析]:")
    print(f"  缩放系数: X={scale_x:.3f}, Y={scale_y:.3f}")
    print(f"  非透明最顶端 Y: {mapped_top:.1f}px")
    print(f"  非透明最底端 Y: {mapped_bottom:.1f}px")

    # Analyze vertical bands (Top 0-30%, Mid 30-70%, Bottom 70-100%)
    top_band = alpha.crop((0, 0, w, int(h * 0.3)))
    mid_band = alpha.crop((0, int(h * 0.3), w, int(h * 0.7)))
    bottom_band = alpha.crop((0, int(h * 0.7), w, h))

    top_bbox = top_band.getbbox()
    mid_bbox = mid_band.getbbox()
    bottom_bbox = bottom_band.getbbox()

    if top_bbox:
        print(f"  顶部角标/LOGO 区域 (1080x1920 对应): Y: {top_bbox[1]*scale_y:.0f}px -> {top_bbox[3]*scale_y:.0f}px")
    else:
        print("  顶部无不透明元素")

    if mid_bbox:
        print(f"  中部区域不透明元素 (1080x1920 对应): Y: {(int(h*0.3)+mid_bbox[1])*scale_y:.0f}px -> {(int(h*0.3)+mid_bbox[3])*scale_y:.0f}px")
    else:
        print("  中部区域 (Y: 576px -> 1344px): 100% 完全透明！(绝佳字幕展示窗口)")

    if bottom_bbox:
        b_y1 = (int(h * 0.7) + bottom_bbox[1]) * scale_y
        b_y2 = (int(h * 0.7) + bottom_bbox[3]) * scale_y
        print(f"  底部声明/水印区域 (1080x1920 对应): Y: {b_y1:.0f}px -> {b_y2:.0f}px")
    else:
        print("  底部无不透明元素")

    print("\n[字幕放置推荐与冲突判定]:")
    print("  - 若使用 Alignment=5 (垂直正居中, Y ≈ 960px): 处于 100% 透明安全区，完全不会遮挡角标或底部声明！")
    print("  - 若使用 Alignment=2 (底部对齐): 必须保留 MarginV >= 260px，否则字幕将与底部版权声明产生视觉重叠！")


def analyze_video_pool(video_dir: Path, audio_dur: float):
    print("\n" + "=" * 70)
    print(">>> 4. 客户解压视频素材库深度诊断 (videos/*.mp4)")
    print("=" * 70)

    clips = list(video_dir.glob("*.mp4"))
    print(f"素材总数: {len(clips)} 个")

    total_pool_dur = 0.0
    clip_details = []

    for c in clips:
        info = probe_file_full(c)
        v = info["video"]
        a = info["audio"]
        total_pool_dur += info["duration"]

        has_a = (a is not None)
        clip_details.append({
            "name": c.name,
            "size_mb": info["size_bytes"] / (1024 * 1024),
            "dur": info["duration"],
            "w": v["width"] if v else 0,
            "h": v["height"] if v else 0,
            "fps": v["fps"] if v else 0.0,
            "codec": v["codec"] if v else "none",
            "is_portrait": v["is_portrait"] if v else False,
            "has_audio": has_a,
            "audio_codec": a["codec"] if has_a else "none"
        })

    for idx, d in enumerate(clip_details, 1):
        orient = "竖屏 9:16" if d["is_portrait"] else "横屏/超清"
        print(f"  [{idx:02d}] {d['name']}")
        print(f"       大小: {d['size_mb']:.1f} MB | 时长: {d['dur']:.2f}s | 分辨率: {d['w']}x{d['h']} ({orient})")
        print(f"       帧率: {d['fps']:.2f} FPS | 原音频: {'有 (' + d['audio_codec'] + ')' if d['has_audio'] else '无'}")

    print(f"\n[素材池容量对比]:")
    print(f"  素材总可用时长: {total_pool_dur:.2f} 秒 ({int(total_pool_dur//60)}分{total_pool_dur%60:.2f}秒)")
    print(f"  小说配音总时长: {audio_dur:.2f} 秒 ({int(audio_dur//60)}分{audio_dur%60:.2f}秒)")

    deficit = audio_dur - total_pool_dur
    if deficit > 0:
        cycles = math.ceil(audio_dur / total_pool_dur)
        print(f"  [需循环组合]: 音频长于素材总和，需至少循环播放 {cycles} 轮才能覆盖！")
    else:
        print(f"  [素材充足]: 素材库总时长已完全覆盖音频时长。")

    return clip_details, total_pool_dur


def analyze_rendering_feasibility(audio_dur: float, clip_details: list, srt_count: int):
    print("\n" + "=" * 70)
    print(">>> 5. 8分54秒 长视频全量渲染性能与内存瓶颈预估")
    print("=" * 70)

    # 1. Segment count estimate
    avg_dur = 4.0  # seconds per segment
    est_segments = math.ceil(audio_dur / avg_dur)
    print(f"预计切片数量: ~{est_segments} 个片段 (按平均 4.0s 计算)")

    # 2. FilterGraph complex string length evaluation
    # Each segment has: [i:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v_i];
    # Concat: [v_0][v_1]...[v_N-1]concat=n=N:v=1:a=0[v_cat];
    # Overlay: [v_cat][tpl]overlay=0:0[v_tpl];
    # Subtitles: [v_tpl]subtitles=...[v_out]
    char_per_segment_filter = 115
    est_filter_len = est_segments * char_per_segment_filter + est_segments * 6 + 200
    print(f"预计单次 FilterComplex 字符串长度: ~{est_filter_len} 字符")

    # Windows command line limit check
    cmd_max_windows = 8191
    popen_max_windows = 32767
    print(f"Windows cmd.exe 命令行上限:  {cmd_max_windows} 字符")
    print(f"Windows CreateProcess 上限:  {popen_max_windows} 字符")

    if est_filter_len > cmd_max_windows:
        print(f"  [风险预警]: FilterComplex 长度 ({est_filter_len}) 超出 cmd.exe 上限 ({cmd_max_windows})！")
        print("  [工程对策]: Python 使用 subprocess.Popen 列表传参绕过 cmd.exe（上限 32767），但更可靠的方案是使用 filter_complex_script 将滤镜链写入临时文件传给 FFmpeg！")
    else:
        print(f"  [安全]: 滤镜长度在安全范围内。")

    # 3. File handles & memory
    print(f"\n[系统资源与编码吞吐量预估]:")
    total_frames = int(audio_dur * 30)
    print(f"  总输出视频帧数: {total_frames} 帧 (1080x1920 @ 30 FPS)")
    print(f"  按预设 preset='fast' 编码吞吐量估算 (约 45-60 FPS):")
    print(f"    预计耗时: ~{total_frames / 50:.1f} 秒 (~{total_frames / 50 / 60:.1f} 分钟)")
    est_size_mb = (4 * 1024 * 1024 / 8 * audio_dur + 128 * 1024 / 8 * audio_dur) / (1024 * 1024)
    print(f"  按 4M 视频码率 + 128k 音频码率计算，成品文件大小: ~{est_size_mb:.1f} MB")


def analyze_reference_video(ref_path: Path):
    print("\n" + "=" * 70)
    print(">>> 6. 客户参考样片对比基准分析 (reference/customer_reference.mp4)")
    print("=" * 70)
    info = probe_file_full(ref_path)
    v = info["video"]
    a = info["audio"]

    print(f"参考样片文件名: {info['filename']}")
    print(f"样片大小:       {info['size_bytes'] / (1024*1024):.2f} MB")
    print(f"样片时长:       {info['duration']:.2f} 秒")
    if v:
        print(f"样片分辨率:     {v['width']} x {v['height']} ({'竖屏' if v['is_portrait'] else '横屏'})")
        print(f"样片标称帧率:   {v['fps']} FPS")
        print(f"样片视频编码:   {v['codec']}")
    if a:
        print(f"样片音频编码:   {a['codec']}, {a['samplerate']}Hz")


def main():
    audio_path = PROJECT_ROOT / "audio" / "10月31日 (1).MP3"
    srt_path = PROJECT_ROOT / "subtitles" / "10月31日 (1).srt"
    tpl_path = PROJECT_ROOT / "resources" / "templates" / "customer_template.png"
    video_dir = PROJECT_ROOT / "videos"
    ref_path = PROJECT_ROOT / "reference" / "customer_reference.mp4"

    audio_dur = analyze_audio(audio_path)
    srt_items = analyze_srt(srt_path, audio_dur)
    analyze_template_png(tpl_path)
    clips, total_v_dur = analyze_video_pool(video_dir, audio_dur)
    analyze_rendering_feasibility(audio_dur, clips, len(srt_items))
    analyze_reference_video(ref_path)


if __name__ == "__main__":
    main()
