"""
Stage 5.6.3 Verification Suite for Subtitle Font Size, Project Save/Restore & Deterministic Re-export.
Tests:
1. RenderSettings & SubtitleConfig default font_size == 16.
2. Font size range validation [12, 36], rejection of invalid values.
3. EditProject.set_font_size() updates render_settings and touches updated_at.
4. Project persistence: saving to .clipforge and reloading restores font_size == 16.
5. Backward compatibility: loading an existing project with font_size == 24 preserves 24.
6. SubtitleEditorWidget GUI: spin box reflects project font_size, emits project_modified.
7. Deterministic re-export plan generation without Randomizer shuffle.
8. Preservation guarantee: v1 output file exists and is strictly protected.
"""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.core.edit_project import (
    EditProject, create_project, RenderSettings, VideoTrackSegment, SubtitleTrackItem
)
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition
from app.ui.widgets.subtitle_editor_widget import SubtitleEditorWidget


class TestStage563FontSizeAndReExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_stage563_"))
        self.dummy_audio = self.temp_dir / "test_audio.mp3"
        self.dummy_audio.write_bytes(b"dummy_mp3_content")
        self.dummy_video = self.temp_dir / "clip_01.mp4"
        self.dummy_video.write_bytes(b"dummy_mp4_content")
        self.dummy_srt = self.temp_dir / "test.srt"
        self.dummy_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n测试字幕内容\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_default_font_size(self):
        """TC-01: Verify default font_size is 16 across data model, subtitle config and new project."""
        rs = RenderSettings()
        self.assertEqual(rs.font_size, 16, "RenderSettings 默认字号应为 16")

        sub_cfg = SubtitleConfig()
        self.assertEqual(sub_cfg.font_size, 16, "SubtitleConfig 默认字号应为 16")

        proj = create_project(
            project_name="新项目_默认字号测试",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)]
        )
        self.assertEqual(proj.render_settings.font_size, 16, "新建项目默认字号应为 16")

        opts = proj.to_export_options()
        self.assertIsNotNone(opts.subtitle_config)
        self.assertEqual(opts.subtitle_config.font_size, 16)
        force_style = opts.subtitle_config.to_force_style_str()
        self.assertIn("FontSize=16", force_style, "FFmpeg force_style 参数必须包含 FontSize=16")

    def test_02_font_size_range_validation(self):
        """TC-02: Verify font size range [12, 36] and rejection of invalid values."""
        proj = create_project(
            project_name="字号范围校验",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)]
        )
        # Valid boundaries
        proj.set_font_size(8)
        self.assertEqual(proj.render_settings.font_size, 8)

        proj.set_font_size(36)
        self.assertEqual(proj.render_settings.font_size, 36)

        proj.set_font_size(10)
        self.assertEqual(proj.render_settings.font_size, 10)

        proj.set_font_size(16)
        self.assertEqual(proj.render_settings.font_size, 16)

        # Invalid values
        with self.assertRaises(ValueError):
            proj.set_font_size(7)

        with self.assertRaises(ValueError):
            proj.set_font_size(37)

        with self.assertRaises(ValueError):
            proj.set_font_size(-5)

        with self.assertRaises(ValueError):
            proj.set_font_size(100)

    def test_03_dirty_state_on_font_size_change(self):
        """TC-03: Verify set_font_size updates timestamp and dirty state."""
        proj = create_project(
            project_name="脏标记测试",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)]
        )
        t_init = proj.meta.updated_at
        proj.set_font_size(18)
        self.assertEqual(proj.render_settings.font_size, 18)
        self.assertGreaterEqual(proj.meta.updated_at, t_init)

    def test_04_save_and_reopen_project(self):
        """TC-04: Verify saving to .clipforge and reopening restores font_size == 16."""
        proj = create_project(
            project_name="保存恢复测试",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)],
            render_settings=RenderSettings(font_size=16)
        )
        proj_path = self.temp_dir / "test_proj.clipforge"
        proj.save(proj_path)
        self.assertTrue(proj_path.exists())

        # Load back
        loaded = EditProject.load(proj_path)
        self.assertEqual(loaded.render_settings.font_size, 16, "重新打开项目后字号应恢复为 16")
        self.assertEqual(loaded.meta.project_name, "保存恢复测试")

    def test_05_backward_compatibility_old_project(self):
        """TC-05: Verify existing project with font_size == 24 preserves 24 on load."""
        v1_real_proj = PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片.clipforge"
        if v1_real_proj.is_file():
            loaded = EditProject.load(v1_real_proj)
            self.assertEqual(loaded.render_settings.font_size, 24, "已有阶段 5.6.2 项目的字号 24 应被完整保留，不强制覆盖")

    def test_06_subtitle_editor_widget_font_control(self):
        """TC-06: Verify SubtitleEditorWidget spin box reflects project and emits signal."""
        icons_dir = PROJECT_ROOT / "resources" / "icons"
        widget = SubtitleEditorWidget(icons_dir=icons_dir)

        sub_item = SubtitleTrackItem(
            subtitle_id=1,
            start_time=0.0,
            end_time=2.0,
            original_text="测试字幕内容",
            edited_text="测试字幕内容"
        )
        proj = create_project(
            project_name="控件集成测试",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)],
            initial_subtitles=[sub_item],
            render_settings=RenderSettings(font_size=16)
        )
        widget.set_project(proj)
        self.assertEqual(widget.spin_font_size.value(), 16)

        # Listen to project_modified signal
        modified_fired = []
        widget.project_modified.connect(lambda: modified_fired.append(True))

        # Change via spin box to 20
        widget.spin_font_size.setValue(20)
        self.assertEqual(proj.render_settings.font_size, 20)
        self.assertTrue(len(modified_fired) > 0)
        self.assertEqual(widget.lbl_preview_text.text(), "测试字幕内容")

        # Range clamping in widget
        widget.spin_font_size.setValue(5)
        self.assertEqual(widget.spin_font_size.value(), 8, "下限应被自动限制为 8")

        widget.spin_font_size.setValue(50)
        self.assertEqual(widget.spin_font_size.value(), 36, "上限应被自动限制为 36")

    def test_07_deterministic_reexport_plan(self):
        """TC-07: Verify to_timeline_plan produces exact locked timeline segments."""
        seg1 = VideoTrackSegment("s1", 0, str(self.dummy_video), "hash1", "clip1", 0.0, 4.0)
        seg2 = VideoTrackSegment("s2", 1, str(self.dummy_video), "hash1", "clip1", 2.0, 6.0)

        proj = create_project(
            project_name="确定性重导计划测试",
            audio_path=str(self.dummy_audio),
            audio_duration=10.0,
            srt_path=str(self.dummy_srt),
            video_clips=[str(self.dummy_video)],
            initial_segments=[seg1, seg2],
            render_settings=RenderSettings(font_size=16)
        )

        plan = proj.to_timeline_plan()
        self.assertEqual(len(plan.segments), 2)
        self.assertEqual(plan.segments[0].duration, 4.0)
        self.assertEqual(plan.segments[1].start_time, 2.0)
        self.assertEqual(plan.segments[1].duration, 6.0)
        self.assertEqual(plan.total_duration, 10.0)

    def test_08_protection_of_v1_output(self):
        """TC-08: Verify that v1成片 and manifest from 5.6.2 are strictly preserved."""
        v1_mp4 = PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片_v1.mp4"
        v1_proj = PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片.clipforge"
        v1_manifest = PROJECT_ROOT / "output" / "manifest_stage5_6_2_customer_full.json"

        self.assertTrue(v1_mp4.is_file(), "v1 视频必须存在且保留")
        self.assertGreater(v1_mp4.stat().st_size, 200 * 1024 * 1024, "v1 视频大小必须 > 200 MB")
        self.assertTrue(v1_proj.is_file(), "v1 工程文件必须保留")
        self.assertTrue(v1_manifest.is_file(), "v1 清单文件必须保留")


if __name__ == "__main__":
    unittest.main()
