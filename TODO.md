# YT-DLP Downloader 待修复与完善清单

本文档记录项目代码库中梳理出的已修复与待办事项，当前所有 6 项均已在 `main` 主干修复并验证。

---

## 概览

| 编号 | 待修复项 | 优先级 | 状态 | 类别 | 主要涉及文件 |
| --- | --- | --- | --- | --- | --- |
| #1 | 核心依赖管理重构与弹窗接入（yt-dlp & FFmpeg 系统级管理） | 高 | ✅ 已完成 | 功能接入 | [core/dependency_manager.py](core/dependency_manager.py), [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py), [gui/components/dependency_dialog.py](gui/components/dependency_dialog.py) |
| #2 | 选择 `MP3` / `M4A` 音频格式时自动走纯音频提取与 UI 联动 | 高 | ✅ 已完成 | 下载逻辑 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #3 | 精确区分手动字幕与自动生成字幕（Auto-captions） | 中 | ✅ 已完成 | 下载逻辑 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #4 | 合集/播放列表逐集下载进度回调与真实标题解析 | 中 | ✅ 已完成 | 进度展示 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #5 | PyInstaller 打包环境下 `cookies/` 目录路径持久化 | 中 | ✅ 已完成 | 打包兼容 | [gui/app.py](gui/app.py) |
| #6 | 修正文档首行拼写并在界面增加一键切换深浅色主题按钮 | 低 | ✅ 已完成 | 文档与 UI | [README.md](README.md), [gui/app.py](gui/app.py) |

---

## 详细清单

### - [x] 1. 核心依赖管理重构与弹窗接入
* **优先级 / 类别**：高 · 功能接入 / 架构重构
* **涉及位置**：
  * [core/dependency_manager.py](core/dependency_manager.py)（重构为 `yt-dlp` 与 `FFmpeg` 双依赖三级探测及系统目录直装）
  * [core/downloader.py](core/downloader.py)（改为 `subprocess` 调用系统 `yt-dlp` 可执行文件）
  * [gui/components/dependency_dialog.py](gui/components/dependency_dialog.py)（升级为双依赖系统级配置与引导安装弹窗）
  * [gui/app.py](gui/app.py) & [main.py](main.py)（接入 `DependencyDialog`、启动自动检测弹窗、解析/下载缺失拦截提示）
  * [requirements.txt](requirements.txt), [build.py](build.py), [YT-DLP_Downloader.spec](YT-DLP_Downloader.spec), [YT-DLP_Downloader_macOS.spec](YT-DLP_Downloader_macOS.spec)
* **已完成改造**：
  1. 探测优先级统一为：`用户自定义路径 (~/.ydd/config.json)` ➔ `系统环境（macOS 优先 Homebrew，随后全面覆盖 PATH、MacPorts/Nix/Fink、Python/pip/pipx/pyenv/asdf/mise、Conda、应用目录及 FFmpeg 的 imageio_ffmpeg 兜底；Windows 覆盖 WinGet/Scoop/Chocolatey/Python/Conda；Linux 覆盖 apt/dnf/pacman、Linuxbrew/Snap/Flatpak/Nix/Conda）` ➔ `Full 版内置目录 (bin/)`；移除 `~/.ydd/bin/` 私有二进制缓存与 `requirements.txt` 中的 `imageio-ffmpeg` 必装依赖。
  2. 一键安装直接部署到系统默认目录（macOS 默认锁定 Homebrew 目录：Apple Silicon 为 `/opt/homebrew/bin`，Intel 为 `/usr/local/bin`，无写权限时通过系统授权弹窗提权写入）。
  3. Linux 终端安装命令同时支持并自动识别 `apt`、`dnf`、`pacman`。
  4. 下载器底层改为 `subprocess` 调用外部 `yt-dlp` 可执行文件，与 `FFmpeg` 管理保持完全一致。
  5. 接入 `DependencyDialog` 到主界面徽章，并在启动缺失、点击解析或点击下载缺依赖时提供软件级弹窗引导。

---

