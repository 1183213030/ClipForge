"""
Badge Management and Configuration Persistence Service for ClipForge 3.0.
Manages user-uploaded watermark PNG badges in a persistent library folder,
and saves/loads user's choice of default landscape and portrait badges across restarts.
"""

import json
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class BadgeService:
    """Manages the watermark badge library and user default preferences."""

    def __init__(self, project_root: Optional[Path] = None):
        if getattr(sys, "frozen", False):
            # In packaged mode, badges live next to the exe to persist user uploads across launches
            base_exe_dir = Path(sys.executable).parent
            self.badge_dir = base_exe_dir / "badges"
            self.config_dir = base_exe_dir / "config"
            # Optional seed from bundled MEIPASS if library doesn't exist yet
            meipass_badges = Path(getattr(sys, "_MEIPASS", "")) / "resources" / "badges"
            if not self.badge_dir.exists() and meipass_badges.is_dir():
                try:
                    shutil.copytree(meipass_badges, self.badge_dir)
                except Exception as exc:
                    logger.warning(f"Failed to seed initial badges: {exc}")
        else:
            root = project_root or Path(__file__).resolve().parent.parent.parent
            self.badge_dir = root / "resources" / "badges"
            self.config_dir = root / "config"

        self.badge_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.config_dir / "badge_settings.json"

    def get_badge_library_dir(self) -> Path:
        """Returns the persistent folder where badge PNG files are stored."""
        self.badge_dir.mkdir(parents=True, exist_ok=True)
        return self.badge_dir

    def list_badges(self) -> list[Path]:
        """Lists all valid PNG badge files currently in the library."""
        if not self.badge_dir.is_dir():
            return []
        files = [
            f for f in self.badge_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".png"
        ]
        files.sort(key=lambda p: p.name.lower())
        return files

    def import_badge(self, source_path: Path) -> Optional[Path]:
        """
        Copies a user-selected external PNG file into the persistent badge library.
        Prevents name collisions by appending numbers if needed.
        Returns the destination Path in the badge library.
        """
        if not source_path.is_file() or source_path.suffix.lower() != ".png":
            logger.error(f"Invalid badge file: {source_path}")
            return None

        self.badge_dir.mkdir(parents=True, exist_ok=True)
        base_name = source_path.stem
        ext = source_path.suffix.lower()

        target_name = f"{base_name}{ext}"
        target_path = self.badge_dir / target_name
        counter = 1
        while target_path.exists() and not self._is_same_file(source_path, target_path):
            target_name = f"{base_name}_{counter:02d}{ext}"
            target_path = self.badge_dir / target_name
            counter += 1

        if not target_path.exists():
            shutil.copyfile(source_path, target_path)
            logger.info(f"Imported new badge into library: {target_path}")

        return target_path

    @staticmethod
    def _is_same_file(p1: Path, p2: Path) -> bool:
        try:
            return p1.resolve() == p2.resolve()
        except Exception:
            return False

    def load_settings(self) -> dict:
        """Loads user badge configuration from JSON."""
        if self.settings_file.is_file():
            try:
                data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                logger.warning(f"Failed to parse badge settings: {exc}")
        return {}

    def save_settings(self, settings: dict):
        """Saves user badge configuration to JSON."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as exc:
            logger.error(f"Failed to write badge settings: {exc}")

    def get_default_badges(self) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Resolves the user's saved default landscape and portrait badge paths.
        Returns (landscape_badge_path_or_none, portrait_badge_path_or_none).
        """
        settings = self.load_settings()
        l_name = settings.get("default_landscape_badge")
        p_name = settings.get("default_portrait_badge")

        l_path = (self.badge_dir / l_name) if l_name else None
        p_path = (self.badge_dir / p_name) if p_name else None

        l_res = l_path if (l_path and l_path.is_file()) else None
        p_res = p_path if (p_path and p_path.is_file()) else None
        return l_res, p_res

    def set_default_landscape_badge(self, filename: Optional[str]):
        """Saves or clears the default landscape badge."""
        settings = self.load_settings()
        if filename:
            settings["default_landscape_badge"] = filename
        else:
            settings.pop("default_landscape_badge", None)
        self.save_settings(settings)

    def set_default_portrait_badge(self, filename: Optional[str]):
        """Saves or clears the default portrait badge."""
        settings = self.load_settings()
        if filename:
            settings["default_portrait_badge"] = filename
        else:
            settings.pop("default_portrait_badge", None)
        self.save_settings(settings)
