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

# Test sentences:
# Sentence 1: "抬手从胳肢窝搓出一颗乌黑泥丸" (14 chars)
# Sentence 2: "穿成大雪坪轩辕家粥铺前抢稀粥的乞丐" (17 chars)
# Sentence 3: "一双怨念满满的双眸正死死盯着他" (15 chars)

sentences = [
    "抬手从胳肢窝搓出一颗乌黑泥丸",
    "穿成大雪坪轩辕家粥铺前抢稀粥的乞丐",
    "他们的陈年旧伤或许都不是问题"
]

for s_idx, sent in enumerate(sentences):
    s_srt = temp_dir / f"test_sent_{s_idx}.srt"
    s_srt.write_text(f"1\n00:00:00,000 --> 00:00:05,000\n{sent}\n", encoding="utf-8")
    escaped_s_srt = str(s_srt.resolve()).replace("\\", "/").replace(":", "\\:")
    
    print(f"\n--- Testing: '{sent}' ({len(sent)} chars) ---")
    for fs in [12, 10, 9, 8]:
        out_img = temp_dir / f"sent_{s_idx}_fs{fs}.png"
        style = f"FontName=Microsoft YaHei,FontSize={fs},Alignment=10,MarginV=0,MarginL=20,MarginR=20"
        flt = f"subtitles='{escaped_s_srt}':force_style='{style}'"
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
            # Estimate single char height in px
            single_h = h if h < 60 else h // 2
            lines = 1 if h < 65 else 2
            print(f"  FontSize={fs:2d}: Lines={lines}, bbox=({w:4d}x{h:3d}), Center=({cx:5.1f}, {cy:5.1f}), single_h={single_h}px")
