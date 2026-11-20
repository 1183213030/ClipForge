import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries
from PIL import Image
import numpy as np

ffmpeg, _ = find_ffmpeg_binaries()
temp_dir = Path("temp")
temp_dir.mkdir(exist_ok=True)

test_srt = temp_dir / "test_align.srt"
test_srt.write_text("1\n00:00:00,000 --> 00:00:05,000\n抬手从胳肢窝搓出一颗乌黑泥丸\n", encoding="utf-8")

styles = [
    ("align5_mv100_fs16", "FontName=Microsoft YaHei,FontSize=16,Alignment=5,MarginV=100,MarginL=60,MarginR=60"),
    ("align5_mv0_fs16", "FontName=Microsoft YaHei,FontSize=16,Alignment=5,MarginV=0,MarginL=60,MarginR=60"),
    ("align5_mv0_fs16_wrap2", "FontName=Microsoft YaHei,FontSize=16,Alignment=5,MarginV=0,MarginL=30,MarginR=30,WrapStyle=2"),
    ("align5_mv0_fs12", "FontName=Microsoft YaHei,FontSize=12,Alignment=5,MarginV=0,MarginL=30,MarginR=30"),
    ("align5_mv0_fs10", "FontName=Microsoft YaHei,FontSize=10,Alignment=5,MarginV=0,MarginL=30,MarginR=30"),
    ("align5_mv0_fs9", "FontName=Microsoft YaHei,FontSize=9,Alignment=5,MarginV=0,MarginL=30,MarginR=30"),
    ("align5_mv0_fs8", "FontName=Microsoft YaHei,FontSize=8,Alignment=5,MarginV=0,MarginL=30,MarginR=30"),
]

for name, style in styles:
    out_img = temp_dir / f"{name}.png"
    # Note: escape Windows path colons and backslashes
    escaped_srt = str(test_srt.resolve()).replace("\\", "/").replace(":", "\\:")
    flt = f"subtitles='{escaped_srt}':force_style='{style}'"
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
        h = y_idx.max() - y_idx.min() + 1
        w = x_idx.max() - x_idx.min() + 1
        cy = y_idx.mean()
        cx = x_idx.mean()
        print(f"{name:25s}: bbox w={w:4d}, h={h:3d}, Center Y={cy:6.1f} (target 960.0), Center X={cx:6.1f} (target 540.0)")
    else:
        print(f"{name:25s}: No text found!")
