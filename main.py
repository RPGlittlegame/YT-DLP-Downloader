import importlib.util
import os
import shutil
import sys

from gui.app import App


def get_ffmpeg_path():
    """
    动态获取 FFmpeg 二进制文件的路径。
    多级降级策略保证全平台开箱即用：
    1. 优先查找应用内置或同级 bin 目录 (打包分发或本地放置)
    2. 尝试从已安装的 imageio_ffmpeg 中获取随包分发的静态二进制
    3. 查找操作系统环境变量 PATH 中的 ffmpeg
    4. 兜底返回 None
    """
    # 1. 检查应用内置 / bin 目录
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    local_bin_path = os.path.join(base_dir, "bin", ffmpeg_name)
    try:
        if os.path.exists(local_bin_path) and os.access(
            local_bin_path, os.X_OK if sys.platform != "win32" else os.F_OK
        ):
            return local_bin_path
    except OSError as err:
        print(f"[调试] 本地 bin 访问检查异常: {err}")

    # 2. 检查 imageio_ffmpeg 提供的免安装静态二进制
    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        try:
            imageio_ffmpeg_module = importlib.import_module("imageio_ffmpeg")
            img_ffmpeg = getattr(
                imageio_ffmpeg_module, "get_ffmpeg_exe", lambda: None
            )()
            if img_ffmpeg and os.path.exists(img_ffmpeg):
                return img_ffmpeg
        except Exception as err:
            print(f"[调试] imageio_ffmpeg 加载异常: {err}")

    # 3. 检查系统全局 PATH 环境变量
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg and os.path.exists(system_ffmpeg):
        return system_ffmpeg

    # 4. 未找到可用 FFmpeg
    return None


if __name__ == "__main__":
    # 1. 解析 FFmpeg 路径
    ffmpeg_loc = get_ffmpeg_path()

    # 2. 实例化并运行主程序界面
    app = App(ffmpeg_location=ffmpeg_loc)

    # 若未找到 FFmpeg 给出友好提示
    if not ffmpeg_loc:
        app.after(
            500,
            lambda: app.update_log(
                "⚠️ 提示：未检测到 FFmpeg。建议执行 pip install imageio-ffmpeg 或安装系统 FFmpeg 以启用高清音视频自动合并。"
            ),
        )

    app.mainloop()
