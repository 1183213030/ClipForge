"""
Unit & Integration Tests for ClipForge 3.0 Color Matrix Studio.
Tests filter generation, OpenCV preview calculations, configuration handling, and GUI initialization.
"""

from pathlib import Path
import sys
import unittest
import numpy as np

# Ensure root in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.color_matrix_processor import (
    COLOR_PRESETS,
    ColorMatrixConfig,
    MatrixTaskUnit,
    build_color_filter,
    build_layout_filter,
    build_badge_filter,
    build_fingerprint_filter,
    assemble_filter_chain,
)
from app.core.color_preview_engine import ColorPreviewEngine


class TestColorMatrixEngine(unittest.TestCase):

    def test_color_filter_generation(self):
        # 1. Original / Zero Strength
        self.assertEqual(build_color_filter("original", 0.6), "")
        self.assertEqual(build_color_filter("red", 0.0), "")

        # 2. Red color filter with strength
        red_f = build_color_filter("red", 0.6)
        self.assertIn("colorbalance", red_f)
        self.assertIn("rm=", red_f)

        # 3. Black (B&W) filter
        black_f = build_color_filter("black", 0.6)
        self.assertIn("hue=s=", black_f)
        self.assertIn("eq=contrast=", black_f)

        # 4. Yellow, Purple, Green, Blue
        for c in ["yellow", "purple", "green", "blue"]:
            filt = build_color_filter(c, 0.8)
            self.assertIn("colorbalance", filt)

    def test_layout_filter(self):
        land = build_layout_filter("landscape")
        self.assertIn("1280:720", land)

        port = build_layout_filter("portrait")
        self.assertIn("720:1280", port)
        self.assertIn("crop=", port)

        orig = build_layout_filter("original_size")
        self.assertEqual(orig, "")

    def test_badge_and_fingerprint(self):
        badge = build_badge_filter("二创专用")
        self.assertIn("drawtext", badge)
        self.assertIn("二创专用", badge)

        fp = build_fingerprint_filter()
        self.assertIn("noise=", fp)

    def test_full_chain_assembly(self):
        unit = MatrixTaskUnit(
            source_path=Path("dummy.mp4"),
            output_path=Path("out.mp4"),
            color="purple",
            strength=0.75,
            layout="landscape",
            add_badge=True,
            badge_text="独家",
            enable_fingerprint=True,
        )
        chain = assemble_filter_chain(unit)
        self.assertIn("colorbalance", chain)
        self.assertIn("noise=", chain)
        self.assertIn("scale=1280:720", chain)
        self.assertIn("drawtext=", chain)
        self.assertIn("format=yuv420p", chain)

    def test_opencv_preview_grading(self):
        # Generate dummy 720p frame
        dummy_bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
        dummy_bgr[:, :] = (100, 100, 100)  # Mid-gray

        for color_key, _, _ in COLOR_PRESETS:
            res = ColorPreviewEngine.apply_color_grading(
                dummy_bgr,
                color=color_key,
                strength=0.6,
                add_badge=True,
                badge_text="测试",
                layout="landscape",
            )
            self.assertEqual(res.shape[:2], (720, 1280))
            self.assertIsInstance(res, np.ndarray)

        # Test portrait layout crop simulation
        res_port = ColorPreviewEngine.apply_color_grading(
            dummy_bgr,
            color="red",
            strength=0.6,
            layout="portrait",
        )
        # 720 * 9 / 16 = 405 width
        self.assertEqual(res_port.shape[1], 405)
        self.assertEqual(res_port.shape[0], 720)


    def test_default_badge_resolution_and_overlay(self):
        from app.core.color_matrix_processor import get_default_badge_path
        p_land = get_default_badge_path("landscape")
        p_port = get_default_badge_path("portrait")

        self.assertIsNotNone(p_land)
        self.assertTrue(p_land.is_file())
        self.assertIsNotNone(p_port)
        self.assertTrue(p_port.is_file())

        # Test RGBA loading
        rgba_land = ColorPreviewEngine.load_badge_rgba(p_land)
        self.assertIsNotNone(rgba_land)
        self.assertEqual(rgba_land.shape[-1], 4)

        # Test overlay on dummy 720p frame
        dummy_bgr = np.zeros((720, 1280, 3), dtype=np.uint8)
        dummy_bgr[:, :] = (80, 80, 80)
        res_land = ColorPreviewEngine.apply_color_grading(
            dummy_bgr,
            color="red",
            strength=0.6,
            add_badge=True,
            badge_image_path=p_land,
            layout="landscape",
        )
        self.assertEqual(res_land.shape, (720, 1280, 3))

    def test_badge_service_persistence(self):
        from app.services.badge_service import BadgeService
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            svc = BadgeService(project_root=tmp_root)

            # Initially empty badges and defaults
            self.assertEqual(svc.list_badges(), [])
            def_l, def_p = svc.get_default_badges()
            self.assertIsNone(def_l)
            self.assertIsNone(def_p)

            # Create dummy badge png
            dummy_png = tmp_root / "test_user_badge.png"
            from PIL import Image
            img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
            img.save(dummy_png)

            # Import into library
            imported = svc.import_badge(dummy_png)
            self.assertIsNotNone(imported)
            self.assertTrue(imported.is_file())
            self.assertEqual(len(svc.list_badges()), 1)

            # Set as default landscape
            svc.set_default_landscape_badge(imported.name)
            saved_l, saved_p = svc.get_default_badges()
            self.assertIsNotNone(saved_l)
            self.assertEqual(saved_l.name, imported.name)
            self.assertIsNone(saved_p)

            # Reload service in same dir to test persistence across restarts
            svc2 = BadgeService(project_root=tmp_root)
            saved_l2, saved_p2 = svc2.get_default_badges()
            self.assertIsNotNone(saved_l2)
            self.assertEqual(saved_l2.name, imported.name)

            # Clear default
            svc2.set_default_landscape_badge(None)
            saved_l3, _ = svc2.get_default_badges()
            self.assertIsNone(saved_l3)


if __name__ == "__main__":
    unittest.main()
