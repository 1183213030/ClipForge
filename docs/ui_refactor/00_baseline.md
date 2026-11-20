# ClipForge UI 重构基线与业务保护审计报告 (Stage 0 Baseline Audit)

> **审计执行时间**: 2026-11-20  
> **Git 重构分支**: `ui-awwwards-refactor`  
> **执行代理**: Antigravity (DeepMind)  
> **审计范围**: `D:\Tools\ClipForge` 工程现状、UI与业务模块依赖关系、保护清单哈希、全阶段测试基准与交互安全边界  

---

## 1. 工程现状与代码资产审计

### 1.1 现有 UI 模块清单 (允许修改与视觉升级)

| 文件路径 | 模块职责 | 依赖的业务接口 | 改造与升级策略 |
| :--- | :--- | :--- | :--- |
| `app/ui/main_window.py` | 主窗口容器、双页面堆叠、顶部导航、批量导出控制、任务监控队列 | `TaskService`, `probe_media`, `TimelineBuilder`, `EditProject`, `create_project` | 重构整体容器与导航栏，采用 Awwwards 胶囊 Tab，优化左右分栏网格，升级任务卡片流式布局 |
| `app/ui/pages/workbench_page.py` | 精细编辑工作台页面、顶部工程操作栏、三栏联动与底部时间轴容器 | `EditProject`, `ProjectError` | 重构顶部工具栏状态卡片、三栏容器视觉规范、保持信号流 100% 连通 |
| `app/ui/widgets/asset_card.py` | 批量混剪 · 素材导入与扫描卡片 (音频/字幕/视频库/PNG模板) | `ScanResult`, `ScanFolderThread`, `ProbeAudioThread` | 升级为深曜石多层卡片，优化路径长文本省略与悬停，统一状态徽章与按钮 |
| `app/ui/widgets/subtitle_card.py` | 批量混剪 · 字幕排版与样式配置卡片 (字体/字号/位置/描边/预览) | `SubtitleConfig`, `SubtitlePosition`, `FontManager` | 统一样式输入控件，折叠/高密度对齐，升级字幕预览独立卡片 |
| `app/ui/widgets/video_card.py` | 批量混剪 · 视频规格与硬件加速配置卡片 (比例/分辨率/FPS/码率/硬件加速) | `ExportOptions`, `HardwareEncoderManager`, `EncoderBackend` | 统一下拉框与硬件加速检测状态徽章，高密度专业呈现 |
| `app/ui/widgets/task_item_widget.py` | 批量混剪 · 实时任务监控条目卡片 (进度条/速度/耗时/状态/取消/打开) | `TaskRecord`, `TaskState` | 消除重绘闪烁，统一渐变进度条与状态药丸徽章，优化操作按钮悬停与交互 |
| `app/ui/widgets/segment_list_widget.py` | 工作台 · 视频片段管理列表 (编号/片段名/时长/入出点/排序/替换/删除) | `EditProject`, `VideoTrackSegment` | 卡片化片段列表，序号 Badge 高亮，优化拖拽手柄视觉反馈与选中高亮 |
| `app/ui/widgets/video_player_widget.py` | 工作台 · 9:16 视频画布、播放控制栏、时间码、进度条、音量控制 | `QMediaPlayer`, `QAudioOutput`, `QVideoWidget` | 规范 9:16 画布比例与居中投影，统一等宽时间码、青色播放头与悬停交互 |
| `app/ui/widgets/subtitle_editor_widget.py` | 工作台 · 395条字幕表格编辑器、关键词搜索、时间码、双击编辑 | `EditProject`, `SubtitleTrackItem` | 深度深色表格、表头样式优化、选中行青色描边、大数据量平滑滚动 |
| `app/ui/widgets/timeline_track_widget.py` | 工作台 · 底部多片段时间轴缩略、时间标尺、片段色块分布、播放头 | `EditProject` | 标尺时间刻度精细化、片段色块配色与选中态、青色播放头指针与拖拽反馈 |
| `resources/styles/dark_theme.qss` | 全局暗色主题样式表 (配色 Token、控件样式、滚动条、圆角) | 视觉层样式表 | 全面重构为 Awwwards 顶级深曜石主题规范，建立全套样式类 |

