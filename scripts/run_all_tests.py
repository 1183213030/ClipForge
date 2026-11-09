"""
Comprehensive Test Runner for ClipForge:
Executes and benchmarks all project test suites from Stage 1 through Stage 5.6.3,
capturing exact exit codes, stdout, stderr, and test case counts.
"""

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Force UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

TEST_SUITES = [
    {
        "stage": "Stage 1",
        "description": "基础视频混剪、音画对齐与字幕烧录",
        "command": [sys.executable, "tests/test_stage1.py"]
    },
    {
        "stage": "Stage 2",
        "description": "素材去重打散、无相邻重复与种子复现",
        "command": [sys.executable, "tests/test_stage2.py"]
    },
    {
        "stage": "Stage 3",
        "description": "批量小说推文自动化处理与导出 Manifest",
        "command": [sys.executable, "tests/test_stage3.py"]
    },
    {
        "stage": "Stage 4",
        "description": "PySide6 主界面集成与交互响应",
        "command": [sys.executable, "tests/test_stage4_gui.py"]
    },
    {
        "stage": "Stage 5.1 & 5.2",
        "description": "核心渲染加固、推文模板与智能换行",
        "command": [sys.executable, "tests/test_stage5_core.py"]
    },
    {
        "stage": "Stage 5.3",
        "description": "EditProject 数据模型、持久化与原子保存",
        "command": [sys.executable, "tests/test_stage5_project.py"]
    },
    {
        "stage": "Stage 5.4",
        "description": "轻量编辑工作台 GUI 交互与确定性重导",
        "command": [sys.executable, "tests/test_stage5_workbench.py"]
    },
    {
        "stage": "Stage 5.6.1",
        "description": "滤镜脚本化解耦、临时文件清理与 CPS 诊断",
        "command": [sys.executable, "tests/test_stage5_filter_script.py"]
    },
    {
        "stage": "Stage 5.6.3",
        "description": "字号控制、持久化同步与确定性重导计划",
        "command": [sys.executable, "-m", "unittest", "tests/test_stage5_font_and_reexport.py"]
    }
]


def main():
    print("=" * 80)
    print(">>> ClipForge 全阶段自动化测试执行与回归体检")
    print("=" * 80)

    results = []
    total_passed = 0
    total_failed = 0

    for item in TEST_SUITES:
        stage = item["stage"]
        desc = item["description"]
        cmd = item["command"]
        cmd_str = " ".join(cmd)

        print(f"\n[Running] {stage}: {desc}")
        print(f"  Command: {cmd_str}")

        start_t = time.time()
        p = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace"
        )
        elapsed = time.time() - start_t

        is_success = (p.returncode == 0)
        status = "PASS" if is_success else "FAIL"

        if is_success:
            total_passed += 1
            print(f"  Result: [{status}] ExitCode=0, Elapsed={elapsed:.2f}s")
        else:
            total_failed += 1
            print(f"  Result: [{status}] ExitCode={p.returncode}, Elapsed={elapsed:.2f}s")
            print(f"  STDERR: {p.stderr[:300]}")

        results.append({
            "stage": stage,
            "description": desc,
            "command": cmd_str,
            "exit_code": p.returncode,
            "status": status,
            "elapsed_seconds": round(elapsed, 2),
            "stdout_tail": p.stdout[-300:] if p.stdout else "",
            "stderr_tail": p.stderr[-300:] if p.stderr else ""
        })

    print("\n" + "=" * 80)
    print(f">>> 全阶段回归测试汇总: 共 {len(TEST_SUITES)} 套测试，通过: {total_passed}，失败: {total_failed}")
    print("=" * 80)

    out_json = PROJECT_ROOT / "output" / "inspection_stage5_6_3" / "full_regression_results.json"
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"回归汇总已写入: {out_json.name}")


if __name__ == "__main__":
    main()
