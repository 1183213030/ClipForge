import os
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.services.task_service import TaskRecord, TaskState
from app.core.randomizer import TimelinePlan
from app.core.video_processor import ExportOptions
from app.core.edit_project import EditProject

def run():
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Target directories
    out_dir = PROJECT_ROOT / "docs" / "ui_screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    artifact_dir = Path(r"C:\Users\123\.gemini\antigravity\brain\7aa825f9-f09c-4552-acbd-1c1d088ad80b\screenshots")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    win = MainWindow(project_root=PROJECT_ROOT)
    win.resize(1366, 860)
    win.show()
    app.processEvents()

    # --- Populate Batch Mix (Page 0) with realistic data ---
    try:
        win.asset_card.audio_input.setText("audio_novel_chapter_01.mp3")
        win.asset_card.audio_info_lbl.setText("时长: 03:25 | 44.1kHz 双声道立体声 (已探测)")
        win.asset_card.audio_info_lbl.setStyleSheet("color: #34d399; font-size: 11px;")
        
        win.asset_card.srt_input.setText("subtitles_chapter_01.srt")
        win.asset_card.srt_info_lbl.setText("字幕文件就绪: 84 条对齐字幕 (UTF-8)")
        win.asset_card.srt_info_lbl.setStyleSheet("color: #34d399; font-size: 11px;")

        win.asset_card.folder_input.setText("D:/Media/ShortClips/4K_Relaxing_Footage")
        
        win.asset_card.template_input.setText("resources/templates/customer_template.png")
        win.asset_card.template_info_lbl.setText("模板已就绪: 1080x1920 (含右上角角标与底部声明)")
        win.asset_card.template_info_lbl.setStyleSheet("color: #34d399; font-size: 11px;")

        # Populate Task List
        dummy_plan = TimelinePlan(plan_id=1, total_duration=205.0)
        dummy_opts = ExportOptions()
        
        t1 = TaskRecord(
            task_id="TASK_001",
            output_filename="clipforge_batch_001.mp4",
            plan=dummy_plan,
            audio_path="audio.mp3",
            srt_path="sub.srt",
            output_dir="output",
            options=dummy_opts,
            state=TaskState.SUCCESS,
            progress=1.0,
            target_duration=205.0,
            elapsed_seconds=54.2,
            final_output_path="D:/Tools/ClipForge/output/clipforge_batch_001.mp4"
        )
        t2 = TaskRecord(
            task_id="TASK_002",
            output_filename="clipforge_batch_002.mp4",
            plan=dummy_plan,
            audio_path="audio.mp3",
            srt_path="sub.srt",
            output_dir="output",
            options=dummy_opts,
            state=TaskState.RUNNING,
            progress=0.68,
            target_duration=205.0,
            elapsed_seconds=36.8
        )
        t3 = TaskRecord(
            task_id="TASK_003",
            output_filename="clipforge_batch_003.mp4",
            plan=dummy_plan,
            audio_path="audio.mp3",
            srt_path="sub.srt",
            output_dir="output",
            options=dummy_opts,
            state=TaskState.PENDING,
            progress=0.0,
            target_duration=205.0,
            elapsed_seconds=0.0
        )
        
        from app.ui.widgets.task_item_widget import TaskItemWidget
        for t in [t1, t2, t3]:
            tw = TaskItemWidget(t, win.icons_dir)
            win.task_widgets[t.task_id] = tw
            win.task_container_layout.insertWidget(win.task_container_layout.count() - 1, tw)

        win.overall_progress_bar.setValue(56)
        win.lbl_stat_total.setText("总任务: 3")
        win.lbl_stat_running.setText("导出中: 1")
        win.lbl_stat_success.setText("成功: 1")
        win.lbl_stat_failed.setText("失败: 0")
        win.btn_cancel_all.setEnabled(True)
        win.btn_view_manifest.setEnabled(True)
    except Exception as e:
        print(f"Error populating batch data: {e}")

    for _ in range(15):
        app.processEvents()

    # Capture Batch Mix
    batch_img = win.grab()
    batch_p1 = out_dir / "current_batch_mix.png"
    batch_p2 = artifact_dir / "current_batch_mix.png"
    batch_img.save(str(batch_p1))
    batch_img.save(str(batch_p2))
    print(f"Saved batch: {batch_p1}")

    # --- Switch to Workbench (Page 1) and populate ---
    win._switch_page(1)
    for _ in range(15):
        app.processEvents()

    sample_proj_file = PROJECT_ROOT / "temp" / "test_roundtrip_loop.clipforge"
    if sample_proj_file.is_file():
        try:
            proj = EditProject.load(sample_proj_file)
            win.workbench_page.set_project(proj, sample_proj_file)
            print("Loaded test_roundtrip_loop.clipforge successfully")
        except Exception as e:
            print(f"Error loading project: {e}")

    for _ in range(20):
        app.processEvents()

    workbench_img = win.grab()
    wb_p1 = out_dir / "current_workbench.png"
    wb_p2 = artifact_dir / "current_workbench.png"
    workbench_img.save(str(wb_p1))
    workbench_img.save(str(wb_p2))
    print(f"Saved workbench: {wb_p1}")

    win.close()
    print("All captures completed successfully!")

if __name__ == "__main__":
    run()
