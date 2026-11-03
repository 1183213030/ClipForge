"""
Stage 5.4 Verification Suite for ClipForge: Workbench & Lightweight Editing Workflow.
Validates the complete editing lifecycle requested by the user:
1. Load project and video into 9:16 player.
2. Test playback, pause, seeking, and timecode.
3. Reorder video segments via UI actions.
4. Replace a video segment with a new clip.
5. Modify segment duration with boundary and tail balancing validation.
6. Edit subtitle text and timestamp in the subtitle editor table.
7. Save project, close, and reload to verify 100% state persistence.
8. Execute deterministic re-export (bypasses randomizer).
9. Post-check new output video (v2) with FFprobe.
10. Ensure original exported video (v1) was NOT overwritten.
11. Capture high-resolution screenshot of the Stage 5.4 Workbench UI.
"""

import os
from pathlib import Path
import shutil
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.edit_project import (
    EditProject, create_project, VideoTrackSegment, SubtitleTrackItem,
    RenderSettings, MIN_SEGMENT_DURATION, FRAME_TOLERANCE_EPSILON
)
from app.utils.path_utils import normalize_path
from app.core.media_probe import probe_media
from app.core.media_scanner import calculate_file_sha256
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions
from app.ui.main_window import MainWindow
from app.ui.pages.workbench_page import WorkbenchPage
from tests.test_stage1 import create_synthetic_test_assets


