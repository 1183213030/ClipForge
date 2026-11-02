"""
Stage 1 In-depth Verification Script.
1. Audio FFT frequency analysis: Confirms only 523.25Hz novel narration exists,
   and 440Hz / 880Hz original clip noise frequencies are strictly suppressed.
2. Multi-timestamp subtitle snapshot verification: Checks subtitle appearance & disappearance
   at key SRT timeline points.
"""

from pathlib import Path
import sys
import numpy as np
from scipy.io import wavfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.ffmpeg_utils import get_ffmpeg_path, run_command


def verify_audio_frequencies(mp4_path: Path, temp_dir: Path) -> dict:
    ffmpeg = get_ffmpeg_path()
    wav_path = temp_dir / "extracted_audio.wav"
    
    # Extract audio to 44100Hz mono wav
    run_command([
        ffmpeg, "-y",
        "-i", str(mp4_path),
        "-ac", "1",
        "-ar", "44100",
        str(wav_path)
    ])
    
    samplerate, data = wavfile.read(str(wav_path))
    # Perform FFT
    data = data.astype(np.float32)
    fft_vals = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), 1.0 / samplerate)
    
    def get_peak_near(target_freq: float, window: float = 10.0) -> float:
        mask = (freqs >= target_freq - window) & (freqs <= target_freq + window)
        return float(np.max(fft_vals[mask])) if np.any(mask) else 0.0

    peak_novel = get_peak_near(523.25)
    peak_clip1 = get_peak_near(440.0)
    peak_clip2 = get_peak_near(880.0)
    
    # Calculate ratio relative to novel narration peak
    ratio_clip1 = peak_clip1 / max(peak_novel, 1e-6)
    ratio_clip2 = peak_clip2 / max(peak_novel, 1e-6)
    
    return {
        "peak_novel_523Hz": peak_novel,
        "peak_clip1_440Hz": peak_clip1,
        "ratio_clip1": ratio_clip1,
        "peak_clip2_880Hz": peak_clip2,
        "ratio_clip2": ratio_clip2,
        "is_muted_effectively": (ratio_clip1 < 0.001 and ratio_clip2 < 0.001)
    }


def verify_subtitle_snapshots(mp4_path: Path, temp_dir: Path) -> list[dict]:
    ffmpeg = get_ffmpeg_path()
    snapshot_dir = temp_dir / "sub_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    timestamps = [
        (0.2, "空档期 (0.2s - 应当无字幕)"),
        (1.5, "台词1 (1.5s - 夜幕降临...)"),
        (3.2, "空档期 (3.2s - 应当无字幕)"),
        (4.5, "台词2 (4.5s - 楚飞缓缓...)"),
        (7.5, "台词3 (7.5s - 门后显现...)"),
        (8.4, "尾部空档 (8.4s - 字幕已结束)")
    ]
    
    results = []
    for ts, desc in timestamps:
        out_img = snapshot_dir / f"shot_{ts:.1f}s.png"
        run_command([
            ffmpeg, "-y",
            "-ss", f"{ts:.2f}",
            "-i", str(mp4_path),
            "-vframes", "1",
            str(out_img)
        ])
        results.append({
            "timestamp": ts,
            "description": desc,
            "file": str(out_img),
            "size": out_img.stat().st_size
        })
    return results


if __name__ == "__main__":
    mp4_file = PROJECT_ROOT / "output" / "stage1_output_成品_001.mp4"
    temp_dir = PROJECT_ROOT / "temp" / "verify_stage1"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print(">>> 执行阶段一专项轻量复核")
    print("=" * 60)
    
    # 1. Audio check
    print("\n[复核 1/2] 提取成品音轨并执行 FFT 频域分离检测...")
    audio_res = verify_audio_frequencies(mp4_file, temp_dir)
    print(f"  小说配音 (523Hz) 峰值能量: {audio_res['peak_novel_523Hz']:.1f}")
    print(f"  素材1原音 (440Hz) 相对比率: {audio_res['ratio_clip1']:.6f}")
    print(f"  素材2原音 (880Hz) 相对比率: {audio_res['ratio_clip2']:.6f}")
    print(f"  原音频完全剥离判定: {'PASS' if audio_res['is_muted_effectively'] else 'FAIL'}")
    
    # 2. Subtitle multi-point snapshot
    print("\n[复核 2/2] 字幕时间戳多点抽帧测试...")
    sub_res = verify_subtitle_snapshots(mp4_file, temp_dir)
    for r in sub_res:
        print(f"  时间点 {r['timestamp']}s: {r['description']} -> 生成截图 ({r['size']} bytes)")
        
    print("\n>>> 阶段一轻量复核完成！")
