# YT-DLP Downloader 待修复与完善清单

本文档记录当前代码库中已发现的未完全接通、边界处理异常或文档不一致的待办事项，供后续迭代与修复使用。

---

## 概览

| 编号 | 待修复项 | 优先级 | 状态 | 类别 | 主要涉及文件 |
| --- | --- | --- | --- | --- | --- |
| #1 | 核心依赖管理重构与弹窗接入（yt-dlp & FFmpeg 系统级管理） | 高 | ✅ 已完成 | 功能接入 | [core/dependency_manager.py](core/dependency_manager.py), [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py), [gui/components/dependency_dialog.py](gui/components/dependency_dialog.py) |
| #2 | 仅选择输出格式为 `MP3` 时未自动走纯音频提取流程 | 高 | ⏳ 待修复 | 下载逻辑 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #3 | 自动生成字幕（Auto-captions）无法正常下载 | 中 | ✅ 已兼容 | 下载逻辑 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #4 | 合集/播放列表逐集下载进度回调未触发 | 中 | ✅ 已接入 | 进度展示 | [core/downloader.py](core/downloader.py), [gui/app.py](gui/app.py) |
| #5 | PyInstaller 打包环境下 `cookies/` 目录路径可能只读或临时失效 | 中 | ⏳ 待修复 | 打包兼容 | [gui/app.py](gui/app.py), [core/dependency_manager.py](core/dependency_manager.py) |
| #6 | 文档与界面功能细节不一致 | 低 | ⏳ 待修复 | 文档与 UI | [README.md](README.md), [gui/app.py](gui/app.py) |

---

## 详细清单

### - [x] 1. 核心依赖管理重构与弹窗接入（`refactor/dependency-management` 分支已完成）
* **优先级 / 类别**：高 · 功能接入 / 架构重构
* **涉及位置**：
  * [core/dependency_manager.py](core/dependency_manager.py)（重构为 `yt-dlp` 与 `FFmpeg` 双依赖三级探测及系统目录直装）
  * [core/downloader.py](core/downloader.py)（改为 `subprocess` 调用系统 `yt-dlp` 可执行文件）
  * [gui/components/dependency_dialog.py](gui/components/dependency_dialog.py)（升级为双依赖系统级配置与引导安装弹窗）
  * [gui/app.py](gui/app.py) & [main.py](main.py)（接入 `DependencyDialog`、启动自动检测弹窗、解析/下载缺失拦截提示）
  * [requirements.txt](requirements.txt), [build.py](build.py), [YT-DLP_Downloader.spec](YT-DLP_Downloader.spec), [YT-DLP_Downloader_macOS.spec](YT-DLP_Downloader_macOS.spec)（移除 `imageio-ffmpeg` 与 `yt_dlp` Python 库依赖，更新 Slim/Full 双轨构建）
* **已完成改造**：
  1. 探测优先级统一为：`用户自定义路径 (~/.ydd/config.json)` ➔ `系统环境（macOS 优先 /opt/homebrew/bin）` ➔ `Full 版内置目录 (bin/)`；移除 `~/.ydd/bin/` 私有二进制缓存、`imageio-ffmpeg` 与全盘 `site-packages` 扫描。
  2. 一键安装直接部署到系统默认目录（macOS 优先 `/opt/homebrew/bin`，无写权限时通过系统授权弹窗提权写入）。
  3. 下载器底层改为 `subprocess` 调用外部 `yt-dlp` 可执行文件，与 `FFmpeg` 管理保持完全一致。
  4. 接入 `DependencyDialog` 到主界面徽章，并在启动缺失、点击解析或点击下载缺依赖时提供软件级弹窗引导。

---

