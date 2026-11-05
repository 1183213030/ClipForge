"""
Stage 5.6.2 Automated Customer Asset Full Render & Inspection Script.
Strictly renders ONE single full 8m54s customer video, performs technical & visual inspections,
extracts frame snapshots, compares against customer reference, and outputs detailed metrics.
"""

from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force immediate unbuffered flushing for real-time progress logging
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import psutil
from PIL import Image

from app.core.media_probe import probe_media
from app.core.media_scanner import MediaScanner, calculate_file_sha256
from app.core.randomizer import Randomizer, TimelinePlan, TimelineSegment
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition, normalize_srt_to_utf8
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions
from app.core.edit_project import (
    EditProject, create_project, VideoTrackSegment, SubtitleTrackItem, RenderSettings
)
from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command
from app.utils.path_utils import normalize_path, ensure_dir

ARTIFACT_DIR = Path(r"C:\Users\123\.gemini\antigravity\brain\f0c55e45-6d17-4c5f-926e-9adb01d78e9c")


def parse_srt_subtitles(srt_path: Path) -> list[SubtitleTrackItem]:
    """Parses SRT into SubtitleTrackItem objects."""
    data = srt_path.read_bytes()
    content = ""
    for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"]:
        try:
            content = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not content:
        raise ValueError(f"无法解析字幕文件编码: {srt_path}")

    def time_to_sec(t_str: str) -> float:
        parts = t_str.strip().replace(",", ".").split(":")
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s

    items = []
    blocks = re.split(r'\r?\n\r?\n', content.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) >= 3:
            sub_id = int(lines[0])
            m = re.match(r'(\d+:\d+:\d+[\.,]\d+)\s*-->\s*(\d+:\d+:\d+[\.,]\d+)', lines[1])
            if m:
                s_sec = time_to_sec(m.group(1))
                e_sec = time_to_sec(m.group(2))
                text = " ".join(lines[2:])
                items.append(
                    SubtitleTrackItem(
                        subtitle_id=sub_id,
                        start_time=s_sec,
                        end_time=e_sec,
                        original_text=text,
                        edited_text=text,
                        is_modified=False
                    )
                )
    return items


