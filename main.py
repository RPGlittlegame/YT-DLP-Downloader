from core.dependency_manager import dependency_manager
from gui.app import App


def get_dependency_info():
    """动态探测系统 yt-dlp 与 FFmpeg 依赖状态"""
    return dependency_manager.detect_all()


def get_ffmpeg_info():
    """兼容旧接口：获取 FFmpeg 路径与来源描述"""
    info = dependency_manager.detect_ffmpeg()
    return info.get("path"), str(info.get("source") or "未检测到")


def get_ffmpeg_path():
    """兼容旧接口"""
    path, _ = get_ffmpeg_info()
    return path


if __name__ == "__main__":
    # 1. 系统级探测 yt-dlp 与 FFmpeg（macOS 优先 Homebrew）
    deps = get_dependency_info()
    ffmpeg_info = deps.get("ffmpeg", {})
    ytdlp_info = deps.get("yt-dlp", {})

    ffmpeg_loc = ffmpeg_info.get("path")
    ffmpeg_source = str(ffmpeg_info.get("source") or "未检测到")
    ytdlp_loc = ytdlp_info.get("path")
    ytdlp_source = str(ytdlp_info.get("source") or "未检测到")

    # 2. 实例化并运行主程序界面（缺失依赖时界面将自动弹出引导配置）
    app = App(
        ffmpeg_location=ffmpeg_loc,
        ffmpeg_type=ffmpeg_source,
        ytdlp_location=ytdlp_loc,
        ytdlp_type=ytdlp_source,
    )
    app.mainloop()
