import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from app.utils.ffmpeg_utils import find_ffmpeg_binaries

ffmpeg, _ = find_ffmpeg_binaries()
test_srt = Path("temp/test_ref_cmp.srt")
escaped_srt = str(test_srt.resolve()).replace("\\", "/").replace(":", "\\:")

style = "FontName=Microsoft YaHei,FontSize=9,Alignment=10,MarginV=0,MarginL=20,MarginR=20,WrapStyle=2"
flt = f"subtitles='{escaped_srt}':force_style='{style}'"
cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1", "-vf", flt, "-vframes", "1", "temp/test_wrap2.png"]
res = subprocess.run(cmd, capture_output=True, text=True)
print("FFmpeg return code:", res.returncode)
assert res.returncode == 0
print("WrapStyle=2 SUCCESS!")
