"""
Stage 5.3 Verification Suite for ClipForge: EditProject & Re-export Pipeline.

Covers 12 comprehensive test scenarios:
1. TC-01: Project creation (create_project) with full metadata and tracks.
2. TC-02: Project serialization & deserialization (save / load) deep equality.
3. TC-03: Robust handling of Chinese characters and spaces in file paths.
4. TC-04: Asset integrity validation (validate_assets) and re-linking (recover_missing_asset).
5. TC-05: Timeline segment reordering and persistence across reload.
6. TC-06: Segment duration adjustment and automatic tail-balancing logic.
7. TC-07: Subtitle modification (text & timing) and export to valid SRT.
8. TC-08: Render and template settings persistence.
9. TC-09: Corrupted JSON handling (safe ProjectError raise).
10. TC-10: Schema version migration and backward compatibility fallbacks.
11. TC-11: Atomic save safety (preserves original file on write error).
12. TC-12: Deterministic TimelinePlan generation (bypasses randomizer).
"""

import json
import os
from pathlib import Path
import shutil
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.edit_project import (
    EditProject,
    ProjectMeta,
    RawAssetManifest,
    VideoTrackSegment,
    SubtitleTrackItem,
    RenderSettings,
    ExportHistoryRecord,
    ProjectError,
    AssetMissingError,
    create_project,
    SCHEMA_VERSION
)
from app.utils.path_utils import normalize_path