### - [ ] 2. 仅选择输出格式为 `MP3` 时未自动走纯音频提取流程
* **优先级 / 类别**：高 · 下载逻辑
* **涉及位置**：
  * [core/downloader.py](core/downloader.py#L354-L391)（`YTDlpDownloader.download` 的格式与后处理分支）
  * [gui/app.py](gui/app.py#L248-L255)（`format_combo` 下拉选项 `["MP4", "MKV", "AVI", "WMV", "MOV", "MP3"]`）
  * [gui/app.py](gui/app.py#L980-L984)（`on_download` 参数读取）
* **现象与原因**：
  在 `YTDlpDownloader.download()` 中，只有当 `video_format_id == "none"`（即用户在“视频”下拉框手动选择了 `无 (仅音频)`）时，才会走 `extract_audio` 与 `FFmpegExtractAudio` 后处理分支。如果用户保持“视频”选项为默认的 `自动 (Best)`，仅把“格式”下拉框改为 `MP3`，代码仍会走 `v_id != "none"` 分支，将 `opts["format"]` 设为 `bestvideo+bestaudio/best` 并设置 `opts["merge_output_format"] = "mp3"`，导致混流失败或无法输出纯 MP3 音频。
* **修复建议**：
  1. 在 `core/downloader.py` 中对纯音频目标格式（如 `format_type in {"mp3", "m4a", "wav", "flac", "opus"}`）做统一判定：即使 `v_id != "none"`，也视为纯音频提取，选用音频流（`a_id` 为 `best`/`none` 时回退到 `bestaudio/best`）并挂载 `FFmpegExtractAudio` 后处理器。
  2. 可选优化：在 `gui/app.py` 中监听 `format_combo` 变化，当用户选择 `MP3` 等音频格式时联动提示或自动将视频选项切换为 `无 (仅音频)`，防止后续误选字幕嵌入等仅适用于视频的选项。

---

### - [x] 3. 自动生成字幕（Auto-captions）无法正常下载（已兼容）
* **优先级 / 类别**：中 · 下载逻辑
* **涉及位置**：
  * [core/downloader.py](core/downloader.py#L457-L470)（`download` 字幕 CLI 参数配置）
* **当前状态**：
  重构为系统 `yt-dlp` 子进程调用后，已同时传入 `--write-subs` 与 `--write-auto-subs`，可正常下载自动生成字幕。

---

### - [x] 4. 合集/播放列表逐集下载进度回调未触发（已接入）
* **优先级 / 类别**：中 · 进度展示
* **涉及位置**：
  * [gui/app.py](gui/app.py#L42)（向 `YTDlpDownloader` 传入 `playlist_item_callback=self.update_item_progress`）
  * [core/downloader.py](core/downloader.py#L514-L520)（解析 `[download] Downloading item X of Y` 并触发 `playlist_item_callback`）
* **当前状态**：
  在子进程输出解析中已捕获 `[download] Downloading item X of Y` 行并触发 `self.playlist_item_callback(idx, total, ...)`。

---

### - [ ] 5. PyInstaller 打包环境下 `cookies/` 目录路径可能只读或临时失效
* **优先级 / 类别**：中 · 打包兼容
* **涉及位置**：
  * [gui/app.py](gui/app.py#L59-L61)（`self.cookie_dir` 路径计算）
  * [gui/app.py](gui/app.py#L612-L681)（`update_cookie_list` 与 `import_cookie_file`）
  * [core/dependency_manager.py](core/dependency_manager.py#L56-L59)（应用数据目录 `~/.ydd/` 规范）
* **现象与原因**：
  `App.__init__` 目前直接通过 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 推导 `self.cookie_dir`。在源码运行时它指向项目根目录的 `cookies/`；但在 PyInstaller 打包后（尤其是 macOS `.app` 或单文件模式），`__file__` 指向应用包内部或临时解压目录 `_MEIPASS`，会导致导入的 Cookie 文件在只读包内写入失败，或在重启后丢失。相比之下，`DependencyManager` 已经统一将配置与缓存存放在可写的 `~/.ydd/` 目录。
* **修复建议**：
  1. 判断 `getattr(sys, "frozen", False)`：打包环境下将 `self.cookie_dir` 指向用户数据目录 `~/.ydd/cookies/`（复用 `DependencyManager._get_app_data_dir()` 或统一的路径工具函数）；源码开发模式下可保留项目内 `cookies/` 或统一使用 `~/.ydd/cookies/`。
  2. 在 `import_cookie_file()` 中确保目标目录自动创建，并在 UI 上或日志中明确展示当前 Cookie 存储路径，方便用户管理与清理。

---

### - [ ] 6. 文档与界面功能细节不一致
* **优先级 / 类别**：低 · 文档与 UI
* **涉及位置**：
  * [README.md](README.md#L1)（首行标题存在多余字符：`z# YT-DLP Downloader`）
  * [README.md](README.md#L12)（功能描述写明“支持一键切换深色/浅色模式”）
  * [gui/app.py](gui/app.py#L16)（当前固定为 `ctk.set_appearance_mode("System")`，界面无切换按钮）
* **现象与原因**：
  1. `README.md` 第 1 行多了一个字母 `z`，导致 Markdown 一级标题无法正确渲染。
  2. `README.md` 第 12 行宣传了“支持一键切换深色/浅色模式”，但实际 GUI 中仅在初始化时调用 `ctk.set_appearance_mode("System")` 跟随系统主题，未提供手动切换深色/浅色模式的控件。
* **修复建议**：
  1. 修正 `README.md` 第 1 行的拼写错误，改为 `# YT-DLP Downloader`。
  2. 择一对齐：在 `gui/app.py` 顶部栏增加深色/浅色/跟随系统的切换按钮（调用 `ctk.set_appearance_mode(...)`），或者将 `README.md` 第 12 行修改为与实际一致的“自动跟随系统深色/浅色主题”。
