"""
Generates an interactive, self-contained HTML gallery artifact with base64 embedded images
for Stage 5.6.3 visual inspection.
"""

import base64
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSP_DIR = PROJECT_ROOT / "output" / "inspection_stage5_6_3"
ARTIFACT_DIR = Path(r"C:\Users\123\.gemini\antigravity\brain\f0c55e45-6d17-4c5f-926e-9adb01d78e9c")

SCENES = [
    {
        "id": 2,
        "title": "场景 2：诗意短句（7 字）· 2 行变 1 行核心对比",
        "tag": "scene2_verse_7chars",
        "sub_id": 198,
        "time": "272.5s",
        "text": "我笑他人看不穿",
        "char_count": 7,
        "analysis": "v1 (24px) 因单行容字量低，仅 7 个字即被迫折为 2 行，总高度达 285 px，严重遮挡角色胸部与剑柄；v2 (16px) 轻松容纳单行，总高度骤降至 86 px（缩减 69.8%），中央画面完全透气，角色动态与服饰细节完整呈现。"
    },
    {
        "id": 3,
        "title": "场景 3：叙事长句（9 字）· 2 行变 1 行核心对比",
        "tag": "scene3_narrative_9chars",
        "sub_id": 98,
        "time": "133.4s",
        "text": "毕竟在这位儒圣心里",
        "char_count": 9,
        "analysis": "v1 (24px) 折为两行，总高 303 px，压迫角色头部正下方；v2 (16px) 保持 1 行展示，总高仅 86 px（缩减 71.6%），左右留白舒展，距离顶部 PNG 模板安全区 >450 px，绝无遮挡冲突。"
    },
    {
        "id": 5,
        "title": "场景 5：紧凑长句（12 字）· 双行高度大幅压缩",
        "tag": "scene5_dialogue_12chars",
        "sub_id": 16,
        "time": "21.5s",
        "text": "接着便有一道声音传来慢着",
        "char_count": 12,
        "analysis": "两版均展示为 2 行，但 v1 (24px) 高度达 285 px，横向几乎贴近屏幕边缘；v2 (16px) 总高压缩至 192 px（缩减 93 px），左右两侧各留出 >240 px 边距，文字紧凑而呼吸感强。"
    },
    {
        "id": 6,
        "title": "场景 6：超长大单句（14 字）· 3 行压缩至 2 行",
        "tag": "scene6_extralong_15chars",
        "sub_id": 296,
        "time": "401.8s",
        "text": "他们的陈年旧伤或许都不是问题",
        "char_count": 14,
        "analysis": "本片最长单句之一。v1 (24px) 被迫折断为惊人的 3 行，总高度暴增至 445 px，吞噬屏幕近四分之一高度；v2 (16px) 仅需 2 行（总高 193 px，缩减 252 px，降幅 56.6%），完美化解严重遮挡。"
    },
    {
        "id": 1,
        "title": "场景 1：短句台词（4 字）· 单行字芯比例验证",
        "tag": "scene1_short_4chars",
        "sub_id": 356,
        "time": "485.4s",
        "text": "然而今日",
        "char_count": 4,
        "analysis": "两版均为单行。v1 字芯高 118 px，总高 126 px；v2 字芯高 78 px，总高 86 px。精准实测缩减比为 66.1%，与字号参数 16/24=66.7% 完全对应。"
    },
    {
        "id": 4,
        "title": "场景 4：片尾回味句（8 字）· 尾句折行与模板留白",
        "tag": "scene4_tail_9chars",
        "sub_id": 395,
        "time": "533.5s",
        "text": "这天莫不是要变了",
        "char_count": 8,
        "analysis": "全片倒数第一条字幕。v1 (24px) 折为 2 行（285 px）；v2 (16px) 保持 1 行（86 px，缩减 69.8%）。距离底部留白区充裕，收尾视觉干净。"
    }
]