def run_stage5_project_suite():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 阶段 5.3 EditProject 数据模型与工程重导测试")
    print("=" * 70)

    test_dir = PROJECT_ROOT / "temp" / "测试 空间_Stage5_Project"
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Prepare dummy assets
    audio_file = test_dir / "测试 音频 [小说].mp3"
    audio_file.write_text("dummy audio", encoding="utf-8")
    srt_file = test_dir / "测试 字幕 [双语].srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\n初始字幕\n", encoding="utf-8")
    template_png = test_dir / "遮罩 模板 [水印].png"
    template_png.write_text("dummy png", encoding="utf-8")

    clip1 = test_dir / "素材 01 [4K].mp4"
    clip2 = test_dir / "素材 02 [1080P].mp4"
    clip3 = test_dir / "素材 03 [60FPS].mp4"
    for c in [clip1, clip2, clip3]:
        c.write_text("dummy video", encoding="utf-8")

    # ---------------------------------------------------------
    # TC-01: Project creation
    # ---------------------------------------------------------
    print("\n[TC-01] 项目创建 (create_project) 与元数据初始化...")
    seg1 = VideoTrackSegment(
        segment_id="seg_001",
        order_index=0,
        clip_path=str(clip1),
        clip_sha256="sha256_111",
        display_name=clip1.name,
        source_start_time=0.0,
        duration=3.0
    )
    seg2 = VideoTrackSegment(
        segment_id="seg_002",
        order_index=1,
        clip_path=str(clip2),
        clip_sha256="sha256_222",
        display_name=clip2.name,
        source_start_time=0.0,
        duration=4.0
    )
    seg3 = VideoTrackSegment(
        segment_id="seg_003",
        order_index=2,
        clip_path=str(clip3),
        clip_sha256="sha256_333",
        display_name=clip3.name,
        source_start_time=0.0,
        duration=3.0
    )
    sub1 = SubtitleTrackItem(
        subtitle_id=1,
        start_time=0.0,
        end_time=2.5,
        original_text="第一句台词",
        edited_text="第一句台词"
    )
    sub2 = SubtitleTrackItem(
        subtitle_id=2,
        start_time=2.5,
        end_time=5.0,
        original_text="第二句台词",
        edited_text="第二句台词"
    )

    proj = create_project(
        project_name="测试项目_V1",
        audio_path=str(audio_file),
        audio_duration=10.0,
        srt_path=str(srt_file),
        video_clips=[str(clip1), str(clip2), str(clip3)],
        template_png_path=str(template_png),
        initial_segments=[seg1, seg2, seg3],
        initial_subtitles=[sub1, sub2]
    )

    assert proj.meta.project_name == "测试项目_V1"
    assert proj.meta.schema_version == SCHEMA_VERSION
    assert len(proj.video_track) == 3
    assert len(proj.subtitle_track) == 2
    assert proj.assets.audio_duration == 10.0
    print("  [PASS] 项目创建成功，元数据、资产清单、视频轨、字幕轨初始化完备")

    # ---------------------------------------------------------
    # TC-02 & TC-03: Save, Reload & Chinese / Space Paths
    # ---------------------------------------------------------
    print("\n[TC-02 & TC-03] 中文与空格路径序列化保存与重新加载 (Save & Load)...")
    proj_save_path = test_dir / "工程 文件 存档 [备份].clipforge"
    proj.save(proj_save_path)
    assert proj_save_path.is_file(), "工程文件未成功写入磁盘"

    loaded_proj = EditProject.load(proj_save_path)
    assert loaded_proj.meta.project_id == proj.meta.project_id
    assert loaded_proj.meta.project_name == "测试项目_V1"
    assert len(loaded_proj.video_track) == 3
    assert loaded_proj.video_track[0].display_name == clip1.name
    assert loaded_proj.video_track[1].clip_sha256 == "sha256_222"
    assert len(loaded_proj.subtitle_track) == 2
    assert loaded_proj.assets.template_png_path == normalize_path(str(template_png))
    print("  [PASS] 中文/空格路径支持良好，JSON 完整反序列化且数据字段完全一致")

    # ---------------------------------------------------------
    # TC-04: Asset Validation & Path Recovery
    # ---------------------------------------------------------
    print("\n[TC-04] 资产完整性校验 (validate_assets) 与丢失恢复 (recover_missing_asset)...")
    missing = loaded_proj.validate_assets()
    assert len(missing) == 0, f"意外的素材丢失: {missing}"

    # Simulate clip2 moving / renaming
    new_clip2 = test_dir / "重命名后的 素材 02.mp4"
    clip2.rename(new_clip2)

    missing_after_rename = loaded_proj.validate_assets()
    assert len(missing_after_rename) == 1
    assert missing_after_rename[0] == normalize_path(str(clip2))
    print(f"  成功检出丢失素材: {Path(missing_after_rename[0]).name}")

    # Recover asset link
    loaded_proj.recover_missing_asset(str(clip2), str(new_clip2))
    assert len(loaded_proj.validate_assets()) == 0
    assert loaded_proj.video_track[1].clip_path == normalize_path(str(new_clip2))
    assert loaded_proj.video_track[1].display_name == new_clip2.name
    print("  [PASS] 成功重定位丢失素材，项目资产校验恢复正常")

    # ---------------------------------------------------------
    # TC-05: Timeline Segment Reordering
    # ---------------------------------------------------------
    print("\n[TC-05] 视频片段顺序调整与持久化 (reorder_segments)...")
    # Original order: seg_001, seg_002, seg_003
    loaded_proj.reorder_segments(["seg_003", "seg_001", "seg_002"])
    assert [s.segment_id for s in loaded_proj.video_track] == ["seg_003", "seg_001", "seg_002"]
    assert [s.order_index for s in loaded_proj.video_track] == [0, 1, 2]

    # Audio duration and subtitle timestamps MUST remain unchanged
    assert loaded_proj.assets.audio_duration == 10.0
    assert loaded_proj.subtitle_track[0].start_time == 0.0

    loaded_proj.save(proj_save_path)
    reloaded_proj = EditProject.load(proj_save_path)
    assert [s.segment_id for s in reloaded_proj.video_track] == ["seg_003", "seg_001", "seg_002"]
    print("  [PASS] 片段重排序成功，独立音轨与字幕轨毫秒未动，重载后顺序严格保留")

    # ---------------------------------------------------------
    # TC-06: Segment Duration Adjustment & Tail Balancing
    # ---------------------------------------------------------
    print("\n[TC-06] 片段时长微调与尾部自适应对齐 (update_segment_duration)...")
    # Total audio duration is 10.0.
    # Current track: seg_003 (3.0s), seg_001 (3.0s), seg_002 (4.0s). Total = 10.0s.
    # Now change seg_003 to 5.0s.
    reloaded_proj.update_segment_duration("seg_003", 5.0)
    assert reloaded_proj.video_track[0].duration == 5.0
    assert reloaded_proj.video_track[1].duration == 3.0
    # Tail segment seg_002 should automatically balance to 10.0 - (5.0 + 3.0) = 2.0s
    assert reloaded_proj.video_track[2].duration == 2.0
    total_dur = sum(s.duration for s in reloaded_proj.video_track)
    assert total_dur >= reloaded_proj.assets.audio_duration
    print(f"  更新后片段时长序列: {[s.duration for s in reloaded_proj.video_track]}, 总时长: {total_dur}s")
    print("  [PASS] 尾部片段自适应填平音频时长，保证无黑屏或音频截断")

    # ---------------------------------------------------------
    # TC-07: Subtitle Modification & SRT Export
    # ---------------------------------------------------------
    print("\n[TC-07] 字幕文本与时间戳修改 (edit_subtitle_text / timing) 及 SRT 导出...")
    reloaded_proj.edit_subtitle_text(1, "修改后的第一句精选台词！")
    assert reloaded_proj.subtitle_track[0].is_modified is True
    assert reloaded_proj.subtitle_track[0].edited_text == "修改后的第一句精选台词！"

    reloaded_proj.edit_subtitle_timing(1, 0.2, 2.8)
    assert reloaded_proj.subtitle_track[0].start_time == 0.2
    assert reloaded_proj.subtitle_track[0].end_time == 2.8

    out_srt = test_dir / "导出的修改字幕.srt"
    reloaded_proj.export_edited_srt_file(out_srt)
    assert out_srt.is_file()
    srt_content = out_srt.read_text(encoding="utf-8")
    assert "00:00:00,200 --> 00:00:02,800" in srt_content
    assert "修改后的第一句精选台词！" in srt_content
    print("  [PASS] 字幕内容与时间轴独立修改成功，导出的 SRT 符合 FFmpeg 渲染规范")

    # ---------------------------------------------------------
    # TC-08: Render Settings & History Records
    # ---------------------------------------------------------
    print("\n[TC-08] 渲染配置与导出历史记录持久化...")
    reloaded_proj.render_settings.output_width = 1080
    reloaded_proj.render_settings.output_height = 1920
    reloaded_proj.render_settings.fps = 30
    reloaded_proj.render_settings.subtitle_position = "bottom"
    reloaded_proj.render_settings.font_size = 28
    reloaded_proj.render_settings.primary_color = "&H0000FFFF"  # Yellow

    reloaded_proj.add_export_history(
        output_path=str(test_dir / "output_v1.mp4"),
        status="SUCCESS",
        elapsed=12.4
    )
    reloaded_proj.add_export_history(
        output_path=str(test_dir / "output_v2.mp4"),
        status="SUCCESS",
        elapsed=11.8
    )

    reloaded_proj.save(proj_save_path)
    final_proj = EditProject.load(proj_save_path)
    assert final_proj.render_settings.subtitle_position == "bottom"
    assert final_proj.render_settings.font_size == 28
    assert final_proj.render_settings.primary_color == "&H0000FFFF"
    assert len(final_proj.export_history) == 2
    assert final_proj.export_history[0].version == 1
    assert final_proj.export_history[1].version == 2
    print("  [PASS] 渲染配置与导出版本历史持久化无损存储")

    # ---------------------------------------------------------
    # TC-09: Corrupted JSON Handling
    # ---------------------------------------------------------
    print("\n[TC-09] 损坏的工程文件防御性解析 (Corrupted JSON)...")
    corrupt_file = test_dir / "损坏的工程.clipforge"
    corrupt_file.write_text("{ \"meta\": { invalid_json...", encoding="utf-8")

    try:
        EditProject.load(corrupt_file)
        assert False, "未能捕获损坏的 JSON 异常"
    except ProjectError as e:
        print(f"  正确捕获预期异常: {e}")
        print("  [PASS] 损坏工程文件安全报错，程序健壮无崩溃")

    # ---------------------------------------------------------
    # TC-10: Schema Migration & Defaults Fallback
    # ---------------------------------------------------------
    print("\n[TC-10] 旧版协议/缺失字段平滑迁移 (Schema Migration)...")
    legacy_data = {
        "meta": {
            "project_name": "旧版本工程"
        },
        "assets": {
            "audio_path": str(audio_file),
            "audio_duration": 15.0
        },
        "video_track": [
            {
                "clip_path": str(clip1),
                "duration": 15.0
            }
        ]
    }
    legacy_file = test_dir / "旧版本工程.clipforge"
    legacy_file.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

    migrated_proj = EditProject.load(legacy_file)
    assert migrated_proj.meta.project_name == "旧版本工程"
    assert migrated_proj.meta.schema_version == SCHEMA_VERSION
    assert len(migrated_proj.video_track) == 1
    assert migrated_proj.video_track[0].segment_id == "seg_001"
    assert migrated_proj.video_track[0].crop_mode == "crop_fill"
    assert migrated_proj.render_settings.output_width == 1080
    assert migrated_proj.render_settings.fps == 30
    print("  [PASS] 缺失字段自动补全默认值，平滑兼容不同版本工程协议")

    # ---------------------------------------------------------
    # TC-11: Atomic Save Protection
    # ---------------------------------------------------------
    print("\n[TC-11] 磁盘写入异常时的原子级防破坏保护 (Atomic Save)...")
    # Verify that existing valid project is not wiped even if an error occurs
    valid_content = proj_save_path.read_text(encoding="utf-8")

    # Monkeypatch to force error during dump
    class FaultyProject(EditProject):
        def to_dict(self):
            raise RuntimeError("模拟磁盘满或序列化中断")

    faulty = FaultyProject(
        final_proj.meta,
        final_proj.assets,
        final_proj.video_track,
        final_proj.subtitle_track,
        final_proj.render_settings
    )

    try:
        faulty.save(proj_save_path)
        assert False, "未能触发保存失败"
    except ProjectError as e:
        print(f"  捕获写入故障: {e}")

    # Confirm original file is untouched and valid
    after_content = proj_save_path.read_text(encoding="utf-8")
    assert valid_content == after_content, "原工程文件在异常发生时被破坏！"
    # Ensure no leftover temp files
    temp_files = list(test_dir.glob(".tmp_*"))
    assert len(temp_files) == 0, f"残留未清理的临时文件: {temp_files}"
    print("  [PASS] 原子保护生效：原工程完好无损，临时文件全量清理")

    # ---------------------------------------------------------
    # TC-12: Deterministic TimelinePlan (Bypasses Randomizer)
    # ---------------------------------------------------------
    print("\n[TC-12] 确定性时间轴生成 (to_timeline_plan, 绕过随机混剪)...")
    # Calling to_timeline_plan must match the exact sequence in final_proj.video_track
    plan = final_proj.to_timeline_plan(plan_id=99)
    assert plan.plan_id == 99
    assert len(plan.segments) == len(final_proj.video_track)
    for seg_plan, seg_proj in zip(plan.segments, final_proj.video_track):
        assert seg_plan.clip_path == seg_proj.clip_path
        assert seg_plan.duration == seg_proj.duration
        assert seg_plan.display_name == seg_proj.display_name

    assert plan.uniqueness_score == 1.0
    assert "无随机洗牌" in plan.notes[0]
    print(f"  时间轴片段序列: {plan.clip_sequence}")
    print(f"  时间轴计划备注: {plan.notes}")
    print("  [PASS] 成功生成完全确定性的 TimelinePlan，重导时绝不触发随机洗牌")

    print("\n" + "=" * 70)
    print(">>> 阶段 5.3 EditProject 12项测试全量通过！(12/12 PASS)")
    print("=" * 70)


if __name__ == "__main__":
    run_stage5_project_suite()
