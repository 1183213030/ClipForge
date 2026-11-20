import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries
from app.core.subtitle_processor import SubtitleConfig, SubtitlePosition, build_subtitles_filter
from PIL import Image
import numpy as np

ffmpeg, _ = find_ffmpeg_binaries()
temp_dir = Path("temp")
temp_dir.mkdir(exist_ok=True)

# Test customer subtitles
srt_path = temp_dir / "customer_sub_test.srt"
srt_content = """1
00:00:00,000 --> 00:00:03,000
穿成大雪坪轩辕家粥铺前抢稀粥的乞丐

2
00:00:07,000 --> 00:00:10,000
抬手从胳肢窝搓出一颗乌黑泥丸

3
00:00:12,000 --> 00:00:15,000
他们的陈年旧伤或许都不是问题
"""
srt_path.write_text(srt_content, encoding="utf-8")

# Config with updated centered, compact, single-line style
sub_cfg = SubtitleConfig(
    font_name="Microsoft YaHei",
    font_size=9,
    position=SubtitlePosition.CENTER,
    margin_v=0,
    margin_l=20,
    margin_r=20,
    max_line_chars=24
)

sub_filter = build_subtitles_filter(srt_path, sub_cfg)
print("Generated subtitle filter:", sub_filter)

# Render frames against raw video clip + template
raw_clip = Path("videos/6150669-uhd_2160_4096_25fps.mp4")
template_png = Path("resources/templates/customer_template.png")

checkpoints = [
    ("frame_1_opening_17chars", 1.5, "穿成大雪坪轩辕家粥铺前抢稀粥的乞丐"),
    ("frame_2_niwan_14chars", 8.5, "抬手从胳肢窝搓出一颗乌黑泥丸"),
    ("frame_3_jiushang_14chars", 13.5, "他们的陈年旧伤或许都不是问题"),
]

for tag, t_sec, text in checkpoints:
    s_srt = temp_dir / f"{tag}.srt"
    s_srt.write_text(f"1\n00:00:00,000 --> 00:00:10,000\n{text}\n", encoding="utf-8")
    s_flt = build_subtitles_filter(s_srt, sub_cfg)
    
    out_img = temp_dir / f"{tag}_centered_fs9.png"
    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[vbg];"
        f"[1:v]scale=1080:1920[vtpl];"
        f"[vbg][vtpl]overlay=0:0[vcomp];"
        f"[vcomp]{s_flt}[vout]"
    )
    cmd = [
        ffmpeg, "-y",
        "-ss", str(t_sec),
        "-i", str(raw_clip.resolve()),
        "-i", str(template_png.resolve()),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-vframes", "1",
        str(out_img)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("FFmpeg error:", res.stderr)
        break
    print(f"Generated {out_img.name}")
