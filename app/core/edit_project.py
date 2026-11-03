"""
EditProject Data Model Module for ClipForge.
Manages persistent timeline editing states, independent video & audio/subtitle tracks,
schema versioning, asset integrity validation, and non-random re-export plans.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Optional
import uuid

from app.core.media_scanner import calculate_file_sha256
from app.core.randomizer import TimelinePlan, TimelineSegment
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition
from app.core.video_processor import ExportOptions
from app.utils.path_utils import normalize_path, ensure_dir


SCHEMA_VERSION = "1.0.0"
MIN_SEGMENT_DURATION = 0.5
FRAME_TOLERANCE_EPSILON = 0.034  # ~1 frame tolerance @ 30 FPS



class ProjectError(Exception):
    """Raised when project validation, loading or saving fails."""
    pass


class AssetMissingError(ProjectError):
    """Raised when one or more assets cannot be found on disk."""
    def __init__(self, missing_files: list[str]):
        self.missing_files = missing_files
        super().__init__(f"项目存在缺失素材 ({len(missing_files)} 个):\n" + "\n".join(missing_files))


@dataclass
class ProjectMeta:
    project_id: str
    project_name: str
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RawAssetManifest:
    audio_path: str
    audio_duration: float
    srt_path: Optional[str] = None
    video_clips: list[str] = field(default_factory=list)
    template_png_path: Optional[str] = None


@dataclass
class VideoTrackSegment:
    segment_id: str
    order_index: int
    clip_path: str
    clip_sha256: str
    display_name: str
    source_start_time: float = 0.0
    duration: float = 0.0
    crop_mode: str = "crop_fill"  # Default 9:16 aspect ratio preserving crop


@dataclass
class SubtitleTrackItem:
    subtitle_id: int
    start_time: float
    end_time: float
    original_text: str
    edited_text: str
    is_modified: bool = False


@dataclass
class RenderSettings:
    output_width: int = 1080
    output_height: int = 1920
    fps: int = 30
    video_bitrate: str = "4M"
    enable_template: bool = True
    template_path: Optional[str] = None
    font_name: str = "Microsoft YaHei"
    font_size: int = 24
    outline_width: int = 2
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    subtitle_position: str = "center"  # "center", "bottom", "top"
    margin_v: int = 100
    margin_l: int = 60
    margin_r: int = 60


@dataclass
class ExportHistoryRecord:
    version: int
    output_path: str
    exported_at: str
    status: str
    elapsed_seconds: float
    error_message: Optional[str] = None


def migrate_v090_to_v100(data: dict) -> dict:
    """Explicit migration logic from v0.9.0/unversioned to v1.0.0."""
    data.setdefault("meta", {})["schema_version"] = "1.0.0"
    data.setdefault("render_settings", {})
    data["render_settings"].setdefault("subtitle_position", "center")
    data["render_settings"].setdefault("enable_template", True)
    data["render_settings"].setdefault("font_name", "Microsoft YaHei")
    data["render_settings"].setdefault("font_size", 24)
    data.setdefault("export_history", [])
    return data


SCHEMA_MIGRATION_CHAIN = [
    ("0.9.0", "1.0.0", migrate_v090_to_v100),
]


def apply_schema_migrations(data: dict) -> dict:
    """Applies sequential schema migrations across versions."""
    current_ver = data.get("meta", {}).get("schema_version", "0.9.0")
    if current_ver == SCHEMA_VERSION:
        return data

    for from_ver, to_ver, mig_fn in SCHEMA_MIGRATION_CHAIN:
        if current_ver == from_ver or (from_ver == "0.9.0" and current_ver != SCHEMA_VERSION):
            data = mig_fn(data)
            current_ver = to_ver
    return data


class EditProject:

    def __init__(
        self,
        meta: ProjectMeta,
        assets: RawAssetManifest,
        video_track: list[VideoTrackSegment],
        subtitle_track: list[SubtitleTrackItem],
        render_settings: RenderSettings,
        export_history: Optional[list[ExportHistoryRecord]] = None
    ):
        self.meta = meta
        self.assets = assets
        self.video_track = sorted(video_track, key=lambda s: s.order_index)
        self.subtitle_track = sorted(subtitle_track, key=lambda s: s.start_time)
        self.render_settings = render_settings
        self.export_history: list[ExportHistoryRecord] = export_history or []

    # =========================================================================
    # Editing Operations (Mutations without affecting independent tracks)
    # =========================================================================

    def reorder_segments(self, segment_ids_in_order: list[str]):
        """
        Reorders video segments according to the specified list of segment_ids.
        Audio and subtitle tracks remain completely untouched.
        """
        seg_dict = {s.segment_id: s for s in self.video_track}
        if set(segment_ids_in_order) != set(seg_dict.keys()):
            raise ValueError("传入的片段 ID 集合与当前项目不符。")

        new_track = []
        for idx, sid in enumerate(segment_ids_in_order):
            seg = seg_dict[sid]
            seg.order_index = idx
            new_track.append(seg)

        self.video_track = new_track
        self._touch()

    def replace_segment(self, segment_id: str, new_clip_path: str, new_sha256: str):
        """
        Replaces the source clip of a segment while preserving its position,
        timeline slot, and duration.
        """
        for seg in self.video_track:
            if seg.segment_id == segment_id:
                seg.clip_path = normalize_path(new_clip_path)
                seg.clip_sha256 = new_sha256
                seg.display_name = Path(new_clip_path).name
                self._touch()
                return
        raise ValueError(f"未找到目标片段: {segment_id}")

    def rebalance_track(self):
        """
        Ensures total video track duration satisfies:
        abs(sum(s.duration) - self.assets.audio_duration) <= FRAME_TOLERANCE_EPSILON.
        The tail segment absorbs any difference.
        """
        if not self.video_track:
            return
        audio_dur = self.assets.audio_duration
        if len(self.video_track) == 1:
            self.video_track[0].duration = round(audio_dur, 3)
            self._touch()
            return

        other_sum = sum(s.duration for s in self.video_track[:-1])
        remaining = audio_dur - other_sum
        if remaining < MIN_SEGMENT_DURATION:
            raise ValueError(
                f"前面片段总时长 ({other_sum:.2f}s) 过长，分配给尾部片段的剩余时长 ({remaining:.2f}s) 小于最小允许值 ({MIN_SEGMENT_DURATION}s)。"
            )
        self.video_track[-1].duration = round(remaining, 3)
        self._touch()

    def update_segment_duration(self, segment_id: str, new_duration: float):
        """
        Updates the duration of a video segment.
        Validates boundaries and re-balances the tail segment.
        Raises ValueError if constraints cannot be satisfied.
        """
        if new_duration < MIN_SEGMENT_DURATION:
            raise ValueError(f"片段时长不能小于 {MIN_SEGMENT_DURATION} 秒。")

        target_idx = -1
        for idx, seg in enumerate(self.video_track):
            if seg.segment_id == segment_id:
                target_idx = idx
                break

        if target_idx == -1:
            raise ValueError(f"未找到目标片段: {segment_id}")

        audio_dur = self.assets.audio_duration
        if len(self.video_track) == 1:
            self.video_track[0].duration = round(audio_dur, 3)
            self._touch()
            return

        if target_idx < len(self.video_track) - 1:
            # Modifying a non-tail segment: check tail remainder
            other_sum = sum(s.duration for i, s in enumerate(self.video_track[:-1]) if i != target_idx)
            remaining_for_tail = audio_dur - (other_sum + new_duration)
            if remaining_for_tail < MIN_SEGMENT_DURATION:
                raise ValueError(
                    f"无法将片段时长设置为 {new_duration:.2f}s：分配给末尾片段的剩余时长 ({remaining_for_tail:.2f}s) 小于允许的最小片段时长 ({MIN_SEGMENT_DURATION}s)。"
                )
            self.video_track[target_idx].duration = round(new_duration, 3)
            self.video_track[-1].duration = round(remaining_for_tail, 3)
        else:
            # Modifying the tail segment directly: preceding segment absorbs
            if len(self.video_track) > 1:
                other_sum = sum(s.duration for s in self.video_track[:-2])
                new_preceding = audio_dur - (other_sum + new_duration)
                if new_preceding < MIN_SEGMENT_DURATION:
                    raise ValueError(
                        f"无法将末尾片段时长设置为 {new_duration:.2f}s：前序片段需缩减至 ({new_preceding:.2f}s)，小于最小允许时长 ({MIN_SEGMENT_DURATION}s)。"
                    )
                self.video_track[-2].duration = round(new_preceding, 3)
                self.video_track[-1].duration = round(new_duration, 3)

        self._touch()

    def move_segment(self, segment_id: str, direction: int):
        """
        Moves a segment up (-1) or down (+1) in the video track.
        Re-indexes and rebalances the tail segment.
        """
        idx = -1
        for i, s in enumerate(self.video_track):
            if s.segment_id == segment_id:
                idx = i
                break
        if idx == -1:
            raise ValueError(f"未找到目标片段: {segment_id}")

        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(self.video_track):
            return  # Already at top or bottom boundary

        self.video_track[idx], self.video_track[target_idx] = self.video_track[target_idx], self.video_track[idx]
        for i, s in enumerate(self.video_track):
            s.order_index = i

        self.rebalance_track()
        self._touch()

    def add_segment(self, clip_path: str, duration: float = 3.0, clip_sha256: str = "", insert_index: Optional[int] = None):
        """
        Adds a new video segment to the track.
        Automatically balances the tail segment.
        """
        if duration < MIN_SEGMENT_DURATION:
            raise ValueError(f"新片段时长不能小于 {MIN_SEGMENT_DURATION}s。")

        norm_path = normalize_path(clip_path)
        new_seg = VideoTrackSegment(
            segment_id=f"seg_{uuid.uuid4().hex[:6]}",
            order_index=len(self.video_track),
            clip_path=norm_path,
            clip_sha256=clip_sha256,
            display_name=Path(norm_path).name,
            source_start_time=0.0,
            duration=round(duration, 3)
        )

        if insert_index is None or insert_index >= len(self.video_track):
            if len(self.video_track) >= 1:
                self.video_track.insert(-1, new_seg)
            else:
                self.video_track.append(new_seg)
        else:
            self.video_track.insert(max(0, insert_index), new_seg)

        for i, s in enumerate(self.video_track):
            s.order_index = i

        self.rebalance_track()
        self._touch()

    def remove_segment(self, segment_id: str):
        """
        Removes a segment from the track.
        At least one segment must remain.
        """
        if len(self.video_track) <= 1:
            raise ValueError("时间轴至少需保留一个视频片段。")

        idx = -1
        for i, s in enumerate(self.video_track):
            if s.segment_id == segment_id:
                idx = i
                break
        if idx == -1:
            raise ValueError(f"未找到目标片段: {segment_id}")

        self.video_track.pop(idx)
        for i, s in enumerate(self.video_track):
            s.order_index = i

        self.rebalance_track()
        self._touch()


    def edit_subtitle_text(self, subtitle_id: int, new_text: str):
        """Edits subtitle text without altering audio content or timing."""
        for sub in self.subtitle_track:
            if sub.subtitle_id == subtitle_id:
                sub.edited_text = new_text.strip()
                sub.is_modified = (sub.edited_text != sub.original_text)
                self._touch()
                return
        raise ValueError(f"未找到字幕 ID: {subtitle_id}")

    def edit_subtitle_timing(self, subtitle_id: int, new_start: float, new_end: float):
        """Edits subtitle timestamp without changing audio."""
        if new_start < 0 or new_end <= new_start:
            raise ValueError("字幕时间戳无效 (需满足 0 <= start < end)。")
        if new_end > self.assets.audio_duration + 1.0:
            raise ValueError("字幕结束时间不可超出音频总时长。")

        for sub in self.subtitle_track:
            if sub.subtitle_id == subtitle_id:
                sub.start_time = round(new_start, 3)
                sub.end_time = round(new_end, 3)
                sub.is_modified = True
                self.subtitle_track.sort(key=lambda s: s.start_time)
                self._touch()
                return
        raise ValueError(f"未找到字幕 ID: {subtitle_id}")

    def add_export_history(self, output_path: str, status: str, elapsed: float, error: Optional[str] = None):
        """Appends an export record with auto-incremented version number."""
        next_ver = len(self.export_history) + 1
        record = ExportHistoryRecord(
            version=next_ver,
            output_path=normalize_path(output_path),
            exported_at=datetime.now().isoformat(),
            status=status,
            elapsed_seconds=round(elapsed, 2),
            error_message=error
        )
        self.export_history.append(record)
        self._touch()

    # =========================================================================
    # Asset Validation & Path Recovery
    # =========================================================================

    def validate_assets(self) -> list[str]:
        """Returns list of missing asset paths on disk."""
        missing = []
        if not Path(self.assets.audio_path).is_file():
            missing.append(self.assets.audio_path)

        if self.assets.srt_path and not Path(self.assets.srt_path).is_file():
            missing.append(self.assets.srt_path)

        if self.assets.template_png_path and not Path(self.assets.template_png_path).is_file():
            missing.append(self.assets.template_png_path)

        for seg in self.video_track:
            if not Path(seg.clip_path).is_file():
                if seg.clip_path not in missing:
                    missing.append(seg.clip_path)

        return missing

    def recover_missing_asset(self, old_path: str, new_path: str, force: bool = False):
        """
        Re-links a missing asset path to a newly located file.
        Verifies SHA-256 file content consistency. If content differs, requires force=True.
        Updates clip_sha256 and display_name.
        """
        norm_old = normalize_path(old_path)
        norm_new = normalize_path(new_path)
        if not Path(norm_new).is_file():
            raise FileNotFoundError(f"新的素材文件不存在: {norm_new}")

        new_sha = calculate_file_sha256(norm_new)

        matched = False
        if self.assets.audio_path == norm_old:
            self.assets.audio_path = norm_new
            matched = True

        if self.assets.srt_path == norm_old:
            self.assets.srt_path = norm_new
            matched = True

        if self.assets.template_png_path == norm_old:
            self.assets.template_png_path = norm_new
            matched = True

        for seg in self.video_track:
            if seg.clip_path == norm_old:
                if seg.clip_sha256 and seg.clip_sha256 != new_sha and not force:
                    raise ValueError(
                        f"素材内容哈希不一致 (原: [{seg.clip_sha256[:8]}], 新: [{new_sha[:8]}]), "
                        f"可能为同名不同内容视频。如确认替换请使用 force=True。"
                    )
                seg.clip_path = norm_new
                seg.clip_sha256 = new_sha
                seg.display_name = Path(norm_new).name
                matched = True

        if not matched:
            raise ValueError(f"项目中未找到引用的旧素材路径: {norm_old}")

        self._touch()


    # =========================================================================
    # Serialization & Atomic Persistence
    # =========================================================================

    def to_dict(self) -> dict:
        return {
            "meta": asdict(self.meta),
            "assets": asdict(self.assets),
            "video_track": [asdict(s) for s in self.video_track],
            "subtitle_track": [asdict(s) for s in self.subtitle_track],
            "render_settings": asdict(self.render_settings),
            "export_history": [asdict(h) for h in self.export_history]
        }

    def save(self, file_path: str | Path):
        """
        Saves project state atomically using a temp file + replace.
        Protects existing project file from being wiped on disk write failures.
        """
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target.parent / f".tmp_{target.name}_{uuid.uuid4().hex[:6]}"

        try:
            self._touch()
            data = self.to_dict()
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Atomic file swap
            if os.name == "nt" and target.exists():
                # On Windows, os.replace is atomic across existing files in same volume
                os.replace(temp_file, target)
            else:
                shutil.move(str(temp_file), str(target))
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            raise ProjectError(f"保存项目文件失败: {e}")

    @staticmethod
    def load(file_path: str | Path) -> "EditProject":
        """
        Loads project from JSON, performs schema migration & field normalization.
        """
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"项目文件不存在: {p}")

        try:
            with open(p, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            raise ProjectError(f"解析项目 JSON 失败 (文件损坏): {e}")

        # Explicit Schema version migration chain
        raw_data = apply_schema_migrations(raw_data)

        # Schema normalization
        meta_d = raw_data.get("meta", {})

        assets_d = raw_data.get("assets", {})
        video_track_d = raw_data.get("video_track", [])
        subtitle_track_d = raw_data.get("subtitle_track", [])
        render_d = raw_data.get("render_settings", {})
        history_d = raw_data.get("export_history", [])

        meta = ProjectMeta(
            project_id=meta_d.get("project_id", f"proj_{uuid.uuid4().hex[:8]}"),
            project_name=meta_d.get("project_name", p.stem),
            schema_version=meta_d.get("schema_version", SCHEMA_VERSION),
            created_at=meta_d.get("created_at", datetime.now().isoformat()),
            updated_at=meta_d.get("updated_at", datetime.now().isoformat())
        )

        assets = RawAssetManifest(
            audio_path=normalize_path(assets_d.get("audio_path", "")),
            audio_duration=float(assets_d.get("audio_duration", 0.0)),
            srt_path=normalize_path(assets_d["srt_path"]) if assets_d.get("srt_path") else None,
            video_clips=[normalize_path(v) for v in assets_d.get("video_clips", [])],
            template_png_path=normalize_path(assets_d["template_png_path"]) if assets_d.get("template_png_path") else None
        )

        video_track = [
            VideoTrackSegment(
                segment_id=s.get("segment_id", f"seg_{i+1:03d}"),
                order_index=s.get("order_index", i),
                clip_path=normalize_path(s.get("clip_path", "")),
                clip_sha256=s.get("clip_sha256", ""),
                display_name=s.get("display_name", Path(s.get("clip_path", "")).name),
                source_start_time=float(s.get("source_start_time", 0.0)),
                duration=float(s.get("duration", 0.0)),
                crop_mode=s.get("crop_mode", "crop_fill")
            )
            for i, s in enumerate(video_track_d)
        ]

        subtitle_track = [
            SubtitleTrackItem(
                subtitle_id=sub.get("subtitle_id", i + 1),
                start_time=float(sub.get("start_time", 0.0)),
                end_time=float(sub.get("end_time", 0.0)),
                original_text=sub.get("original_text", ""),
                edited_text=sub.get("edited_text", sub.get("original_text", "")),
                is_modified=bool(sub.get("is_modified", False))
            )
            for i, sub in enumerate(subtitle_track_d)
        ]

        render_settings = RenderSettings(
            output_width=int(render_d.get("output_width", 1080)),
            output_height=int(render_d.get("output_height", 1920)),
            fps=int(render_d.get("fps", 30)),
            video_bitrate=str(render_d.get("video_bitrate", "4M")),
            enable_template=bool(render_d.get("enable_template", True)),
            template_path=normalize_path(render_d["template_path"]) if render_d.get("template_path") else None,
            font_name=str(render_d.get("font_name", "Microsoft YaHei")),
            font_size=int(render_d.get("font_size", 24)),
            outline_width=int(render_d.get("outline_width", 2)),
            primary_color=str(render_d.get("primary_color", "&H00FFFFFF")),
            outline_color=str(render_d.get("outline_color", "&H00000000")),
            subtitle_position=str(render_d.get("subtitle_position", "center")),
            margin_v=int(render_d.get("margin_v", 100)),
            margin_l=int(render_d.get("margin_l", 60)),
            margin_r=int(render_d.get("margin_r", 60))
        )

        export_history = [
            ExportHistoryRecord(
                version=int(h.get("version", i + 1)),
                output_path=normalize_path(h.get("output_path", "")),
                exported_at=str(h.get("exported_at", "")),
                status=str(h.get("status", "SUCCESS")),
                elapsed_seconds=float(h.get("elapsed_seconds", 0.0)),
                error_message=h.get("error_message")
            )
            for i, h in enumerate(history_d)
        ]

        return EditProject(
            meta=meta,
            assets=assets,
            video_track=video_track,
            subtitle_track=subtitle_track,
            render_settings=render_settings,
            export_history=export_history
        )

    # =========================================================================
    # Pipeline Conversion (Bypassing Randomizer on Re-export)
    # =========================================================================

    def to_timeline_plan(self, plan_id: int = 1) -> TimelinePlan:
        """
        Converts the current edited video track into a deterministic TimelinePlan.
        Bypasses Randomizer shuffle entirely!
        """
        segments = []
        clip_seq = []
        for s in self.video_track:
            segments.append(
                TimelineSegment(
                    clip_path=s.clip_path,
                    clip_sha256=s.clip_sha256,
                    display_name=s.display_name,
                    start_time=s.source_start_time,
                    duration=s.duration
                )
            )
            clip_seq.append(s.display_name)

        return TimelinePlan(
            plan_id=plan_id,
            segments=segments,
            total_duration=round(sum(s.duration for s in segments), 3),
            clip_sequence=clip_seq,
            uniqueness_score=1.0,
            notes=["基于 EditProject 手动时间轴直接导出 (已锁定排列，无随机洗牌)"]
        )

    def to_export_options(self) -> ExportOptions:
        """Builds ExportOptions according to the project's RenderSettings."""
        rs = self.render_settings
        pos_enum = SubtitlePosition.CENTER
        if rs.subtitle_position == "bottom":
            pos_enum = SubtitlePosition.BOTTOM
        elif rs.subtitle_position == "top":
            pos_enum = SubtitlePosition.TOP

        sub_cfg = SubtitleConfig(
            font_name=rs.font_name,
            font_size=rs.font_size,
            primary_color=rs.primary_color,
            outline_color=rs.outline_color,
            outline_width=rs.outline_width,
            position=pos_enum,
            margin_v=rs.margin_v,
            margin_l=rs.margin_l,
            margin_r=rs.margin_r
        )

        tpl_p = rs.template_path or self.assets.template_png_path
        return ExportOptions(
            output_width=rs.output_width,
            output_height=rs.output_height,
            fps=rs.fps,
            video_bitrate=rs.video_bitrate,
            subtitle_config=sub_cfg,
            template_png_path=tpl_p,
            enable_template=rs.enable_template
        )

    def export_edited_srt_file(self, target_srt_path: str | Path) -> str:
        """
        Exports the current subtitle track (incorporating any user edits)
        to a standard SRT file for FFmpeg rendering.
        """
        target = Path(target_srt_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        def sec_to_srt_time(sec: float) -> str:
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            secs = int(sec % 60)
            ms = int(round((sec - int(sec)) * 1000))
            return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

        lines = []
        for i, sub in enumerate(self.subtitle_track):
            lines.append(str(i + 1))
            t_start = sec_to_srt_time(sub.start_time)
            t_end = sec_to_srt_time(sub.end_time)
            lines.append(f"{t_start} --> {t_end}")
            lines.append(sub.edited_text)
            lines.append("")

        content = "\n".join(lines)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def _touch(self):
        self.meta.updated_at = datetime.now().isoformat()


def create_project(
    project_name: str,
    audio_path: str,
    audio_duration: float,
    srt_path: Optional[str],
    video_clips: list[str],
    template_png_path: Optional[str] = None,
    initial_segments: Optional[list[VideoTrackSegment]] = None,
    initial_subtitles: Optional[list[SubtitleTrackItem]] = None,
    render_settings: Optional[RenderSettings] = None
) -> EditProject:
    """Factory function to initialize a new EditProject."""
    meta = ProjectMeta(
        project_id=f"proj_{uuid.uuid4().hex[:8]}",
        project_name=project_name
    )

    manifest = RawAssetManifest(
        audio_path=normalize_path(audio_path),
        audio_duration=audio_duration,
        srt_path=normalize_path(srt_path) if srt_path else None,
        video_clips=[normalize_path(v) for v in video_clips],
        template_png_path=normalize_path(template_png_path) if template_png_path else None
    )

    return EditProject(
        meta=meta,
        assets=manifest,
        video_track=initial_segments or [],
        subtitle_track=initial_subtitles or [],
        render_settings=render_settings or RenderSettings()
    )