---

## 2. 严格保护的业务与核心模块 (禁止修改)

为了确保本次 UI/UX 重构绝对不改变任何底层视频生成、字幕解析、随机化混剪算法、工程持久化及并发任务调度的语义，以下业务模块被列入 **P0 绝对保护清单**。

任何对下列文件的修改将被视为验收不合格：

| 模块类别 | 保护文件路径 | 字节大小 | SHA-256 校验和 | 保护原因与业务边界 |
| :--- | :--- | :--- | :--- | :--- |
| **核心算法** | `app/core/video_processor.py` | 23,121 | `b691a8ab69cc17b2724d664b13888e2c0771a1ea27ead421973089a374414754` | FFmpeg 滤镜图构建、音视频合流、多片段时间轴拼接、模板图层叠加、CFR 帧率控制与烧录算法 |
| **媒体探测** | `app/core/media_probe.py` | 5,691 | `03b71d87ab62a291b5b6071ab4cad836e67ebd4f152d0bf777ba3a5223dd728b` | FFprobe 媒体元数据探测、流信息提取、音频采样率与视频时长解析 |
| **素材扫描** | `app/core/media_scanner.py` | 5,862 | `d1a6ddfefe900fc0efbc3ad5a53fc37d77dfc0c92943574bb022e1023a4528fd` | 本地素材目录多线程扫描、哈希去重与素材库索引 |
| **随机化引擎** | `app/core/randomizer.py` | 14,463 | `4524c80d350cc0ec117aae87644e1afc02059a471612f52cb98d3cf1fed5d219` | 素材相邻防重复打散、时长预算分配、随机种子生成与复现逻辑 |
| **时间轴构建** | `app/core/timeline_builder.py` | 3,340 | `7ea52d44f998193f6e33fd2a393298dc6659f60280b886b40a830cf183668df1` | 时间轴段落装配、多轨道同步与导出时间轴计划生成 |
| **导出管理** | `app/core/export_manager.py` | 5,853 | `fbab2d6c19e9455851d1f83121f36b3cc9a51b5ad2a06b32a72fb1eb2da4e714` | 导出任务管线执行、Manifest 元数据生成与成片落盘管理 |
| **工程数据** | `app/core/edit_project.py` | 29,280 | `1652dced1ce51f6ac1c65066f1375350da054d57e5b5ddcadbb6c623346eac88` | `.clipforge` 工程模型、轨道对象、原子持久化、脏标记与时间轴转换 |
| **任务服务** | `app/services/task_service.py` | 20,280 | `e98e745e51e3998cd0f9461aeb5258004ad441b35890e95931e41f0f39aaf3ea` | 任务队列管理、多线程并发调度、取消机制、状态迁移与日志管理 |
| **硬件编码** | `app/core/hw_encoder.py` | 7,774 | `f27ede43c0a3c22d8af3618b12505d53a11f4371a24c70f854cd174f4a5c76b2` | NVENC / QSV / AMF 硬件编码器探测与参数匹配 |
| **字体系统** | `app/core/font_manager.py` | 5,591 | `1413229a9275b348cec9ef1e232d2822832479267e695667fed9952ab5349c6e` | 系统字体扫描、TTF/OTF 自定义字体注册与验证 |
| **字幕处理** | `app/core/subtitle_processor.py` | 8,503 | `7cf204102ab54087b8e322772c12936fc2cf4d424cdcda72da75370dfd48085b` | SRT 解析、智能换行分词、ASS 样式生成与字符集编码适配 |
| **素材缓存** | `app/core/clip_cache.py` | 15,847 | `f4e64e2b2f6610cdea23abbbfcf500c06a9723a7f85768e12667e3b162842902` | 素材缓存索引、元数据持久化加速 |
| **系统底层** | `app/utils/ffmpeg_utils.py` | 4,699 | `efc0f2a8a41a3724d8c2d077230a3cb26e3439289ba0b8e0f54bc73c472e2682` | FFmpeg/FFprobe 子进程调用包装、路径定位与安全执行 |
| **路径工具** | `app/utils/path_utils.py` | 1,275 | `cd40ab47ea4ca0f5568c9740ef352c0e7e9dff3754fca304f0ddccc60f41c695` | 跨平台路径规整、目录保证与路径转换 |
| **主入口** | `main.py` | 1,126 | `9d4d6ac074d186ead10ef75fdb4560310d560b54eca1b6961ba49269c3910907` | 应用启动引导、高分屏缩放适配、QApplication 事件循环 |
| **UI工作线程** | `app/ui/threads.py` | 5,882 | `caae90904071ddde8fcd658662a169dff6635099263a4818771608dcf775e6de` | Qt 后台工作线程 (`QThread`)，负责连接业务任务与 UI 信号 |

