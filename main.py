from core.dependency_manager import dependency_manager
from gui.app import App


def get_ffmpeg_info():
        """动态获取 FFmpeg 二进制文件的路径与来源描述"""
        info = dependency_manager.detect_ffmpeg()
        return info.get("path"), str(info.get("source") or "未检测到")


def get_ffmpeg_path():
        """兼容旧接口"""
        path, _ = get_ffmpeg_info()
        return path


if __name__ == "__main__":
        # 1. 解析 FFmpeg 路径及来源
        ffmpeg_loc, ffmpeg_source = get_ffmpeg_info()

        # 2. 实例化并运行主程序界面
        app = App(ffmpeg_location=ffmpeg_loc, ffmpeg_type=ffmpeg_source)

        # 若未找到 FFmpeg 给出友好提示
        if not ffmpeg_loc:
                app.after(
                        500,
                        lambda: app.update_log(
                                "⚠️ 提示：未检测到 FFmpeg 媒体引擎。点击右上角【⚙️ FFmpeg 配置】可一键自动安装或指定系统路径。"
                        ),
                )

        app.mainloop()
