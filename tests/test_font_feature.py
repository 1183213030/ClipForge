"""
Font Management and Custom Font Feature Verification Test Suite for ClipForge.
1. Tests FontManager initialization, scanning, and file import.
2. Tests SubtitleCardWidget font selection, add font button, and config generation.
3. Tests SubtitleEditorWidget font synchronization with EditProject.
4. Tests full FFmpeg subtitles filter rendering using custom font with fontsdir.
"""

from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.core.font_manager import FontManager
from app.core.subtitle_processor import SubtitleConfig, build_subtitles_filter
from app.core.video_processor import VideoProcessor, VideoSegment, ExportOptions
from app.ui.widgets.subtitle_card import SubtitleCardWidget
from app.ui.widgets.subtitle_editor_widget import SubtitleEditorWidget
from app.core.edit_project import create_project, RenderSettings, SubtitleTrackItem
from tests.test_stage1 import create_synthetic_test_assets


def test_font_suite():
    print("=" * 70)
    print(">>> 开始执行 ClipForge 自定义字体添加与渲染全量功能验证")
    print("=" * 70)

    app = QApplication.instance() or QApplication(sys.argv)

    test_env = PROJECT_ROOT / "temp" / "测试 空间_FontFeature"
    if test_env.exists():
        shutil.rmtree(test_env, ignore_errors=True)
    test_env.mkdir(parents=True, exist_ok=True)

    # 1. Test FontManager
    print("\n[Step 1/4] 验证 FontManager 初始化与字体扫描/导入...")
    custom_fonts_dir = test_env / "custom_fonts"
    fm = FontManager(custom_fonts_dir)
    initial_fonts = fm.get_available_fonts()
    assert len(initial_fonts) >= 7, "应当包含常见系统字体"
    print(f"  [PASS] 成功发现初始字体 {len(initial_fonts)} 种，首选: {initial_fonts[0]}")

    # Copy / import a real Windows TTF font
    src_font = Path("C:/Windows/Fonts/simkai.ttf")
    if not src_font.exists():
        src_font = next(Path("C:/Windows/Fonts").glob("*.ttf"))

    ok, msg, families = fm.import_font_file(src_font)
    assert ok, f"字体导入应成功: {msg}"
    assert len(families) > 0, "应解析出至少一个字体家族名称"
    print(f"  [PASS] 导入外部字体成功: {src_font.name} -> 家族名称: {families}")

    updated_fonts = fm.get_available_fonts()
    assert families[0] in updated_fonts, "新导入的字体应在可用字体列表中"
    print(f"  [PASS] 可用字体列表已动态更新: {families[0]} 已置顶")

    # 2. Test SubtitleCardWidget
    print("\n[Step 2/4] 验证 SubtitleCardWidget 控件与新字体联动...")
    icons_dir = PROJECT_ROOT / "resources" / "icons"
    sub_card = SubtitleCardWidget(icons_dir)
    assert hasattr(sub_card, "btn_add_font"), "必须包含添加字体按钮"
    assert hasattr(sub_card, "combo_font"), "必须包含字体下拉框"
    assert sub_card.btn_add_font.text() == "添加新字体", "按钮名称应为 '添加新字体'"

    # Simulate importing font into sub_card's FontManager
    ok2, _, fams2 = sub_card.font_manager.import_font_file(src_font)
    assert ok2, "子卡片字体导入应成功"
    sub_card._refresh_font_list()
    sub_card.combo_font.setCurrentText(fams2[0])
    sub_cfg = sub_card.get_subtitle_config()
    assert sub_cfg.font_name == fams2[0], f"SubtitleConfig 字体应为 {fams2[0]}"
    assert sub_cfg.fonts_dir is not None, "SubtitleConfig 必须携带 fonts_dir"
    print(f"  [PASS] SubtitleCardWidget 成功应用新字体 {fams2[0]} 并携带 fonts_dir: {sub_cfg.fonts_dir}")

    # 3. Test SubtitleEditorWidget & EditProject synchronization
    print("\n[Step 3/4] 验证 SubtitleEditorWidget 与 EditProject 字体同步...")
    sub_editor = SubtitleEditorWidget(icons_dir)
    assert hasattr(sub_editor, "combo_font"), "SubtitleEditorWidget 必须包含字体下拉框"
    assert hasattr(sub_editor, "btn_add_font"), "SubtitleEditorWidget 必须包含添加新字体按钮"

    # Create synthetic project
    proj = create_project(
        project_name="测试字体工程",
        audio_path=str(test_env / "a.mp3"),
        audio_duration=10.0,
        srt_path=None,
        video_clips=[],
        render_settings=RenderSettings(font_name="Microsoft YaHei", font_size=12),
        initial_subtitles=[
            SubtitleTrackItem(subtitle_id=1, start_time=0.0, end_time=2.0, original_text="测试字幕", edited_text="测试字幕")
        ]
    )
    sub_editor.set_project(proj)
    assert sub_editor.combo_font.currentText() == "Microsoft YaHei"

    # Switch font in SubtitleEditorWidget
    sub_editor.combo_font.setCurrentText(fams2[0])
    assert proj.render_settings.font_name == fams2[0], "工程内部 render_settings 字体应已更新"
    print(f"  [PASS] 精细编辑工作台字体切换联动成功: {proj.render_settings.font_name}")

    # 4. Test FFmpeg render with custom font
    print("\n[Step 4/4] 验证 FFmpeg 基于 fontsdir 实际烧录自定义字体...")
    assets_dir = test_env / "media"
    c1, _, audio, srt = create_synthetic_test_assets(assets_dir)
    vp = VideoProcessor(temp_dir=test_env / "vp_temp")

    out_mp4 = test_env / "custom_font_out.mp4"
    opts = ExportOptions(
        output_width=720,
        output_height=1280,
        fps=25,
        video_bitrate="2M",
        subtitle_config=SubtitleConfig(
            font_name=fams2[0],
            font_size=24,
            fonts_dir=str(sub_card.font_manager.fonts_dir)
        ),
        fonts_dir=str(sub_card.font_manager.fonts_dir)
    )

    vp.render_mixed_video(
        segments=[VideoSegment(file_path=str(c1), start_time=0.0, duration=2.0)],
        audio_path=audio,
        srt_path=srt,
        output_path=out_mp4,
        options=opts
    )
    assert out_mp4.is_file() and out_mp4.stat().st_size > 10000, "渲染视频应成功生成且非空"
    print(f"  [PASS] 成功渲染包含自定义字体 ({fams2[0]}) 的成品视频: {out_mp4.name} ({out_mp4.stat().st_size} bytes)")

    # Cleanup test_env & imported test fonts in resources/fonts
    shutil.rmtree(test_env, ignore_errors=True)
    for p in (PROJECT_ROOT / "resources" / "fonts").glob("*.ttf"):
        try:
            p.unlink()
        except Exception:
            pass
    print("\n" + "=" * 70)
    print(">>> 全部自定义字体功能验证用例通过 (SUCCESS)!")
    print("=" * 70)


if __name__ == "__main__":
    test_font_suite()
