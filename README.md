# ClipForge 3.0 (片段工坊)

> Automated Video Mixing & Matrix Color Studio · Windows 本地智能短视频全自动混剪与批量矩阵调色工作台

<p align="center">
  <img src="resources/icons/logo.png" width="160" alt="ClipForge Logo" />
</p>

## 项目简介

**ClipForge 3.0** 是一款专注于 Windows 本地运行的高性能短视频工坊。包含三大核心业务能力：
1. **智能全自动混剪**：将小说配音音频、SRT 字幕与多个解压背景素材进行智能随机重组，自动化规整 (9:16)、视频拼接、小说音轨合成、中文字幕样式化烧录与批量导出。
2. **精细编辑工作台**：对各片段进行精细化预览、微调与时间轴交互。
3. **批量矩阵调色大师 (3.0 新增)**：针对短视频矩阵铺量分发需求，一键对视频施加 7 色色调滤镜（原色、红、黄、紫、绿、蓝、黑白）、滑块无极强度调色、1280×720 横屏 / 720×1280 竖屏适配、二创角标、防重微指纹，支持 NVIDIA NVENC (如 GTX 1650 SUPER) 双路极速硬件编码加速。

软件专为单机离线环境打造，**不依赖云端服务、不上传任何素材、不产生任何额外 API 费用**。提供一体化工作台与独立免安装运行脚本。

---

## 核心特性

- **矩阵调色与规格规整 (v3.0)**: 支持原色与红、黄、紫、绿、蓝、黑白 7 大色偏预设，0~100% 强度自由混合；同时输出 1280×720 横板与 720×1280 竖版规格，支持添加半透明角标与防搬重微指纹。
- **极致 GPU 硬件加速 (NVENC)**: 深度适配 NVIDIA 图灵架构 (GTX 1650 SUPER / RTX 系列) 独立硬件编码器，双路并行流水线，15 分钟长视频几十秒硬件导出，杜绝 CPU 占满卡顿。
- **60 FPS 毫秒级调色监视器**: 基于 OpenCV 内存渲染，拖动时间轴与强度滑块实时 WYSIWYG 所见即所得，点击屏幕秒切颜色对比。
- **多源异构素材自适应**: 支持任意数量、任意分辨率、任意编码的视频素材，自动统一规整为 `1080×1920 (9:16)` 竖屏比例与 `30 FPS`。
- **智能随机编排算法**: 采用基于洗牌与动态窗口去重的组合算法，素材充足时保证排列各异；素材不足时自动重组回环，并在音频终点进行毫秒级精准截断。
- **纯粹本地音画合流**: 彻底剥离背景视频原生杂音，以用户提供的小说配音作为唯一音轨，严格保障音画同步与时长绝对对齐。
- **高兼容中文字幕烧录**: 深度集成 FFmpeg 字幕渲染管线，妥善解决 Windows 平台下的中文路径、特殊字符转义与字体回退问题。
- **双机部署支持**: 支持作为一体化标签页运行，也可通过 `python run_color_matrix.py` 单独启动专职调色独立版本，满足多电脑协作需求。

---

## 技术架构

```
ClipForge/
├── app/
│   ├── ui/                    # PySide6 界面层
│   │   ├── main_window.py     # 主界面工作台
│   │   ├── widgets/           # 自定义卡片与控制组件
│   │   └── dialogs/           # 日志与详情弹窗
│   ├── core/                  # 核心计算与媒体管线
│   │   ├── media_scanner.py   # 素材扫描与合法性过滤
│   │   ├── media_probe.py     # 媒体元数据探测 (FFprobe / FFmpeg)
│   │   ├── randomizer.py      # 视频组合排程算法 (洗牌+去重+截断)
│   │   ├── timeline_builder.py# 剪辑时间轴与指令生成器
│   │   ├── video_processor.py # FFmpeg 滤镜图与渲染管线
│   │   ├── subtitle_processor.py # SRT 字幕转义与样式处理
│   │   └── export_manager.py  # 批量渲染排程与状态管理
│   ├── services/              # 辅助服务
│   │   ├── config_service.py  # 用户参数持久化 (JSON)
│   │   ├── task_service.py    # QThread 异步任务调度与取消
│   │   └── log_service.py     # 本地运行日志与错误归档
│   └── utils/
│       ├── path_utils.py      # 中文路径与转义工具
│       └── ffmpeg_utils.py    # FFmpeg 进程调度与进度解析
├── resources/
│   ├── icons/                 # 应用与界面图标
│   └── styles/                # QSS 样式表
├── bin/                       # 存放 ffmpeg.exe / ffprobe.exe
├── temp/                      # 临时拼接片段与转码缓存 (自动清理)
├── output/                    # 最终生成 MP4 导出目录
└── logs/                      # 诊断日志
```

---

## 运行环境与安装

### 运行需求
- 操作系统: Windows 10 / 11 (x64)
- Python: 3.11+
- FFmpeg: 包含 `libass` 滤镜支持的静态编译版本

### 依赖安装
```powershell
pip install -r requirements.txt
```

---

## 许可证与合规声明

- 本项目采用开源协议，供个人创作与学习使用。
- 视频编解码基于 FFmpeg (LGPL/GPL)。打包分发遵循对应开源许可证。
