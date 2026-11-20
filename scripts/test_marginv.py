import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries
from PIL import Image
import numpy as np

ffmpeg, _ = find_ffmpeg_binaries()
temp_dir = Path("temp")
test_srt = temp_dir / "test_align.srt"
escaped_srt = str(test_srt.resolve()).replace("\\", "/").replace(":", "\\:")

for mv in [0, 50, 100]:
    out_img = temp_dir / f"test_mv_{mv}.png"
    flt = f"subtitles='{escaped_srt}':force_style='FontName=Microsoft YaHei,FontSize=10,Alignment=10,MarginV={mv},MarginL=30,MarginR=30'"
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
        "-vf", flt,
        "-vframes", "1", str(out_img)
    ]
    subprocess.run(cmd, capture_output=True)
    im = Image.open(out_img)
    arr = np.array(im)
    y_idx, x_idx = np.where(arr[:, :, 0] > 100)
    if len(y_idx) > 0:
        cy = y_idx.mean()
        cx = x_idx.mean()
        print(f"Alignment=10, MarginV={mv:3d}: Center Y={cy:6.1f}, Center X={cx:6.1f}")
