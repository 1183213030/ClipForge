"""
Font Management and Registration Module for ClipForge.
Handles scanning, importing, Qt application font registration, and FFmpeg font directory integration.
"""

import logging
from pathlib import Path
import shutil
from typing import Optional, List, Tuple, Dict

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

DEFAULT_POPULAR_FONTS = [
    "Microsoft YaHei",
    "SimHei",
    "KaiTi",
    "FangSong",
    "SimSun",
    "Segoe UI",
    "Arial"
]

SUPPORTED_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}


class FontManager:
    """Manages custom font loading, registration, and discovery."""

    def __init__(self, fonts_dir: Optional[Path] = None):
        if fonts_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.fonts_dir = project_root / "resources" / "fonts"
        else:
            self.fonts_dir = Path(fonts_dir).resolve()

        self.fonts_dir.mkdir(parents=True, exist_ok=True)
        # Mapping of font family name -> font file Path
        self.custom_fonts: Dict[str, Path] = {}
        self.scan_fonts()

    def scan_fonts(self) -> Dict[str, Path]:
        """Scans fonts_dir for font files and registers them into QFontDatabase."""
        app = QApplication.instance()
        if not self.fonts_dir.is_dir():
            return self.custom_fonts

        for f in self.fonts_dir.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_FONT_EXTENSIONS:
                try:
                    if app:
                        font_id = QFontDatabase.addApplicationFont(str(f))
                        if font_id != -1:
                            families = QFontDatabase.applicationFontFamilies(font_id)
                            for fam in families:
                                self.custom_fonts[fam] = f
                        else:
                            # Fallback using stem name if registration returned -1
                            self.custom_fonts[f.stem] = f
                    else:
                        self.custom_fonts[f.stem] = f
                except Exception as e:
                    logger.warning("注册字体文件失败: %s, 错误: %s", f.name, e)

        return self.custom_fonts

    def import_font_file(self, file_path: str | Path) -> Tuple[bool, str, List[str]]:
        """
        Imports an external font file into the application fonts directory,
        registers it with QFontDatabase, and returns (success, message, family_names).
        """
        src = Path(file_path).resolve()
        if not src.is_file():
            return False, f"字体文件不存在: {src}", []

        ext = src.suffix.lower()
        if ext not in SUPPORTED_FONT_EXTENSIONS:
            return False, f"不支持的字体格式 ({ext})，仅支持 TTF / OTF / TTC / WOFF", []

        dest = self.fonts_dir / src.name
        try:
            if src != dest:
                shutil.copy2(src, dest)
        except Exception as e:
            return False, f"复制字体文件失败: {e}", []

        # Register in Qt
        app = QApplication.instance()
        families: List[str] = []
        if app:
            try:
                font_id = QFontDatabase.addApplicationFont(str(dest))
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
            except Exception as e:
                logger.warning("QFontDatabase 注册异常: %s", e)

        if not families:
            families = [src.stem]

        for fam in families:
            self.custom_fonts[fam] = dest

        family_str = ", ".join(families)
        return True, f"成功装载字体: {family_str}", families

    def get_available_fonts(self) -> List[str]:
        """
        Returns an ordered, deduplicated list of available fonts:
        1. Custom imported fonts
        2. Windows standard Chinese fonts
        3. Other system installed font families
        """
        result: List[str] = []
        seen = set()

        def add_font(f_name: str):
            if f_name and f_name not in seen:
                seen.add(f_name)
                result.append(f_name)

        # 1. Add custom fonts first
        for fam in self.custom_fonts.keys():
            add_font(fam)

        # 2. Add default popular fonts
        for fam in DEFAULT_POPULAR_FONTS:
            add_font(fam)

        # 3. Add system fonts from QFontDatabase if available
        app = QApplication.instance()
        if app:
            try:
                for fam in QFontDatabase.families():
                    # Only add common Chinese or non-hidden fonts to keep list manageable
                    if any(ord(c) > 127 for c in fam):
                        add_font(fam)
            except Exception:
                pass

        return result

    def get_font_file(self, family_name: str) -> Optional[Path]:
        """Returns the font file path for a given family name if it is a custom font."""
        return self.custom_fonts.get(family_name)
