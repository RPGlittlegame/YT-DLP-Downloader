# YT-DLP Downloader

基于 `yt-dlp` 和 `CustomTkinter` 构建的现代化跨平台视频下载器。

## 🌟 特性

- **现代化交互界面**: 采用类似 MacOS 的清爽设计和深色模式。
- **一键解析**: 输入链接后快速获取视频信息。
- **自定义下载选项**: 
  - 支持画质选择（最高画质、1080P、720P、仅音频）。
  - 支持封装格式选择（MP4, MKV, MP3）。
- **Cookie 注入**: 支持选择本地 `cookies.txt` 文件，用于下载受限内容（如会员视频）。
- **实时进度反馈**: 底部配有进度条和滚动日志，随时掌握下载状态。
- **跨平台与独立打包**: 架构上支持通过 PyInstaller 打包成无需配置 Python 环境的单体程序。

---

## 🛠️ 测试准备：配置 `bin` 文件夹 (关键)

由于 `yt-dlp` 在合并最佳音频与视频轨道，或提取纯音频格式时，**必须依赖外部工具 FFmpeg**，因此在首次运行代码测试前，请务必完成以下准备：

1. **创建目录**: 在项目根目录下，新建一个名为 `bin` 的文件夹。
2. **下载 FFmpeg**:
   - **Windows 用户**: 前往 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`。
   - **macOS 用户**: 可以下载静态编译好的 [FFmpeg 二进制文件](https://evermeet.cx/ffmpeg/)。
3. **放置文件**:
   - 将下载的压缩包解压。
   - 找到其中的 `ffmpeg.exe` (Windows) 或 `ffmpeg` (Mac) 二进制可执行文件。
   - **将该文件移动/粘贴到刚刚创建的 `bin` 文件夹中。**

你的最终工作区目录结构应该符合如下形式：
```text
YT-DLP Downloader/
├── bin/
│   └── ffmpeg.exe    <-- 确保它在这里 (Mac下为 ffmpeg 无后缀)
├── core/
│   └── downloader.py
├── gui/
│   └── app.py
├── main.py
├── requirements.txt
└── README.md
```

---

## 🚀 运行指南

### 1. 安装依赖环境

请确保您已安装 Python 3.8 或更高版本。在您的虚拟环境或全局环境中运行：

```bash
pip install -r requirements.txt
```

### 2. 启动应用

确认 `bin/ffmpeg` 已正确放置后，执行主入口启动图形界面：

```bash
python main.py
```

### 3. 使用说明

1. **输入链接**: 将网页视频的 URL 粘贴至顶部的地址栏。
2. **获取信息**: 点击 **[解析]** 按钮。稍等片刻，UI 界面将显示出该视频的实际标题（测试网络连通性和 yt-dlp 支持）。
3. **自定义配置**:
   - 根据需求在下拉框中调整清晰度（最高画质 / 1080P 等）。
   - 在分段选择器中切换封装格式（MP4 / MKV / MP3）。
   - 点击 **[选择目录]** 设定你想保存视频的本地文件夹。
   - （可选）若需下载会员专享内容，请借助浏览器插件导出 `cookies.txt` 文件，并在 UI 中选择加载。
4. **执行下载**: 点击底部的 **[开始下载]**。此时可以观察下方的进度条和日志终端框，它将实时反馈当前的下载百分比和速度。

---

## 📦 进阶：如何独立打包 (PyInstaller)

本项目支持被打包为不需要 Python 环境的便携软件。

**Windows 打包参考命令**:
```bash
pyinstaller --noconfirm --onedir --windowed --add-data "bin/ffmpeg.exe;bin/" main.py
```
*注：`--add-data` 参数确保了打包后程序会在自身的临时运行目录 (`sys._MEIPASS`) 或根目录下解压并携带 `bin/ffmpeg.exe`。*