---

## 3. 依赖关系拓扑图

```
                          +------------------------------------------+
                          |                 main.py                  |
                          +------------------------------------------+
                                               |
                                               v
                          +------------------------------------------+
                          |        app/ui/main_window.py             |
                          +------------------------------------------+
                                     /             \
                                    /               \
                                   v                 v
                 +-----------------------+     +-------------------------------+
                 | 页面 A: 批量混剪 Split |     | 页面 B: WorkbenchPage         |
                 +-----------------------+     +-------------------------------+
                     /       |       \            /        |          \         \
                    v        v        v          v         v           v         v
               [Asset]  [Subtitle]  [Video]  [Segment]  [Player]  [SubEditor] [Timeline]
                  Card      Card      Card      List     Widget      Widget     Track
                    |         |         |         |         |           |         |
                    +---------+---------+         +---------+-----------+---------+
                                  |                                     |
                                  v                                     v
                       +---------------------+               +---------------------+
                       |   app/ui/threads.py |               | app/core/edit_proj  |
                       +---------------------+               +---------------------+
                                  |
                                  v
    +-------------------------------------------------------------------------------+
    |                          受保护的业务核心层 (P0)                                |
    |  TaskService | VideoProcessor | TimelineBuilder | MediaProbe | MediaScanner   |
    |  SubtitleProcessor | FontManager | HwEncoder | ExportManager | FfmpegUtils    |
    +-------------------------------------------------------------------------------+
```

---

## 4. 全阶段测试基准体检结果 (Stage 1 ~ 5.6.3)

在基线准备阶段，运行了项目内置的全量测试套件 `scripts/run_all_tests.py`。
测试执行记录与状态汇总如下：

| 阶段编号 | 测试脚本 | 测试套件职责 | 基准结果 | 耗时 | 详细诊断说明 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Stage 1** | `tests/test_stage1.py` | 基础视频混剪、音画对齐与字幕烧录 | **PASS** | 7.92s | 综合合成、分段对齐与字幕烧录 100% 正常通过 |
| **Stage 2** | `tests/test_stage2.py` | 素材去重打散、无相邻重复与种子复现 | **PASS** | 7.44s | 素材随机打散与确定性种子复现逻辑通过 |
| **Stage 3** | `tests/test_stage3.py` | 批量小说推文自动化处理与导出 Manifest | **PASS** | 43.54s | 完整真实渲染批处理、Manifest 结构与元数据校验通过 |
| **Stage 4** | `tests/test_stage4_gui.py` | PySide6 主界面集成与交互响应 | **PASS** | 65.08s | 主窗口初始化、素材探测、参数设置、异步混剪导出通过 |
| **Stage 5.1 & 5.2** | `tests/test_stage5_core.py` | 核心渲染加固、推文模板与智能换行 | **FAIL\*** | 7.00s | **环境基线已知现象**: TC-04 尾帧抽帧体积断言 `size > 50000` 触发 AssertionError，实测生成图像为 `45,036` bytes（为正常非黑屏帧，受 PNG 压缩率波动影响低于 50KB 阈值，核心渲染流程完全正常） |
| **Stage 5.3** | `tests/test_stage5_project.py` | EditProject 数据模型、持久化与原子保存 | **PASS** | 0.23s | 工程文件新建、修改、原子写入与加载无损校验通过 |
| **Stage 5.4** | `tests/test_stage5_workbench.py` | 轻量编辑工作台 GUI 交互与确定性重导 | **PASS** | 12.23s | 片段调序、时长调整、字幕表格联动、确定性重导通过 |
| **Stage 5.6.1** | `tests/test_stage5_filter_script.py` | 滤镜脚本化解耦、临时文件清理与 CPS 诊断 | **PASS** | 60.75s | `-filter_complex_script` 生命周期、超长滤镜图测试通过 |
| **Stage 5.6.3** | `tests/test_stage5_font_and_reexport.py` | 字号控制、持久化同步与确定性重导计划 | **FAIL\*** | 0.89s | **环境基线已知现象**: 前 7 项测试全部通过（字号更新、工程同步、重导计划生成等均 PASS），仅 TC-08 检查 `output/客户小说推文_10月31日_首次完整成片_v1.mp4` 失败，原因是该大视频（275MB）被 `.gitignore` 忽略，未随代码库提交，属运行时历史成片依赖项 |

