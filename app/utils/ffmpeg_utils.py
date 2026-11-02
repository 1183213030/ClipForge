"""
FFmpeg Utility Module for ClipForge.
Discovers binaries, manages subprocess executions, and monitors progress.
"""

from pathlib import Path
import os
import shutil
import subprocess
from typing import Callable, Optional


class FFmpegError(Exception):
    """Raised when an FFmpeg or FFprobe command fails."""
    pass


def find_ffmpeg_binaries() -> tuple[Optional[str], Optional[str]]:
    """
    Locates ffmpeg and ffprobe executables in order of precedence:
    1. <project_root>/bin/ffmpeg.exe (and ffprobe.exe)
    2. Python imageio-ffmpeg bundle (for ffmpeg)
    3. System PATH
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    local_bin = project_root / "bin"
    
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None
    
    # 1. Local bin folder
    local_ffmpeg = local_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    local_ffprobe = local_bin / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if local_ffmpeg.is_file():
        ffmpeg_path = str(local_ffmpeg)
    if local_ffprobe.is_file():
        ffprobe_path = str(local_ffprobe)
        
    # 2. imageio-ffmpeg for ffmpeg if not found in local bin
    if not ffmpeg_path:
        try:
            import imageio_ffmpeg
            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and os.path.isfile(bundled):
                ffmpeg_path = bundled
                # Check if ffprobe sits in the same directory
                candidate_ffprobe = Path(bundled).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
                if candidate_ffprobe.is_file() and not ffprobe_path:
                    ffprobe_path = str(candidate_ffprobe)
        except Exception:
            pass
            
    # 3. System PATH fallback
    if not ffmpeg_path:
        which_ffmpeg = shutil.which("ffmpeg")
        if which_ffmpeg:
            ffmpeg_path = which_ffmpeg
            
    if not ffprobe_path:
        which_ffprobe = shutil.which("ffprobe")
        if which_ffprobe:
            ffprobe_path = which_ffprobe
            
    return ffmpeg_path, ffprobe_path


def get_ffmpeg_path() -> str:
    """Returns valid ffmpeg executable path or raises FFmpegError."""
    ffmpeg, _ = find_ffmpeg_binaries()
    if not ffmpeg:
        raise FFmpegError("未找到 FFmpeg 可执行程序，请将其放置于 bin/ 目录或添加到系统 PATH 中。")
    return ffmpeg


def get_ffprobe_path() -> Optional[str]:
    """Returns ffprobe executable path if available, or None."""
    _, ffprobe = find_ffmpeg_binaries()
    return ffprobe


def run_command(
    cmd: list[str],
    timeout_sec: Optional[float] = None,
    on_stderr_line: Optional[Callable[[str], None]] = None
) -> subprocess.CompletedProcess[str]:
    """
    Executes a CLI command safely with UTF-8 encoding support,
    optionally capturing stderr stream line-by-line.
    """
    startupinfo = None
    if os.name == "nt":
        # Hide console window on Windows
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        startupinfo=startupinfo,
        encoding="utf-8",
        errors="replace"
    )

    stderr_lines = []
    try:
        # If line callback provided, process stderr live
        if on_stderr_line:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_lines.append(line)
                on_stderr_line(line)
            stdout, _ = process.communicate(timeout=timeout_sec)
            stderr = "".join(stderr_lines)
        else:
            stdout, stderr = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        process.kill()
        raise FFmpegError(f"执行命令超时 ({timeout_sec}s): {' '.join(cmd)}")
    except Exception as e:
        process.kill()
        raise FFmpegError(f"执行命令异常: {e}")

    ret_code = process.poll()
    if ret_code != 0:
        raise FFmpegError(
            f"命令执行失败 (退出代码: {ret_code}):\n{' '.join(cmd)}\n错误详情:\n{stderr[-1000:]}"
        )

    return subprocess.CompletedProcess(cmd, ret_code, stdout, stderr)
