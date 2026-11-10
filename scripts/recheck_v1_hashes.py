"""
Independent script to calculate SHA-256 and size of Stage 5.6.2 and Stage 5.6.3 assets.
Avoids PowerShell inline quoting issues.
"""

from datetime import datetime
import hashlib
import os
from pathlib import Path
import sys

# Force UTF-8 output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FILES_TO_CHECK = [
    {
        "name": "阶段 5.6.2 v1 最终视频",
        "path": PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片_v1.mp4",
        "stage5_6_2_recorded_size": 275441200,
        "stage5_6_2_recorded_sha256": "7c54626733aa714c5c87bf0fc828d23500269f4cea8a040db7bcded297e7041a"
    },
    {
        "name": "阶段 5.6.2 v1 项目工程",
        "path": PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片.clipforge",
        "stage5_6_2_recorded_size": 109210,
        "stage5_6_2_recorded_sha256": "267ce5aea79bda8077c3c06a52529bef194537b524ac6bb6576d30cb433db5d7"
    },
    {
        "name": "阶段 5.6.2 v1 独立 Manifest",
        "path": PROJECT_ROOT / "output" / "manifest_stage5_6_2_customer_full.json",
        "stage5_6_2_recorded_size": 17197,
        "stage5_6_2_recorded_sha256": "9d7c602b178623e53273d1308533eace22927c5db3827d58e48ad1d88b5f4184"
    },
    {
        "name": "阶段 5.6.3 v2 新工程",
        "path": PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片_v2_edit.clipforge",
        "stage5_6_2_recorded_size": 109215,
        "stage5_6_2_recorded_sha256": "17d0ef7d7cae4d36c24e42edfedf999b285b4375f659ce33255dd99157dd923c"
    },
    {
        "name": "阶段 5.6.3 v2 最终视频",
        "path": PROJECT_ROOT / "output" / "客户小说推文_10月31日_首次完整成片_v2_font16.mp4",
        "stage5_6_2_recorded_size": 275412750,
        "stage5_6_2_recorded_sha256": "c5cd401c3c4b94c6db9f219964f9ace6dc4288c201b0bf21e0e9fc65a47dc422"
    }
]


def main():
    print("=" * 80)
    print(">>> 独立执行关键交付物 SHA-256 与文件大小精确核验")
    print("=" * 80)

    all_matched = True

    for item in FILES_TO_CHECK:
        name = item["name"]
        p = item["path"]
        exp_sz = item["stage5_6_2_recorded_size"]
        exp_sha = item["stage5_6_2_recorded_sha256"]

        if not p.exists():
            print(f"ERROR: 文件不存在 -> {p}")
            all_matched = False
            continue

        st = p.stat()
        actual_sz = st.st_size
        mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        actual_sha = hasher.hexdigest()

        size_match = (actual_sz == exp_sz)
        sha_match = (actual_sha == exp_sha)

        if size_match and sha_match:
            status = "MATCH (100% 一致)"
        else:
            status = "MISMATCH (不一致!)"
            all_matched = False

        print(f"\n[{name}] {p.name}")
        print(f"  文件修改时间: {mtime_str}")
        print(f"  实际字节大小: {actual_sz} 字节 (预期: {exp_sz}) -> {'PASS' if size_match else 'FAIL'}")
        print(f"  实际 SHA-256 : {actual_sha}")
        print(f"  预期 SHA-256 : {exp_sha} -> {'PASS' if sha_match else 'FAIL'}")
        print(f"  校验综合结论: {status}")

    print("\n" + "=" * 80)
    if all_matched:
        print(">>> 结论: 全部 5 个核心资产的 SHA-256 与文件大小 100% 吻合，未受任何改动！")
    else:
        print(">>> 结论: 存在资产不匹配，请核查！")
    print("=" * 80)


if __name__ == "__main__":
    main()