### - [x] 2. 选择 `MP3` / `M4A` 音频格式时自动走纯音频提取与 UI 联动
* **优先级 / 类别**：高 · 下载逻辑
* **涉及位置**：
  * [core/downloader.py](core/downloader.py#L417-L450)（`YTDlpDownloader.download` 纯音频判断与参数生成）
  * [gui/app.py](gui/app.py#L244-L280)（默认选项与 `format_combo` / `v_quality_combo` 绑定）
  * [gui/app.py](gui/app.py#L674-L695)（`_on_format_select` 与 `_on_video_quality_select` 联动）
* **已完成改造**：
  1. 后端在 `video_format_id == "none"` 或 `format_type` 属于音频格式集合（`mp3`/`m4a`/`wav`/`flac`/`opus`）时统一走纯音频提取流程（`-f bestaudio/best` 或指定音频流 + `-x --audio-format ...`），不传 `--merge-output-format` 与 `--embed-subs`。
  2. 前端增加 `M4A` 选项并实现「格式」与「视频流」双向联动：选 `MP3`/`M4A` 自动切为 `无 (仅音频)`，选回视频格式自动切回 `自动 (Best)`。

---

### - [x] 3. 精确区分手动字幕与自动生成字幕（Auto-captions）
* **优先级 / 类别**：中 · 下载逻辑
* **涉及位置**：
  * [gui/app.py](gui/app.py#L991-L999)（`s_opts_map` 保存 `lang` 与 `auto` 标识）
  * [gui/app.py](gui/app.py#L1185-L1195)（`on_download` 读取 `subtitle_auto` 并传递给下载器）
  * [core/downloader.py](core/downloader.py#L369-L473)（`subtitle_auto` 精确控制 `--write-subs` / `--write-auto-subs`）
* **已完成改造**：
  1. `s_opts_map` 保留字幕元数据中的 `auto` 标记，下载时透传 `subtitle_auto` 参数。
  2. 当 `subtitle_auto=True` 时仅传 `--write-auto-subs`，`False` 时仅传 `--write-subs`，`None` 时兼容两者，并将 `--sub-format` 设为 `srt/vtt/best`。

---

### - [x] 4. 合集/播放列表逐集下载进度回调与真实标题解析
* **优先级 / 类别**：中 · 进度展示
* **涉及位置**：
  * [core/downloader.py](core/downloader.py#L514-L520)（解析 `[download] Downloading item X of Y` 并触发 `playlist_item_callback`）
  * [gui/app.py](gui/app.py#L856-L883)（`update_item_progress` 匹配 `self.playlist_entries` 展示真实分集标题）
* **已完成改造**：
  1. 在 `YTDlpDownloader.download()` 输出流中捕获播放列表切集信号并回调 `playlist_item_callback(idx, total, ...)`。
  2. `App.update_item_progress()` 根据条目索引从 `self.playlist_entries` 解析出真实分集标题并展示在状态栏与日志中。

---

### - [x] 5. PyInstaller 打包环境下 `cookies/` 目录路径持久化
* **优先级 / 类别**：中 · 打包兼容
* **涉及位置**：
  * [gui/app.py](gui/app.py#L75)（初始化调用 `_resolve_cookie_dir()`）
  * [gui/app.py](gui/app.py#L642-L664)（`_resolve_cookie_dir` 区分打包态与源码态）
* **已完成改造**：
  * 在 PyInstaller 打包环境下（`getattr(sys, "frozen", False)`）将 Cookie 存储目录定位到 `~/.ydd/cookies`，避免写入只读包体或临时解压目录；源码运行优先使用可写的项目 `cookies/` 目录并在不可写时回退 `~/.ydd/cookies`。

---

### - [x] 6. 修正文档首行拼写并在界面增加一键切换深浅色主题按钮
* **优先级 / 类别**：低 · 文档与 UI
* **涉及位置**：
  * [README.md](README.md#L1)（修正标题为 `# YT-DLP Downloader`）
  * [gui/app.py](gui/app.py#L77-L83) & [gui/app.py](gui/app.py#L221-L234)（顶部状态栏主题按钮 `theme_btn`）
  * [gui/app.py](gui/app.py#L666-L672)（`toggle_appearance_mode` 一键循环切换逻辑）
* **已完成改造**：
  1. 修复了 `README.md` 第 1 行多余字符 `z`。
  2. 在主界面顶部右侧新增「🌓 主题: 系统 / ☀️ 浅色 / 🌙 深色」一键循环切换按钮，调用 `ctk.set_appearance_mode()` 即时切换外观。
