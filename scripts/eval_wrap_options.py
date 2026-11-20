import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries
from PIL import Image
import numpy as np

ffmpeg, _ = find_ffmpeg_binaries()
temp_dir = Path("temp")
test_srt = temp_dir / "test_wrap_eval.srt"
test_srt.write_text("1\n00:00:00,000 --> 00:00:10,000\n穿成大雪坪轩辕家粥铺前抢稀粥的乞丐\n", encoding="utf-8")
escaped_srt = str(test_srt.resolve()).replace("\\", "/").replace(":", "\\:")

# Test 1: WrapStyle=2, FontSize=10, MarginL=20, MarginR=20
# Test 2: WrapStyle=0, FontSize=10, MarginL=20, MarginR=20
# Test 3: WrapStyle=0 with original_size=1080x1920

experiments = [
    ("fs10_wrap2", f"subtitles='{escaped_srt}':force_style='FontName=Microsoft YaHei,FontSize=10,Alignment=10,MarginV=0,MarginL=20,MarginR=20,WrapStyle=2'"),
    ("fs10_wrap0", f"subtitles='{escaped_srt}':force_style='FontName=Microsoft YaHei,FontSize=10,Alignment=10,MarginV=0,MarginL=20,MarginR=20,WrapStyle=0'"),
    ("fs9_wrap2",  f"subtitles='{escaped_srt}':force_style='FontName=Microsoft YaHei,FontSize=9,Alignment=10,MarginV=0,MarginL=20,MarginR=20,WrapStyle=2'"),
    ("fs16_wrap2", f"subtitles='{escaped_srt}':force_style='FontName=Microsoft YaHei,FontSize=16,Alignment=10,MarginV=0,MarginL=20,MarginR=20,WrapStyle=2'"),
]

for name, flt in experiments:
    out_img = temp_dir / f"eval_{name}.png"
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
        "-vf", flt,
        "-vframes", "1", str(out_img)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if out_img.exists():
        im = Image.open(out_img)
        arr = np.array(im)
        y, x = np.where(arr[:, :, 0] > 100)
        if len(y) > 0:
            h = y.max() - y.min() + 1
            w = x.max() - x.min() + 1
            x_min = x.min()
            x_max = x.max()
            lines = 1 if h < 65 else 2
            overflow = "OVERFLOW!" if (x_min <= 2 or x_max >= 1078) else "SAFE"
            print(f"{name:15s}: lines={lines}, bbox={w}x{h}, X=[{x_min}, {x_max}] -> {overflow}")
