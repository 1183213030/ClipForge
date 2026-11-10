"""
Builds a compact, tabbed inline comparison widget for chat embed.
"""

import base64
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSP_DIR = PROJECT_ROOT / "output" / "inspection_stage5_6_3"
ARTIFACT_DIR = Path(r"C:\Users\123\.gemini\antigravity\brain\f0c55e45-6d17-4c5f-926e-9adb01d78e9c")

PRIORITY_SCENES = [
    {
        "id": 2,
        "tab_name": "场景2 (7字)",
        "title": "场景2: 我笑他人看不穿 (7字)",
        "tag": "scene2_verse_7chars",
        "sub_id": 198,
        "time": "272.5s",
        "highlight": "2行变1行: 高度 285px -> 86px (-69.8%), 彻底释放角色胸颈与剑身"
    },
    {
        "id": 3,
        "tab_name": "场景3 (9字)",
        "title": "场景3: 毕竟在这位儒圣心里 (9字)",
        "tag": "scene3_narrative_9chars",
        "sub_id": 98,
        "time": "133.4s",
        "highlight": "2行变1行: 高度 303px -> 86px (-71.6%), 距顶部安全区 >450px"
    },
    {
        "id": 5,
        "tab_name": "场景5 (12字)",
        "title": "场景5: 接着便有一道声音传来慢着 (12字)",
        "tag": "scene5_dialogue_12chars",
        "sub_id": 16,
        "time": "21.5s",
        "highlight": "双行高度压缩: 285px -> 192px (-32.6%), 左右各留 240px 安全余量"
    },
    {
        "id": 6,
        "tab_name": "场景6 (14字)",
        "title": "场景6: 他们的陈年旧伤或许都不是问题 (14字)",
        "tag": "scene6_extralong_15chars",
        "sub_id": 296,
        "time": "401.8s",
        "highlight": "3行变2行: 高度 445px -> 193px (-56.6%), 化解全屏最大压迫感"
    }
]


def img_to_b64(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"


def main():
    tabs_html = []
    contents_html = []

    for i, sc in enumerate(PRIORITY_SCENES):
        tag = sc["tag"]
        cmp_path = INSP_DIR / f"compare_{tag}.png"
        zoom_path = INSP_DIR / f"zoom_compare_{tag}.png"
        b64_cmp = img_to_b64(cmp_path)
        b64_zoom = img_to_b64(zoom_path)

        active_tab_class = "border-blue-500 text-blue-400 font-bold bg-blue-500/10" if i == 0 else "border-transparent text-slate-400 hover:text-slate-200"
        hidden_class = "" if i == 0 else "hidden"

        tabs_html.append(f"""
          <button onclick="switchTab({i})" id="tab-btn-{i}" class="tab-btn px-3 py-2 text-xs rounded-t-lg border-b-2 font-medium transition-all {active_tab_class}">
            {sc['tab_name']}
          </button>
        """)

        contents_html.append(f"""
          <div id="tab-pane-{i}" class="tab-pane {hidden_class} space-y-3">
            <div class="bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 flex items-center justify-between text-xs">
              <div>
                <span class="font-bold text-white">{sc['title']}</span>
                <span class="text-slate-400 ml-2 font-mono">@{sc['time']} (第{sc['sub_id']}句)</span>
              </div>
              <span class="px-2 py-0.5 bg-emerald-500/20 text-emerald-300 font-mono text-[11px] rounded font-semibold">
                {sc['highlight']}
              </span>
            </div>

            <!-- Zoom Comparison -->
            <div class="border border-slate-800 rounded-lg overflow-hidden bg-black">
              <div class="px-2.5 py-1 bg-slate-950/80 text-[11px] text-slate-400 border-b border-slate-800 flex justify-between">
                <span>1:1 原尺寸像素标注（红框: v1 24px 实测 | 绿框: v2 16px 实测）</span>
                <span>字形与描边真实大小</span>
              </div>
              <img src="{b64_zoom}" class="w-full max-h-40 object-contain mx-auto" />
            </div>

            <!-- Full Frame Comparison -->
            <div class="border border-slate-800 rounded-lg overflow-hidden bg-black">
              <div class="px-2.5 py-1 bg-slate-950/80 text-[11px] text-slate-400 border-b border-slate-800 flex justify-between">
                <span>9:16 全屏侧向成片（左: v1 24px | 右: v2 16px）</span>
                <span>人物遮挡与留白审阅</span>
              </div>
              <img src="{b64_cmp}" class="w-full max-h-64 object-contain mx-auto" />
            </div>
          </div>
        """)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased p-2">
  <div class="bg-[#0f1219] text-[#f8fafc] border border-slate-800 rounded-xl p-4 shadow-xl max-w-4xl mx-auto">
    <div class="flex items-center justify-between pb-3 border-b border-slate-800">
      <div>
        <h2 class="text-sm font-bold text-white flex items-center gap-2">
          <span>ClipForge 阶段 5.6.3 重点场景视觉抽检对照（内嵌 Base64）</span>
        </h2>
        <p class="text-[11px] text-slate-400 mt-0.5">点击标签切换查看用户指定审阅的 4 组重点场景对比图</p>
      </div>
      <span class="text-[11px] px-2.5 py-1 bg-blue-900/40 border border-blue-700/50 text-blue-300 rounded-full font-mono">
        100% 离线内嵌
      </span>
    </div>

    <!-- Tab Bar -->
    <div class="flex border-b border-slate-800 mt-3 gap-1">
      {''.join(tabs_html)}
    </div>

    <!-- Tab Panes -->
    <div class="mt-3">
      {''.join(contents_html)}
    </div>
  </div>

  <script>
    function switchTab(idx) {{
      const total = {len(PRIORITY_SCENES)};
      for (let i = 0; i < total; i++) {{
        const btn = document.getElementById('tab-btn-' + i);
        const pane = document.getElementById('tab-pane-' + i);
        if (i === idx) {{
          btn.className = 'tab-btn px-3 py-2 text-xs rounded-t-lg border-b-2 font-medium transition-all border-blue-500 text-blue-400 font-bold bg-blue-500/10';
          pane.classList.remove('hidden');
        }} else {{
          btn.className = 'tab-btn px-3 py-2 text-xs rounded-t-lg border-b-2 font-medium transition-all border-transparent text-slate-400 hover:text-slate-200';
          pane.classList.add('hidden');
        }}
      }}
    }}
  </script>
</body>
</html>
"""

    out_file = ARTIFACT_DIR / "stage5_6_3_inline_compare_widget.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"[OK] 内嵌对比组件已生成: {out_file} ({out_file.stat().st_size} 字节)")


if __name__ == "__main__":
    main()
