"""
Unit tests for multi-novel batch management, directory auto-pairing (Option A),
multi-file pairing (Option B), and multi-task pipeline generation.
"""

from pathlib import Path
import pytest
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from app.core.novel_task import NovelTaskItem, NovelBatchMatcher
from app.core.media_scanner import ScanResult, ClipInfo
from app.core.randomizer import TimelinePlan, TimelineSegment
from app.core.video_processor import ExportOptions
from app.services.task_service import TaskService, TaskState


@pytest.fixture
def temp_novel_dir():
    """Creates a temporary folder with mock audio and subtitle files for 3 novels."""
    d = Path(tempfile.mkdtemp(prefix="clipforge_test_novels_"))
    try:
        # Novel 1: exact match
        (d / "novel_01.mp3").write_text("dummy audio 1", encoding="utf-8")
        (d / "novel_01.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello 1", encoding="utf-8")

        # Novel 2: case-insensitive match
        (d / "Novel_02_Fight.WAV").write_text("dummy audio 2", encoding="utf-8")
        (d / "novel_02_fight.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello 2", encoding="utf-8")

        # Novel 3: audio without subtitle
        (d / "novel_03_no_sub.m4a").write_text("dummy audio 3", encoding="utf-8")

        # Orphan subtitle without audio
        (d / "orphan_without_audio.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nOrphan", encoding="utf-8")

        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_novel_batch_matcher_pair_files():
    audios = ["/path/to/novel_a.mp3", "/path/to/NOVEL_B.WAV", "/path/to/novel_c.m4a"]
    srts = ["/path/to/novel_a.srt", "/path/to/novel_b.srt", "/path/to/orphan.srt"]

    tasks, orphans = NovelBatchMatcher.pair_files(
        audio_paths=audios,
        srt_paths=srts,
        probe_durations=False,
        default_count=2
    )

    assert len(tasks) == 3
    # Sorted by name deterministically
    task_map = {t.novel_title.lower(): t for t in tasks}

    assert "novel_a" in task_map
    assert task_map["novel_a"].srt_path is not None
    assert Path(task_map["novel_a"].srt_path).name == "novel_a.srt"
    assert task_map["novel_a"].export_count == 2

    assert "novel_b" in task_map
    assert task_map["novel_b"].srt_path is not None
    assert Path(task_map["novel_b"].srt_path).name == "novel_b.srt"

    assert "novel_c" in task_map
    assert task_map["novel_c"].srt_path is None

    assert len(orphans) == 1
    assert "orphan.srt" in orphans[0]


def test_novel_batch_matcher_scan_folder(temp_novel_dir):
    with patch("app.core.novel_task.probe_media") as mock_probe:
        mock_meta = MagicMock()
        mock_meta.is_valid_audio = True
        mock_meta.duration = 42.5
        mock_meta.audio_codec = "aac"
        mock_probe.return_value = mock_meta

        tasks, orphans = NovelBatchMatcher.scan_and_pair_folder(
            folder_path=temp_novel_dir,
            recursive=False,
            probe_durations=True,
            default_count=1
        )

        assert len(tasks) == 3
        # Ensure probed duration
        for t in tasks:
            assert t.is_valid is True
            assert t.audio_duration == 42.5
            assert "00:42.5" in t.formatted_duration

        # Check orphan detection
        assert len(orphans) == 1
        assert "orphan_without_audio.srt" in orphans[0]


def test_multi_novel_task_service_queue():
    """Verify that multiple novel tasks can be scheduled into TaskService with distinct prefixes."""
    log_dir = Path(tempfile.mkdtemp(prefix="clipforge_test_logs_"))
    try:
        service = TaskService(log_dir=log_dir)

        # Create mock TimelinePlans
        plan1 = TimelinePlan(
            plan_id=1,
            segments=[TimelineSegment(clip_path="c1.mp4", clip_sha256="h1", display_name="c1.mp4", start_time=0.0, duration=10.0)],
            total_duration=10.0
        )
        plan2 = TimelinePlan(
            plan_id=2,
            segments=[TimelineSegment(clip_path="c2.mp4", clip_sha256="h2", display_name="c2.mp4", start_time=0.0, duration=15.0)],
            total_duration=15.0
        )

        opts = ExportOptions()

        # Novel 1
        tasks1 = service.create_batch(
            plans=[plan1],
            audio_path="novel1.mp3",
            srt_path="novel1.srt",
            output_dir=str(log_dir),
            options=opts,
            filename_prefix="小说1_第一章"
        )

        # Novel 2
        tasks2 = service.create_batch(
            plans=[plan2],
            audio_path="novel2.mp3",
            srt_path="novel2.srt",
            output_dir=str(log_dir),
            options=opts,
            filename_prefix="小说2_第一章"
        )

        assert len(service.tasks) == 2
        assert service.tasks[0].task_id == "TASK_001"
        assert service.tasks[0].output_filename == "小说1_第一章_001.mp4"
        assert service.tasks[0].target_duration == 10.0

        assert service.tasks[1].task_id == "TASK_002"
        assert service.tasks[1].output_filename == "小说2_第一章_001.mp4"
        assert service.tasks[1].target_duration == 15.0

        stats = service.get_statistics()
        assert stats.total == 2
        assert stats.pending == 2

        service.clear_all_tasks()
        assert len(service.tasks) == 0
    finally:
        shutil.rmtree(log_dir, ignore_errors=True)


def test_asset_card_mode_switching_and_gui():
    """Verify GUI mode switching and task table interaction."""
    import sys
    from PySide6.QtWidgets import QApplication
    from app.ui.widgets.asset_card import AssetCardWidget

    app = QApplication.instance() or QApplication(sys.argv)
    project_root = Path(__file__).resolve().parent.parent
    icons_dir = project_root / "resources" / "icons"

    widget = AssetCardWidget(icons_dir=icons_dir)
    assert widget.is_batch_mode is False
    assert widget.novel_stack.currentIndex() == 0

    # Switch to batch mode
    widget.set_mode(True)
    assert widget.is_batch_mode is True
    assert widget.novel_stack.currentIndex() == 1

    # Add 2 novel tasks to the batch widget
    t1 = NovelTaskItem(
        task_id="T01",
        novel_title="小说A",
        audio_path="a.mp3",
        srt_path="a.srt",
        audio_duration=50.0,
        export_count=1
    )
    t2 = NovelTaskItem(
        task_id="T02",
        novel_title="小说B",
        audio_path="b.mp3",
        srt_path=None,
        audio_duration=75.0,
        export_count=2
    )

    widget.novel_batch_widget.add_task(t1)
    widget.novel_batch_widget.add_task(t2)

    tasks = widget.get_novel_tasks()
    assert len(tasks) == 2
    assert tasks[0].novel_title == "小说A"
    assert tasks[1].export_count == 2
    assert widget.novel_batch_widget.table.rowCount() == 2

    # Switch back to single mode
    widget.set_mode(False)
    assert widget.is_batch_mode is False
    assert widget.novel_stack.currentIndex() == 0