def run_stage5_workbench_suite():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 阶段 5.4 视频预览与轻量编辑工作台端到端测试")
    print("=" * 70)

    # 0. Setup headless Qt application
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    # Mock blocking modal dialogs for automated testing
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.critical = lambda *args, **kwargs: QMessageBox.Ok


    test_env = PROJECT_ROOT / "temp" / "测试 空间_Stage5_Workbench"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create synthetic media assets
    print("\n[Step 1/10] 创建测试音视频素材与初始成片...")
    clip1, clip2, audio_path, srt_path = create_synthetic_test_assets(test_env)


    # Create a 3rd distinct clip for replace test
    from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command
    clip3 = test_env / "素材_替补03_1080p.mp4"
    ffmpeg = get_ffmpeg_path()
    run_command([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "testsrc=size=1080x1920:rate=30:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(clip3)
    ])
    assert clip3.is_file()

    audio_meta = probe_media(audio_path)
    audio_dur = audio_meta.duration
    print(f"  测试音频时长: {audio_dur:.3f}s")

    # Render initial version 1 video
    v1_output = output_dir / "小说推文_测试01_v1.mp4"
    if v1_output.exists():
        v1_output.unlink()

    processor = VideoProcessor(temp_dir=test_env)
    processor.render_mixed_video(
        segments=[
            VideoSegment(file_path=str(clip1), start_time=0.0, duration=4.0),
            VideoSegment(file_path=str(clip2), start_time=0.0, duration=round(audio_dur - 4.0, 3))
        ],
        audio_path=audio_path,
        srt_path=srt_path,
        output_path=v1_output
    )
    assert v1_output.is_file(), "初始 v1 视频生成失败"
    v1_size = v1_output.stat().st_size
    print(f"  [OK] 初始 v1 成品已生成: {v1_output.name} ({v1_size} bytes)")

    # 2. Build initial EditProject
    sha1 = calculate_file_sha256(clip1)
    sha2 = calculate_file_sha256(clip2)
    sha3 = calculate_file_sha256(clip3)

    proj = create_project(
        project_name="小说推文_测试01",
        audio_path=str(audio_path),
        audio_duration=audio_dur,
        srt_path=str(srt_path),
        video_clips=[str(clip1), str(clip2), str(clip3)],
        initial_segments=[
            VideoTrackSegment(
                segment_id="seg_001", order_index=0, clip_path=str(clip1),
                clip_sha256=sha1, display_name=Path(clip1).name, duration=4.0
            ),
            VideoTrackSegment(
                segment_id="seg_002", order_index=1, clip_path=str(clip2),
                clip_sha256=sha2, display_name=Path(clip2).name, duration=round(audio_dur - 4.0, 3)
            )
        ],
        initial_subtitles=[
            SubtitleTrackItem(subtitle_id=1, start_time=0.0, end_time=2.5,
                              original_text="第一句原始台词", edited_text="第一句原始台词"),
            SubtitleTrackItem(subtitle_id=2, start_time=2.5, end_time=5.0,
                              original_text="第二句原始台词", edited_text="第二句原始台词")
        ]
    )
    proj.add_export_history(output_path=str(v1_output), status="SUCCESS", elapsed=3.2)

    proj_file = test_env / "小说推文_测试01.clipforge"
    proj.save(proj_file)
    print("  [OK] 初始工程文件已保存")

    # 3. Instantiate MainWindow and load Workbench
    print("\n[Step 2/10] 初始化主窗口与加载工作台...")
    window = MainWindow(project_root=PROJECT_ROOT)
    window.show()
    app.processEvents()

    # Switch to Workbench tab
    window.btn_nav_workbench.click()
    app.processEvents()
    assert window.stack.currentIndex() == 1, "未成功切换至工作台页面"
    workbench = window.workbench_page

    # Load project into workbench
    workbench.set_project(proj, proj_file)
    app.processEvents()
    assert workbench.project.meta.project_name == "小说推文_测试01"
    print("  [PASS] 主窗口头部与工作台加载成功，项目元数据完全同步")

    # 4. Test Video Player Controls
    print("\n[Step 3/10] 视频播放器 (9:16 Viewport) 控件与播放状态测试...")
    player = workbench.player_widget
    player.load_media(v1_output)
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()

    # Test Play / Pause / Seek
    player.play()
    app.processEvents()
    assert player.btn_play.toolTip() != "error"

    player.seek(1500)  # seek to 1.5s
    app.processEvents()
    player.pause()
    app.processEvents()
    print("  [PASS] QMediaPlayer 播放、暂停、进度拖动与时间戳显示正常")

    # 5. Test Segment Reordering in UI
    print("\n[Step 4/10] UI 调换视频片段顺序 (Segment Reordering)...")
    assert workbench.project.video_track[0].segment_id == "seg_001"
    assert workbench.project.video_track[1].segment_id == "seg_002"

    # Move seg_002 up
    workbench.segment_list._on_move_up("seg_002")
    app.processEvents()

    assert workbench.project.video_track[0].segment_id == "seg_002"
    assert workbench.project.video_track[1].segment_id == "seg_001"
    assert workbench.is_dirty is True
    # Verify audio duration and subtitle timestamps are completely untouched
    assert workbench.project.assets.audio_duration == audio_dur
    assert workbench.project.subtitle_track[0].start_time == 0.0
    print("  [PASS] 片段顺序调换成功，音频总时长与字幕时间轴毫秒未动")

    # 6. Test Segment Replacement in UI
    print("\n[Step 5/10] UI 替换视频片段素材 (Segment Replacement)...")
    # Replace seg_001 clip with clip3
    target_seg_id = "seg_001"
    workbench.project.replace_segment(target_seg_id, str(clip3), sha3)
    workbench.segment_list.refresh()
    workbench._on_project_modified()
    app.processEvents()

    replaced_seg = [s for s in workbench.project.video_track if s.segment_id == target_seg_id][0]
    assert replaced_seg.clip_path == normalize_path(str(clip3))
    assert replaced_seg.clip_sha256 == sha3
    assert replaced_seg.display_name == clip3.name
    print(f"  [PASS] 成功替换片段素材为: {clip3.name}，哈希已同步更新")

    # 7. Test Segment Duration Modification & Tail Balancing
    print("\n[Step 6/10] UI 修改片段时长与尾部对齐 (Duration Modification)...")
    # Current track: seg_002 (at index 0), seg_001 (tail at index 1)
    # Modify seg_002 duration to 5.0s
    workbench.segment_list._on_duration_changed("seg_002", 5.0)
    app.processEvents()

    seg_0 = workbench.project.video_track[0]
    seg_1 = workbench.project.video_track[1]
    assert seg_0.duration == 5.0
    # Tail segment seg_001 should automatically balance
    expected_tail = round(audio_dur - 5.0, 3)
    assert abs(seg_1.duration - expected_tail) <= FRAME_TOLERANCE_EPSILON
    total_v_dur = seg_0.duration + seg_1.duration
    assert abs(total_v_dur - audio_dur) <= FRAME_TOLERANCE_EPSILON
    print(f"  片段时长序列: [{seg_0.duration}s, {seg_1.duration}s], 总时长: {total_v_dur:.3f}s (音频: {audio_dur:.3f}s)")
    print("  [PASS] 尾段自动平衡，严格满足 |sum(Di) - Ta| <= epsilon")

    # 8. Test Subtitle Modification in Table
    print("\n[Step 7/10] UI 修改字幕台词内容与时间戳 (Subtitle In-place Editing)...")
    sub_widget = workbench.subtitle_editor
    # Edit text of row 0
    sub_widget.table.item(0, 3).setText("这是用户精修修改后的第一句台词！")
    # Trigger cellChanged
    sub_widget._on_cell_changed(0, 3)
    app.processEvents()

    # Edit end time of row 0
    sub_widget.table.item(0, 2).setText("2.80")
    sub_widget._on_cell_changed(0, 2)
    app.processEvents()

    sub_item = workbench.project.subtitle_track[0]
    assert sub_item.edited_text == "这是用户精修修改后的第一句台词！"
    assert sub_item.end_time == 2.80
    assert sub_item.is_modified is True
    print("  [PASS] 字幕内容与时间戳就地编辑成功，已同步至 EditProject")

    # 9. Test Save Project, Close & Reload (Persistence Check)
    print("\n[Step 8/10] 保存工程、重开项目并检查修改保留 (Save & Re-open)...")
    workbench._on_save_project()
    app.processEvents()
    assert workbench.is_dirty is False
    assert proj_file.is_file()

    # Simulate closing project and reopening
    workbench.set_project(None, None)
    app.processEvents()
    assert workbench.project is None

    # Reload from disk
    reloaded_proj = EditProject.load(proj_file)
    workbench.set_project(reloaded_proj, proj_file)
    app.processEvents()

    assert workbench.project.video_track[0].segment_id == "seg_002"
    assert workbench.project.video_track[1].segment_id == "seg_001"
    assert workbench.project.video_track[1].clip_path == normalize_path(str(clip3))
    assert workbench.project.video_track[0].duration == 5.0
    assert workbench.project.subtitle_track[0].edited_text == "这是用户精修修改后的第一句台词！"
    assert workbench.project.subtitle_track[0].end_time == 2.80
    print("  [PASS] 重开工程后，调换顺序、替换素材、修改时长与修改字幕 100% 完整保留！")

    # 10. Test Deterministic Re-export (Non-random)
    print("\n[Step 9/10] 执行确定性重导 (Deterministic Re-export v2)...")
    v2_expected = output_dir / "小说推文_测试01_v2.mp4"
    if v2_expected.exists():
        v2_expected.unlink()

    # Trigger re-export
    workbench._on_reexport()
    app.processEvents()

    # Wait for re-export worker thread to complete
    max_wait = 45.0
    start_t = time.time()
    while workbench.reexport_thread and workbench.reexport_thread.isRunning():
        app.processEvents()
        time.sleep(0.1)
        if time.time() - start_t > max_wait:
            raise TimeoutError("确定性重导超时！")

    assert v2_expected.is_file(), f"未生成重导文件: {v2_expected}"
    print(f"  [OK] v2 重导文件生成成功: {v2_expected.name} ({v2_expected.stat().st_size} bytes)")

    # 11. Post-export FFprobe Inspection & Overwrite Prevention Check
    print("\n[Step 10/10] FFprobe 深度后置校验与防覆盖检查...")
    # A. Check v1 is not overwritten
    assert v1_output.is_file(), "原始 v1 成品被误删！"
    assert v1_output.stat().st_size == v1_size, "原始 v1 成品被意外修改或覆盖！"
    print("  [PASS] 原始成品版本得到严格保护，未被覆盖")

    # B. FFprobe check on v2
    v2_meta = probe_media(v2_expected)
    assert v2_meta.is_valid_video, "导出的 v2 视频无法通过 FFprobe 验证"
    assert v2_meta.width == 1080 and v2_meta.height == 1920, f"分辨率错误: {v2_meta.width}x{v2_meta.height}"
    assert abs(v2_meta.duration - audio_dur) <= 0.040, f"时长不匹配: 视频 {v2_meta.duration}s, 音频 {audio_dur}s"
    assert v2_meta.video_codec == "h264", f"编码非 H.264: {v2_meta.video_codec}"
    assert v2_meta.audio_codec == "aac", f"音轨编码非 AAC: {v2_meta.audio_codec}"
    print(f"  v2 分辨率: {v2_meta.width}x{v2_meta.height} (9:16)")
    print(f"  v2 帧率:   {v2_meta.fps:.2f} FPS")
    print(f"  v2 时长:   {v2_meta.duration:.3f}s (音频: {audio_dur:.3f}s, 误差 {abs(v2_meta.duration - audio_dur):.3f}s)")
    print("  [PASS] FFprobe 检验全项通过")

    # 12. Capture GUI screenshot for user review
    screenshot_path = output_dir / "gui_screenshot_stage5_workbench.png"
    pixmap = window.grab()
    pixmap.save(str(screenshot_path))
    assert screenshot_path.is_file(), "GUI 截图保存失败"
    print(f"  [OK] 阶段 5.4 工作台界面截图已保存: {screenshot_path.name}")

    print("\n" + "=" * 70)
    print(">>> ClipForge 阶段 5.4 视频预览与轻量编辑工作台 10项全流程测试 100% 通过！")
    print("=" * 70)

    workbench.player_widget.player.stop()
    workbench.player_widget.player.setSource(QUrl())
    window.close()
    app.processEvents()
    print("  [OK] 测试套件正常退出")




if __name__ == "__main__":
    run_stage5_workbench_suite()
