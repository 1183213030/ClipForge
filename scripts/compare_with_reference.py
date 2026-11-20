import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries
from PIL import Image
import numpy as np

ffmpeg, _ = find_ffmpeg_binaries()
temp_dir = Path("temp")
test_srt = temp_dir / "test_ref_cmp.srt"
# The exact text from reference video @ 8.5s
test_srt.write_text("1\n00:00:00,000 --> 00:00:05,000\n那个被粉丝堵着骂了半年\n", encoding="utf-8")
escaped_srt = str(test_srt.resolve()).replace("\\", "/").replace(":", "\\:")

for fs in [9, 10]:
    out_img = temp_dir / f"cmp_ref_fs{fs}.png"
    style = f"FontName=Microsoft YaHei,FontSize={fs},Alignment=10,MarginV=0,MarginL=20,MarginR=20"
    flt = f"subtitles='{escaped_srt}':force_style='{style}'"
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
        "-vf", flt,
        "-vframes", "1", str(out_img)
    ]
    subprocess.run(cmd, capture_output=True)
    # Downscale to 544x960 to match reference video resolution
    im = Image.open(out_img).resize((544, 960), Image.Resampling.LANCZOS)
    im.crop((100, 440, 444, 520)).save(temp_dir / f"cmp_crop_fs{fs}.png")

# Now crop the exact same region from reference frame 8.5s
ref_im = Image.open("temp/ref_8.5s.png")
ref_im.crop((100, 440, 444, 520)).save(temp_dir / "ref_crop_8.5s.png")
print("Done comparing with reference")