def img_to_b64(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"


def main():
    print(">>> 正在生成内置 Base64 高清对比图的交互式视觉审查画廊 HTML...")

    scenes_data = []
    for sc in SCENES:
        tag = sc["tag"]
        cmp_file = INSP_DIR / f"compare_{tag}.png"
        zoom_file = INSP_DIR / f"zoom_compare_{tag}.png"

        b64_cmp = img_to_b64(cmp_file)
        b64_zoom = img_to_b64(zoom_file)

        scenes_data.append({
            **sc,
            "has_cmp": bool(b64_cmp),
            "has_zoom": bool(b64_zoom),
            "b64_cmp": b64_cmp,
            "b64_zoom": b64_zoom
        })

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClipForge 阶段 5.6.3 视觉画质与字幕排版深度对照画廊</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    body {{
      background-color: #0b0d13;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    .badge-v1 {{
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid rgba(244, 63, 94, 0.4);
      color: #fb7185;
    }}
    .badge-v2 {{
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #34d399;
    }}
    .img-card {{
      background: #11141f;
      border: 1px solid #1e2433;
      border-radius: 12px;
      overflow: hidden;
      transition: transform 0.2s ease, border-color 0.2s ease;
    }}
    .img-card:hover {{
      border-color: #38bdf8;
    }}
  </style>
</head>
<body class="p-6 max-w-7xl mx-auto">

  <!-- Header -->
  <header class="mb-8 pb-6 border-b border-slate-800">
    <div class="flex items-center justify-between flex-wrap gap-4">
      <div>
        <h1 class="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
          <span>ClipForge 阶段 5.6.3 视觉画质与字幕排版高清对照画廊</span>
        </h1>
        <p class="text-sm text-slate-400 mt-1">
          真实客户成片抽帧对照：v1 (24px 膨胀) vs v2 (16px 优化) · 100% 内嵌无损 Base64 渲染
        </p>
      </div>
      <div class="flex items-center gap-3 text-xs">
        <span class="badge-v1 px-3 py-1.5 rounded-full font-semibold">v1 原版 (24 px)</span>
        <span class="text-slate-500 font-bold">vs</span>
        <span class="badge-v2 px-3 py-1.5 rounded-full font-semibold">v2 二次导出 (16 px)</span>
      </div>
    </div>
  </header>

  <!-- Key Observations Notice Banner -->
  <div class="bg-gradient-to-r from-blue-950/40 via-indigo-950/30 to-purple-950/40 border border-blue-800/40 rounded-xl p-5 mb-8">
    <h3 class="text-sm font-semibold text-blue-300 mb-2 flex items-center gap-2">
      <span>核心视觉审阅结论指引</span>
    </h3>
    <ul class="text-xs text-slate-300 space-y-1.5 leading-relaxed">
      <li><strong>1. 人物面部与构图遮挡改善</strong>：在 24px 下，7 字以上即折断为 2 行甚至 3 行（高度 285~445 px），字面直接骑在人物胸颈部位；16px 恢复为优雅单行（高度仅 86 px），释放出近 70% 的中央画面。</li>
      <li><strong>2. 手机竖屏可读性</strong>：16px 实测纯白字芯高度为 78 px，在 1080×1920 竖屏分辨率下相当于手机全屏阅读时大号黑体，笔画粗壮饱满，配 4px 纯黑外包边，文字反差极其锐利。</li>
      <li><strong>3. PNG 模板安全区</strong>：字幕绝对垂直居中定位在 Y≈720~780 px 区间，距离顶部标题挂件 >450 px，距离底部留白 >800 px，绝无任何穿模冲突。</li>
    </ul>
  </div>

  <!-- Priority Scenes Grid -->
  <div class="space-y-12">
"""

    for sc in scenes_data:
        html_content += f"""
    <!-- Scene {sc['id']} -->
    <section class="img-card p-6" id="scene-{sc['id']}">
      <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div class="flex items-center gap-3">
          <span class="px-2.5 py-1 bg-blue-500/20 text-blue-400 font-mono text-xs font-bold rounded">
            Scene #{sc['id']}
          </span>
          <h2 class="text-lg font-bold text-white">{sc['title']}</h2>
        </div>
        <div class="text-xs text-slate-400 font-mono">
          字幕 #{sc['sub_id']} | 时间戳: <span class="text-amber-400 font-semibold">{sc['time']}</span> | 台词: <span class="text-slate-200">“{sc['text']}” ({sc['char_count']}字)</span>
        </div>
      </div>

      <p class="text-xs text-slate-300 bg-slate-900/60 border border-slate-800/80 rounded-lg p-3 mb-5 leading-relaxed">
        <strong class="text-slate-100">视觉对比深度分析：</strong>{sc['analysis']}
      </p>

      <!-- Zoom Cropped Comparison (Pixel Measured) -->
      <div class="mb-5">
        <div class="text-xs font-semibold text-slate-400 mb-2 flex items-center justify-between">
          <span>1:1 原尺寸字幕局部截取（红框: v1 24px 实测字芯 | 绿框: v2 16px 实测字芯）</span>
          <span class="text-[11px] text-slate-500">直接观测文字笔画锐利度与排版高度</span>
        </div>
        <div class="border border-slate-800 rounded-lg overflow-hidden bg-black flex justify-center">
          <img src="{sc['b64_zoom']}" alt="Zoom Comparison Scene {sc['id']}" class="w-full max-w-4xl object-contain shadow-lg" loading="lazy"/>
        </div>
      </div>

      <!-- Full Screen Side-by-Side Comparison -->
      <div>
        <div class="text-xs font-semibold text-slate-400 mb-2 flex items-center justify-between">
          <span>9:16 全屏成片侧向对比（左侧: v1 原版 24px | 右侧: v2 优化版 16px）</span>
          <span class="text-[11px] text-slate-500">观测整幅画面比例、人物透气度与模板留白</span>
        </div>
        <div class="border border-slate-800 rounded-lg overflow-hidden bg-black flex justify-center">
          <img src="{sc['b64_cmp']}" alt="Full Screen Comparison Scene {sc['id']}" class="w-full max-w-4xl object-contain shadow-lg" loading="lazy"/>
        </div>
      </div>
    </section>
"""

    html_content += """
  </div>

  <footer class="mt-12 pt-6 border-t border-slate-800 text-center text-xs text-slate-500">
    ClipForge 自动视频混剪系统 · 阶段 5.6.3 高清视觉审查报告
  </footer>

</body>
</html>
"""

    out_file = ARTIFACT_DIR / "stage5_6_3_visual_inspection_gallery.html"
    out_file.write_text(html_content, encoding="utf-8")
    print(f"[OK] 视觉画廊已生成: {out_file} ({out_file.stat().st_size} 字节)")


if __name__ == "__main__":
    main()
