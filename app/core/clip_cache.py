"""
Clip Standardization & Asset Pre-processing Cache for ClipForge.
Eliminates redundant 4K decoding, software scaling, cropping, and framerate conversion
across repeated clip loops and multi-video batch exports.
"""

from collections import OrderedDict
import concurrent.futures
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import threading
from typing import Callable, Optional
import uuid

from app.core.media_probe import probe_media
from app.utils.ffmpeg_utils import get_ffmpeg_path, FFmpegError
from app.utils.path_utils import normalize_path, ensure_dir

logger = logging.getLogger(__name__)

# Default disk budget for standardized clip cache (4 GB)
DEFAULT_MAX_CACHE_BYTES = 4 * 1024 * 1024 * 1024


class ClipStandardizationCache:
    """
    Thread-safe, disk-backed cache storing standardized intermediate clips
    (exact target width x height, CFR fps, yuv420p, SAR 1:1, no audio, no B-frames).
    Also caches pre-transcoded AAC audio and pre-scaled template PNGs.
    """

    def __init__(
        self,
        cache_dir: str | Path = "temp/clip_cache",
        max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        ffmpeg_path: Optional[str] = None,
    ):
        self.cache_dir = ensure_dir(cache_dir)
        self.max_cache_bytes = max_cache_bytes
        self.ffmpeg_path = ffmpeg_path or get_ffmpeg_path()

        self._global_lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._meta_cache: dict[str, tuple[int, int, float, float]] = {}  # key -> (w, h, fps, dur)

    def _get_key_lock(self, key: str) -> threading.Lock:
        with self._global_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    @staticmethod
    def _file_fingerprint(file_path: str | Path) -> str:
        """Computes a fast deterministic fingerprint from canonical path, size, and mtime_ns."""
        p = Path(file_path).resolve()
        st = p.stat()
        raw = f"{str(p).lower()}|{st.st_size}|{st.st_mtime_ns}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _clip_cache_key(self, file_path: str | Path, width: int, height: int, fps: int) -> str:
        fp = self._file_fingerprint(file_path)
        return f"clip_{fp}_{width}x{height}_{fps}fps"

    def get_cached_clip_path(
        self,
        file_path: str | Path,
        width: int,
        height: int,
        fps: int,
    ) -> Optional[Path]:
        """Returns existing valid cached clip path if present, else None."""
        try:
            key = self._clip_cache_key(file_path, width, height, fps)
        except OSError:
            return None
        target = self.cache_dir / f"{key}.mp4"
        if target.is_file() and target.stat().st_size > 10 * 1024:
            return target
        return None

    def get_source_info(self, file_path: str | Path) -> tuple[int, int, float, float]:
        """Returns cached (width, height, fps, duration) for a source video file."""
        fp = self._file_fingerprint(file_path)
        with self._global_lock:
            cached = self._meta_cache.get(fp)
            if cached is not None:
                return cached
        meta = probe_media(file_path)
        info = (meta.width, meta.height, meta.fps, meta.duration)
        with self._global_lock:
            self._meta_cache[fp] = info
        return info

    def get_or_create_clip(
        self,
        file_path: str | Path,
        width: int,
        height: int,
        fps: int,
        threads: Optional[int] = None,
        token=None,
    ) -> Path:
        """
        Returns a standardized intermediate MP4 path for `file_path`.
        Thread-safe: concurrent callers requesting the same clip wait on a per-key lock
        so the transcode runs strictly once.
        """
        norm_src = normalize_path(file_path)
        key = self._clip_cache_key(norm_src, width, height, fps)
        target = self.cache_dir / f"{key}.mp4"

        # Fast path without acquiring key lock
        if target.is_file() and target.stat().st_size > 10 * 1024:
            self._touch_file(target)
            return target

        lock = self._get_key_lock(key)
        with lock:
            if target.is_file() and target.stat().st_size > 10 * 1024:
                self._touch_file(target)
                return target

            if token and token.is_cancelled:
                from app.core.video_processor import TaskCancelledError
                raise TaskCancelledError("任务已被用户取消。")

            # Inspect source video fps/resolution to pick the optimal filter order
            src_w, src_h, src_fps, _ = self.get_source_info(norm_src)

            scale_crop = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=bilinear,"
                f"crop={width}:{height},setsar=1"
            )
            fps_filter = f"fps=fps={fps}:round=near:start_time=0"

            if src_w == width and src_h == height:
                # Resolution already matches; avoid unnecessary scaling
                vf = f"setsar=1,{fps_filter}"
            elif src_fps > fps + 0.5:
                # Down-converting framerate (e.g. 60fps -> 30fps): drop excess frames BEFORE scaling!
                vf = f"{fps_filter},{scale_crop}"
            else:
                # Up-converting or equal framerate (e.g. 25fps -> 30fps): scale fewer frames BEFORE duplicating!
                vf = f"{scale_crop},{fps_filter}"

            temp_out = self.cache_dir / f".tmp_{key}_{uuid.uuid4().hex[:6]}.mp4"
            cmd = [
                self.ffmpeg_path, "-y",
                "-an", "-sn", "-dn",
                "-i", norm_src,
                "-vf", vf,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "17",
                "-tune", "fastdecode",
                "-bf", "0",
                "-g", str(max(15, fps)),
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-video_track_timescale", str(fps * 1000),
            ]
            if threads and threads > 0:
                cmd.extend(["-threads", str(threads)])
            cmd.append(str(temp_out))

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    encoding="utf-8",
                    errors="replace",
                )
                if token:
                    token.bind_process(process)
                _, stderr = process.communicate()

                if token and token.is_cancelled:
                    from app.core.video_processor import TaskCancelledError
                    raise TaskCancelledError("任务已被用户取消。")

                if process.returncode != 0:
                    raise FFmpegError(f"素材预标准化失败 ({Path(norm_src).name}):\n{stderr[-500:]}")

                if not temp_out.is_file() or temp_out.stat().st_size < 1024:
                    raise FFmpegError(f"素材预标准化输出无效 ({Path(norm_src).name})")

                # Atomic swap into final cache slot
                os.replace(temp_out, target)
                self._enforce_cache_budget()
                return target
            except Exception:
                if process and process.poll() is None:
                    try:
                        process.kill()
                    except Exception:
                        pass
                if temp_out.exists():
                    try:
                        temp_out.unlink()
                    except Exception:
                        pass
                raise

    def prewarm_clips(
        self,
        clip_paths: list[str],
        width: int,
        height: int,
        fps: int,
        max_workers: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict[str, Path]:
        """
        Pre-standardizes a deduplicated list of clips in parallel before a batch export starts.
        Returns mapping: normalized source path -> cached standardized Path.
        """
        unique_paths: list[str] = list(OrderedDict.fromkeys(normalize_path(p) for p in clip_paths if p))
        total = len(unique_paths)
        if total == 0:
            return {}

        # Separate already-cached from missing
        result: dict[str, Path] = {}
        to_process: list[str] = []
        for p in unique_paths:
            existing = self.get_cached_clip_path(p, width, height, fps)
            if existing is not None:
                self._touch_file(existing)
                result[p] = existing
            else:
                to_process.append(p)

        completed = len(result)
        if on_progress and completed > 0:
            try:
                on_progress(completed, total, "命中缓存")
            except Exception:
                pass

        if not to_process:
            return result

        cpu = os.cpu_count() or 4
        workers = max_workers or max(2, min(4, len(to_process), cpu // 2))
        per_worker_threads = max(2, cpu // workers)

        def _worker(src_path: str) -> tuple[str, Path]:
            if cancel_check and cancel_check():
                from app.core.video_processor import TaskCancelledError
                raise TaskCancelledError("素材预处理已取消。")
            cached_p = self.get_or_create_clip(
                src_path,
                width=width,
                height=height,
                fps=fps,
                threads=per_worker_threads,
            )
            return src_path, cached_p

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_worker, p): p for p in to_process}
            for fut in concurrent.futures.as_completed(future_map):
                if cancel_check and cancel_check():
                    for pending_f in future_map:
                        pending_f.cancel()
                    break
                src_p, cached_p = fut.result()
                result[src_p] = cached_p
                completed += 1
                if on_progress:
                    try:
                        on_progress(completed, total, Path(src_p).name)
                    except Exception:
                        pass

        return result

    def prepare_audio_aac(
        self,
        audio_path: str | Path,
        audio_bitrate: str = "128k",
        audio_samplerate: int = 44100,
    ) -> Optional[Path]:
        """
        Pre-transcodes a shared audio track to AAC (.m4a) once so all tasks in a batch
        can stream-copy (`-c:a copy`) with zero redundant audio encoding.
        """
        norm_audio = normalize_path(audio_path)
        try:
            fp = self._file_fingerprint(norm_audio)
        except OSError:
            return None

        key = f"audio_{fp}_{audio_bitrate}_{audio_samplerate}"
        target = self.cache_dir / f"{key}.m4a"
        if target.is_file() and target.stat().st_size > 1024:
            self._touch_file(target)
            return target

        lock = self._get_key_lock(key)
        with lock:
            if target.is_file() and target.stat().st_size > 1024:
                self._touch_file(target)
                return target

            temp_out = self.cache_dir / f".tmp_{key}_{uuid.uuid4().hex[:6]}.m4a"
            cmd = [
                self.ffmpeg_path, "-y",
                "-vn", "-sn", "-dn",
                "-i", norm_audio,
                "-c:a", "aac",
                "-b:a", audio_bitrate,
                "-ar", str(audio_samplerate),
                str(temp_out),
            ]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    startupinfo=startupinfo,
                    timeout=120,
                )
                if res.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 1024:
                    os.replace(temp_out, target)
                    return target
            except Exception as exc:
                logger.warning(f"音频预转码缓存失败，将回退至单任务实时编码: {exc}")
            finally:
                if temp_out.exists():
                    try:
                        temp_out.unlink()
                    except Exception:
                        pass
            return None

    def prepare_template_png(
        self,
        template_path: str | Path,
        width: int,
        height: int,
    ) -> Path:
        """
        Returns a PNG guaranteed to match (width, height), pre-scaling once via Pillow
        if dimensions differ, avoiding redundant per-frame FFmpeg software scaling.
        """
        norm_tpl = Path(normalize_path(template_path))
        try:
            from PIL import Image
            with Image.open(norm_tpl) as im:
                if im.size == (width, height) and im.mode == "RGBA":
                    return norm_tpl
                fp = self._file_fingerprint(norm_tpl)
                key = f"tpl_{fp}_{width}x{height}"
                target = self.cache_dir / f"{key}.png"
                if target.is_file() and target.stat().st_size > 100:
                    return target
                lock = self._get_key_lock(key)
                with lock:
                    if target.is_file() and target.stat().st_size > 100:
                        return target
                    resized = im.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
                    temp_out = self.cache_dir / f".tmp_{key}_{uuid.uuid4().hex[:6]}.png"
                    resized.save(temp_out, format="PNG")
                    os.replace(temp_out, target)
                    return target
        except Exception as exc:
            logger.debug(f"预缩放模板 PNG 失败，交由 FFmpeg 缩放: {exc}")
            return norm_tpl

    def _touch_file(self, path: Path):
        try:
            os.utime(path, None)
        except Exception:
            pass

    def _enforce_cache_budget(self):
        """Evicts oldest cached files if total cache size exceeds `max_cache_bytes`."""
        try:
            entries = []
            total_size = 0
            for f in self.cache_dir.iterdir():
                if not f.is_file() or f.name.startswith(".tmp_"):
                    continue
                st = f.stat()
                total_size += st.st_size
                entries.append((st.st_mtime, st.st_size, f))

            if total_size <= self.max_cache_bytes:
                return

            entries.sort(key=lambda item: item[0])  # Oldest first
            target_size = int(self.max_cache_bytes * 0.8)
            for _, sz, f in entries:
                if total_size <= target_size:
                    break
                try:
                    f.unlink()
                    total_size -= sz
                except Exception:
                    pass
        except Exception:
            pass