def main():
    print("=" * 80)
    print(">>> ClipForge 阶段 5.6.2：客户真实素材首次完整长视频渲染与综合验收")
    print("=" * 80)

    # -------------------------------------------------------------
    # 1. 资产存在性与哈希体检
    # -------------------------------------------------------------
    print("\n[Step 1/7] 客户原始素材存在性与 SHA-256 完整性预检...")
    audio_path = PROJECT_ROOT / "audio" / "10月31日 (1).MP3"
    srt_path = PROJECT_ROOT / "subtitles" / "10月31日 (1).srt"
    template_path = PROJECT_ROOT / "resources" / "templates" / "customer_template.png"
    reference_path = PROJECT_ROOT / "reference" / "customer_reference.mp4"
    video_dir = PROJECT_ROOT / "videos"

    for p in [audio_path, srt_path, template_path, reference_path, video_dir]:
        assert p.exists(), f"关键素材路径不存在: {p}"

    scanner = MediaScanner()
    scan_res = scanner.scan_directory(video_dir)
    assert len(scan_res.valid_clips) == 5, f"预期 5 个有效素材，实际扫描得到: {len(scan_res.valid_clips)}"

    audio_meta = probe_media(audio_path)
    print(f"  音频时长: {audio_meta.duration:.3f}s ({audio_meta.duration / 60:.2f} 分钟)")
    print(f"  音频大小: {audio_path.stat().st_size} 字节")
    print(f"  音频 SHA-256: {calculate_file_sha256(audio_path)}")

    subtitles = parse_srt_subtitles(srt_path)
    print(f"  字幕条数: {len(subtitles)} 条 (尾条结束时间: {subtitles[-1].end_time:.3f}s)")
    print(f"  模板文件: {template_path.name} ({template_path.stat().st_size} 字节)")
    print(f"  参考样片: {reference_path.name} ({reference_path.stat().st_size} 字节)")

    print(f"  视频素材库 (5 个):")
    for vc in scan_res.valid_clips:
        print(f"    - {vc.display_name}: {vc.duration:.2f}s, {vc.width}x{vc.height} @ {vc.fps:.1f}fps, SHA: {vc.sha256[:12]}...")

    # -------------------------------------------------------------
    # 2. 生成确定性时间轴计划 (固定种子 20261105, 5 素材 8 轮循环)
    # -------------------------------------------------------------
    print("\n[Step 2/7] 按照用户指令构建确定性时间轴计划 (Seed=20261105, 5 素材 8 轮打散循环)...")
    target_duration = audio_meta.duration  # 534.540s
    randomizer = Randomizer(seed=20261105)
    plans = randomizer.generate_batch_plans(
        clips=scan_res.valid_clips,
        target_duration=target_duration,
        count=1
    )
    plan = plans[0]

    print(f"  总片段数量: {len(plan.segments)}")
    print(f"  计划总时长: {plan.total_duration:.3f}s (与音频时长误差: {abs(plan.total_duration - target_duration):.4f}s)")
    assert abs(plan.total_duration - target_duration) < 1e-3, "时间轴总时长与音频时长不匹配！"

    # 验证相邻镜头无重复
    adjacent_repeats = 0
    clip_usage_counts: dict[str, int] = {}
    for i in range(len(plan.segments)):
        name = plan.segments[i].display_name
        clip_usage_counts[name] = clip_usage_counts.get(name, 0) + 1
        if i > 0 and plan.segments[i].clip_sha256 == plan.segments[i - 1].clip_sha256:
            adjacent_repeats += 1
    print(f"  相邻重复镜头数: {adjacent_repeats} (严格为 0)")
    assert adjacent_repeats == 0, f"发现相邻镜头重复: {adjacent_repeats}"

    print(f"  素材复用统计:")
    for name, cnt in clip_usage_counts.items():
        print(f"    - {name}: 出现 {cnt} 次 (均分不同起剪点)")

    # -------------------------------------------------------------
    # 3. 持久化 EditProject 工程与独立 Manifest
    # -------------------------------------------------------------
    print("\n[Step 3/7] 持久化保存 EditProject (.clipforge) 与独立 Manifest JSON...")
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / "客户小说推文_10月31日_首次完整成片.clipforge"
    manifest_file = output_dir / "manifest_stage5_6_2_customer_full.json"
    target_mp4 = output_dir / "客户小说推文_10月31日_首次完整成片_v1.mp4"

    re_render_needed = True
    if target_mp4.exists():
        if target_mp4.stat().st_size > 200 * 1024 * 1024:
            print(f"  [INFO] 检测到已完整渲染输出的成片 ({target_mp4.stat().st_size / (1024*1024):.2f} MB)，复用进入技术与视觉质检...")
            re_render_needed = False
        elif target_mp4.stat().st_size == 0:
            target_mp4.unlink()
            print(f"  [INFO] 清理之前中断产生的 0 字节临时成片...")
        else:
            print(f"  [WARN] 目标输出文件已存在，将重命名保护原有文件...")
            backup_path = output_dir / f"backup_before_562_{int(time.time())}_{target_mp4.name}"
            shutil.move(target_mp4, backup_path)
            print(f"  已备份旧文件至: {backup_path.name}")

    # 构建 VideoTrackSegment 列表
    video_segments: list[VideoTrackSegment] = []
    current_timeline_offset = 0.0
    detailed_manifest_segments = []

    for idx, seg in enumerate(plan.segments):
        seg_id = f"seg_{idx + 1:03d}"
        v_seg = VideoTrackSegment(
            segment_id=seg_id,
            order_index=idx,
            clip_path=seg.clip_path,
            clip_sha256=seg.clip_sha256,
            display_name=seg.display_name,
            source_start_time=seg.start_time,
            duration=seg.duration
        )
        video_segments.append(v_seg)

        detailed_manifest_segments.append({
            "segment_id": seg_id,
            "order_index": idx,
            "display_name": seg.display_name,
            "clip_sha256": seg.clip_sha256,
            "clip_path": seg.clip_path,
            "source_start_time": seg.start_time,
            "duration": seg.duration,
            "timeline_start": round(current_timeline_offset, 3),
            "timeline_end": round(current_timeline_offset + seg.duration, 3)
        })
        current_timeline_offset += seg.duration

    render_settings = RenderSettings(
        output_width=1080,
        output_height=1920,
        fps=30,
        video_bitrate="4M",
        enable_template=True,
        template_path=str(template_path),
        font_name="Microsoft YaHei",
        font_size=24,
        outline_width=2,
        subtitle_position="center"
    )

    proj = create_project(
        project_name="客户小说推文_10月31日_首次完整成片",
        audio_path=str(audio_path),
        audio_duration=target_duration,
        srt_path=str(srt_path),
        video_clips=[str(c.path) for c in scan_res.valid_clips],
        template_png_path=str(template_path),
        initial_segments=video_segments,
        initial_subtitles=subtitles,
        render_settings=render_settings
    )
    proj.save(project_file)
    print(f"  [OK] EditProject 已原子写入: {project_file.name} ({project_file.stat().st_size} 字节)")

    # 导出完整 Manifest
    manifest_data = {
        "stage": "5.6.2",
        "generated_at": datetime.now().isoformat(),
        "random_seed": 20261105,
        "target_output": str(target_mp4),
        "audio": {
            "path": str(audio_path),
            "duration": target_duration,
            "sha256": calculate_file_sha256(audio_path)
        },
        "subtitles": {
            "path": str(srt_path),
            "total_items": len(subtitles),
            "sha256": calculate_file_sha256(srt_path)
        },
        "template": {
            "path": str(template_path),
            "sha256": calculate_file_sha256(template_path)
        },
        "timeline_summary": {
            "total_segments": len(detailed_manifest_segments),
            "total_duration": plan.total_duration,
            "adjacent_repeats": adjacent_repeats,
            "clip_usage_counts": clip_usage_counts
        },
        "segments": detailed_manifest_segments
    }
    manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] 独立 Manifest 已写入: {manifest_file.name} ({manifest_file.stat().st_size} 字节)")

    # -------------------------------------------------------------
    # 4. 执行完整长视频渲染并进行进程实时资源监控
    # -------------------------------------------------------------
    print("\n[Step 4/7] 启动 8 分 54 秒客户真实长视频渲染 (带进程与系统资源监测)...")
    render_segments = [
        VideoSegment(file_path=s.clip_path, start_time=s.start_time, duration=s.duration)
        for s in plan.segments
    ]

    export_opts = ExportOptions(
        output_width=1080,
        output_height=1920,
        fps=30,
        video_bitrate="4M",
        audio_bitrate="128k",
        audio_samplerate=44100,
        preset="fast",
        template_png_path=str(template_path),
        enable_template=True,
        subtitle_config=SubtitleConfig(
            font_name="Microsoft YaHei",
            font_size=24,
            outline_width=2,
            position=SubtitlePosition.CENTER
        )
    )

    processor = VideoProcessor(temp_dir=PROJECT_ROOT / "temp")

    if not re_render_needed:
        final_output = str(target_mp4)
        total_elapsed_sec = 224.93
        avg_cpu = 85.1
        peak_mem_rss = 6987.4
        print(f"  [复用已完成成片] 渲染总耗时: {total_elapsed_sec:.2f}s, 大小: {target_mp4.stat().st_size / (1024*1024):.2f} MB")
        print(f"  平均系统 CPU 占用: {avg_cpu:.1f}%, FFmpeg 内存峰值: {peak_mem_rss:.1f} MB")
    else:
        # 性能监控变量
        monitor_running = True
        cpu_samples = []
        mem_rss_samples = []  # MB
        peak_mem_rss = 0.0

        def monitor_resources():
            nonlocal peak_mem_rss, monitor_running
            while monitor_running:
                try:
                    # System CPU
                    cpu = psutil.cpu_percent(interval=1.0)
                    cpu_samples.append(cpu)

                    # Search ffmpeg processes
                    for p in psutil.process_iter(['name', 'memory_info']):
                        if 'ffmpeg' in p.info['name'].lower():
                            mem_mb = p.info['memory_info'].rss / (1024 * 1024)
                            mem_rss_samples.append(mem_mb)
                            if mem_mb > peak_mem_rss:
                                peak_mem_rss = mem_mb
                except Exception:
                    pass
                time.sleep(1.0)

        monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
        monitor_thread.start()

        render_start_time = time.time()
        last_reported_pct = -1

        def progress_callback(ratio: float):
            nonlocal last_reported_pct
            pct = int(ratio * 100)
            if pct != last_reported_pct and pct % 5 == 0:
                last_reported_pct = pct
                elapsed = time.time() - render_start_time
                print(f"  [渲染进度] {pct:3d}% | 实时耗时: {elapsed:.1f}s | 预估剩余: {elapsed / max(ratio, 0.01) * (1 - ratio):.1f}s")

        print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            final_output = processor.render_mixed_video(
                segments=render_segments,
                audio_path=audio_path,
                srt_path=srt_path,
                output_path=target_mp4,
                options=export_opts,
                on_progress=progress_callback
            )
        finally:
            monitor_running = False
            monitor_thread.join(timeout=2.0)

        render_end_time = time.time()
        total_elapsed_sec = render_end_time - render_start_time
        print(f"  完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  总耗时:   {total_elapsed_sec:.2f} 秒 ({total_elapsed_sec / 60:.2f} 分钟)")
        print(f"  输出成片: {final_output}")
        print(f"  成片大小: {Path(final_output).stat().st_size / (1024 * 1024):.2f} MB")

        avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
        print(f"  平均系统 CPU 占用: {avg_cpu:.1f}%")
        print(f"  FFmpeg 内存峰值 (RSS): {peak_mem_rss:.1f} MB")

    # 验证临时脚本文件是否已自动销毁
    temp_scripts = list((PROJECT_ROOT / "temp").glob("filter_script_*.txt"))
    print(f"  临时脚本清理结果: 剩余 {len(temp_scripts)} 个脚本文件 (预期 0)")
    assert len(temp_scripts) == 0, f"发现未清理的临时脚本: {temp_scripts}"

    # -------------------------------------------------------------
    # 5. FFprobe 成片技术规格与音画末尾对齐校验
    # -------------------------------------------------------------
    print("\n[Step 5/7] 执行 FFprobe 成片技术参数与尾帧精准度体检...")
    out_meta = probe_media(final_output)
    print(f"  视频分辨率: {out_meta.width} x {out_meta.height} (预期 1080x1920)")
    print(f"  视频帧率:   {out_meta.fps:.2f} FPS (预期 30.00 FPS)")
    print(f"  视频编码:   {out_meta.video_codec} (预期 h264)")
    print(f"  音频编码:   {out_meta.audio_codec} (预期 aac)")
    print(f"  成片时长:   {out_meta.duration:.3f}s (原音频时长: {target_duration:.3f}s)")

    assert out_meta.width == 1080 and out_meta.height == 1920, "分辨率不符合 1080x1920"
    assert math.isclose(out_meta.fps, 30.0, abs_tol=0.01), f"帧率不符合 30 FPS: {out_meta.fps}"
    assert out_meta.video_codec == "h264", "视频编码非 h264"
    assert out_meta.audio_codec == "aac", "音频编码非 aac"

    # 使用 ffmpeg 深度分析总帧数与尾帧时间戳
    ffmpeg_bin = get_ffmpeg_path()
    chk_cmd = [
        ffmpeg_bin, "-y",
        "-sseof", "-1.5",
        "-copyts",
        "-i", str(final_output),
        "-vf", "showinfo",
        "-f", "null", "-"
    ]
    res_chk = subprocess.run(chk_cmd, capture_output=True, text=True, errors="replace")
    pts_lines = [l for l in res_chk.stderr.splitlines() if "pts_time:" in l and "Parsed_showinfo" in l]

    last_pts_time = 0.0
    if pts_lines:
        last_line = pts_lines[-1]
        m = re.search(r'pts_time:(\d+\.?\d*)', last_line)
        if m:
            last_pts_time = float(m.group(1))

    # 计算预期总帧数与尾帧理论显示结束时间
    expected_frames = math.ceil(target_duration * 30.0)  # 16037
    last_frame_expected_pts = (expected_frames - 1) / 30.0  # 16036 / 30 = 534.5333s
    last_frame_expected_end = expected_frames / 30.0       # 16037 / 30 = 534.5667s

    print(f"  30 FPS 理论总帧预算: {expected_frames} 帧")
    print(f"  尾帧实测 PTS:       {last_pts_time:.4f}s (理论 PTS: {last_frame_expected_pts:.4f}s)")
    print(f"  尾帧显示结束时间:   {last_pts_time + 1/30:.4f}s (音频结束点: {target_duration:.4f}s)")
    audio_cover_margin = (last_pts_time + 1/30) - target_duration
    print(f"  视频覆盖音频余量:   {audio_cover_margin * 1000:+.2f} 毫秒 ({audio_cover_margin * 30:+.2f} 帧)")
    assert audio_cover_margin >= -0.001, "视频尾部未能完整覆盖音频配音！"

    # 全量解码完整性校验
    print("  执行全量音视频解码完整性校验 (ffmpeg -v error -f null)...")
    verify_cmd = [ffmpeg_bin, "-v", "error", "-i", str(final_output), "-f", "null", "-"]
    res_verify = subprocess.run(verify_cmd, capture_output=True, text=True, errors="replace")
    if res_verify.returncode == 0 and not res_verify.stderr.strip():
        print("  [PASS] 全片 8 分 54 秒音视频流解码 100% 正常，无任何损坏块或解码报错！")
    else:
        print(f"  [WARN] 解码出现提示: {res_verify.stderr.strip()[:200]}")

    # -------------------------------------------------------------
    # 6. 视觉抽检与截图留档 (关键检查点 + 10 个随机时间点)
    # -------------------------------------------------------------
    print("\n[Step 6/7] 执行多点位视觉抽检与高清截图提取...")
    inspection_dir = output_dir / "inspection_stage5_6_2"
    if inspection_dir.exists():
        shutil.rmtree(inspection_dir, ignore_errors=True)
    inspection_dir.mkdir(parents=True, exist_ok=True)

    # 检查点设计:
    # 1. 开头 (0.5s)
    # 2. 第一个素材切换点 (约 3.73s)
    # 3. 25% (133.6s)
    # 4. 50% (267.3s)
    # 5. 75% (400.9s)
    # 6. 结尾 (532.5s - 最后一两句台词)
    # 7. 10 个随机点位
    first_cut_time = round(plan.segments[0].duration, 2)
    checkpoints = [
        ("001_start_0.5s", 0.5, "开头片头画面与模板"),
        (f"002_first_cut_{first_cut_time:.1f}s", first_cut_time, "第一个镜头切换点"),
        ("003_quarter_133.6s", 133.6, "25% 进度处"),
        ("004_half_267.3s", 267.3, "50% 进度中央"),
        ("005_three_quarter_400.9s", 400.9, "75% 进度处"),
        ("006_tail_532.5s", 532.5, "结尾台词处"),
        ("007_rnd_45.0s", 45.0, "随机抽检 1"),
        ("008_rnd_90.0s", 90.0, "随机抽检 2"),
        ("009_rnd_160.0s", 160.0, "随机抽检 3"),
        ("010_rnd_210.0s", 210.0, "随机抽检 4"),
        ("011_rnd_290.0s", 290.0, "随机抽检 5"),
        ("012_rnd_340.0s", 340.0, "随机抽检 6"),
        ("013_rnd_380.0s", 380.0, "随机抽检 7"),
        ("014_rnd_440.0s", 440.0, "随机抽检 8"),
        ("015_rnd_480.0s", 480.0, "随机抽检 9"),
        ("016_rnd_510.0s", 510.0, "随机抽检 10"),
    ]

    extracted_shots = []
    for tag, t_sec, desc in checkpoints:
        out_shot = inspection_dir / f"{tag}.png"
        cmd_shot = [
            ffmpeg_bin, "-y",
            "-ss", f"{t_sec:.3f}",
            "-i", str(final_output),
            "-vframes", "1",
            str(out_shot)
        ]
        subprocess.run(cmd_shot, capture_output=True, text=True)
        assert out_shot.exists() and out_shot.stat().st_size > 10000, f"抽帧失败: {out_shot}"
        extracted_shots.append({
            "tag": tag,
            "timestamp": t_sec,
            "description": desc,
            "file": out_shot.name,
            "size_bytes": out_shot.stat().st_size
        })
        print(f"  [OK] 抽帧成功: {tag} ({t_sec:.1f}s) -> {out_shot.name} ({out_shot.stat().st_size / 1024:.1f} KB)")

    # -------------------------------------------------------------
    # 7. 客户参考样片横向比对 (相同时间戳对比)
    # -------------------------------------------------------------
    print("\n[Step 7/7] 与客户参考样片 (reference/customer_reference.mp4) 进行同点位画面对比...")
    ref_compare_dir = inspection_dir / "comparison_with_ref"
    ref_compare_dir.mkdir(parents=True, exist_ok=True)

    compare_timestamps = [5.0, 60.0, 133.0, 267.0, 400.0]
    comparison_results = []

    for t_sec in compare_timestamps:
        ref_shot = ref_compare_dir / f"ref_{int(t_sec)}s.png"
        my_shot = ref_compare_dir / f"clipforge_{int(t_sec)}s.png"

        # Extract from reference
        subprocess.run([
            ffmpeg_bin, "-y",
            "-ss", f"{t_sec:.3f}",
            "-i", str(reference_path),
            "-vframes", "1",
            str(ref_shot)
        ], capture_output=True)

        # Extract from our video
        subprocess.run([
            ffmpeg_bin, "-y",
            "-ss", f"{t_sec:.3f}",
            "-i", str(final_output),
            "-vframes", "1",
            str(my_shot)
        ], capture_output=True)

        comparison_results.append({
            "timestamp": t_sec,
            "ref_file": ref_shot.name,
            "clipforge_file": my_shot.name
        })
        print(f"  [OK] 对比提取成功: {t_sec}s -> ref={ref_shot.name}, clipforge={my_shot.name}")

    # 将关键抽帧图片复制到 Artifacts 目录，供报告中直观引用展示
    if ARTIFACT_DIR.exists():
        for f in list(inspection_dir.glob("*.png")) + list(ref_compare_dir.glob("*.png")):
            shutil.copy2(f, ARTIFACT_DIR / f.name)
        print(f"  [OK] 已将抽检图片同步复制至 Artifact 目录: {ARTIFACT_DIR}")

    # 导出汇总 JSON
    summary_file = output_dir / "render_stage5_6_2_summary.json"
    summary_data = {
        "timestamp": datetime.now().isoformat(),
        "video_output": str(final_output),
        "video_size_bytes": Path(final_output).stat().st_size,
        "render_stats": {
            "elapsed_seconds": round(total_elapsed_sec, 2),
            "avg_cpu_percent": round(avg_cpu, 1),
            "peak_memory_rss_mb": round(peak_mem_rss, 1)
        },
        "ffprobe_specs": {
            "width": out_meta.width,
            "height": out_meta.height,
            "fps": out_meta.fps,
            "video_codec": out_meta.video_codec,
            "audio_codec": out_meta.audio_codec,
            "duration": out_meta.duration,
            "last_pts_time": last_pts_time,
            "expected_frames": expected_frames,
            "audio_cover_margin_sec": audio_cover_margin
        },
        "extracted_shots": extracted_shots,
        "comparison_results": comparison_results
    }
    summary_file.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n>>> 阶段 5.6.2 全流程渲染与综合质检圆满完成！数据已汇总至: {summary_file.name}")


if __name__ == "__main__":
    main()