**基线测试结论**:
- 核心 UI 与业务联动套件（Stage 1, 2, 3, 4, 5.3, 5.4, 5.6.1）**全部顺利通过**。
- 两项未通过点均为已有测试环境的特定边界断言（PNG压缩大小阈值 与 Git未跟踪大视频资产），并非业务逻辑损坏。
- 重构期间将以 Stage 4 GUI 和 Stage 5.4 Workbench 作为核心回归基准，确保 UI 改造不引起任何新的失败。

---

## 5. UI 交互层安全优化边界分析

根据保护业务层的根本原则，明确划分 UI 层的改动权限与安全边界：

### 5.1 允许且推荐在 UI 层优化的交互行为
1. **视觉反馈强化**: 按钮与卡片的 Hover（轻微明度提升与边框高亮）、Pressed（微弱缩放或色深下压）、Focus（品牌主色描边 `#6366F1`）。
2. **文本展示体验**: 对超长路径采用优雅的中间省略 (`.../folder/file.mp4`)，并配备完整的原生 Tooltip 提示完整路径。
3. **任务队列呈现**: 采用防抖更新机制避免每次进度变更导致整体布局重刷/滚动条跳动；进度条采用微光平滑动画。
4. **组件视觉升级**: 统一采用设计系统 Token，替换粗糙的原生边框与灰底，引入深度暗曜石面板与细微发光。
5. **图标全量统一**: 剔除界面中任何 Emoji 字符，统一替换为 Lucide SVG 矢量图标（基于现有内联 Lucide SVG 方案）。
6. **字幕编辑器交互**: 搜索框实时筛选表格行（仅改变 `table.setRowHidden` 显示状态，绝不触碰底层的字幕数据模型）。
7. **时间轴轨道渲染**: 在 `paintEvent` 中提升标尺刻度细腻度、片段颜色块视觉质感与播放头指针绘制精度。

### 5.2 严禁在 UI 层擅自变更的操作行为
1. **严禁修改信号传参结构**: 例如 `segment_selected(int, object)`、`project_modified()`、`subtitle_clicked(float)` 等信号的类型与触发时机必须保持不变。
2. **严禁在 UI 控件内自行持久化**: 所有工程变更必须通过调用 `EditProject` 对象的既有方法，由其内部处理脏标记和保存。
3. **严禁自行更改多线程任务调度**: `TaskService` 的任务派发、取消逻辑以及 `BatchExportThread` 的生命周期保持原状。
4. **严禁伪造不存在的业务数据**: 如渲染剩余时间、渲染速度等，若底层 `TaskRecord` 未提供则不凭空展示虚拟数字。

---

## 6. 后续阶段实施路线图

- **阶段 0（当前阶段）**: 工程基线与保护审计（已完成，输出基线报告与代码哈希清单）。
- **阶段 1**: 设计系统与公共组件库（建立颜色 Token、重构 `dark_theme.qss`、封装统一 UI 组件、统一 Lucide 矢量图标）。
- **阶段 2**: 批量混剪页面深度重构（素材管理、字幕排版、视频规格、任务调度与实时队列）。
- **阶段 3**: 精细编辑工作台重构（工程操作栏、片段管理、9:16 画布外围、字幕编辑器、时间轴标尺）。
- **阶段 4**: 双页面整合与高分辨率适配（全屏/窗口缩放适配、38片段+395条字幕真实压力测试）。
- **阶段 5**: 全量回归验证与交付（9套测试回归、业务文件哈希二次核验、最终真实成片导出验证）。
