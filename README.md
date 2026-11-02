# ClipForge (片段工坊)

> Automated Video Mixing Tool · Windows 本地智能短视频全自动混剪工作台

<p align="center">
  <img src="resources/icons/logo.png" width="160" alt="ClipForge Logo" />
</p>

## 项目简介

**ClipForge** 是一款专注于 Windows 本地运行的高性能短视频自动混剪工具。主要用于将小说配音音频、SRT 字幕与多个无声解压/背景视频素材进行智能随机重组，自动化完成画面规整裁切 (9:16)、视频拼接、原音消除、小说音轨合成、中文 SRT 样式化字幕烧录与批量导出。

软件专为单机离线环境打造，**不依赖云端服务、不上传任何素材、不产生任何额外 API 费用**。

---

## 核心特性

- **多源异构素材自适应**: 支持任意数量、任意分辨率、任意编码的视频素材，自动统一规整为 `1080×1920 (9:16)` 竖屏比例与 `30 FPS`。
- **智能随机编排算法**: 采用基于洗牌与动态窗口去重的组合算法，素材充足时保证排列各异；素材不足时自动重组回环，并在音频终点进行毫秒级精准截断。
- **纯粹本地音画合流**: 彻底剥离背景视频原生杂音，以用户提供的小说配音作为唯一音轨，严格保障音画同步与时长绝对对齐。
- **高兼容中文字幕烧录**: 深度集成 FFmpeg 字幕渲染管线，妥善解决 Windows 平台下的中文路径、特殊字符转义与字体回退问题。
- **现代异步架构**: 基于 PySide6 构建响应式图形界面，视频转码与编排任务在独立工作线程中串行执行，界面丝滑无卡顿，提供实时进度追踪与任务隔离。

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
