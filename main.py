import sys
import os
from gui.app import App

def get_ffmpeg_path():
    """
    动态获取 FFmpeg 二进制文件的路径。
    支持在开发环境和 PyInstaller 打包后的生产环境中查找同级 bin 目录。
    """
    if getattr(sys, 'frozen', False):
        # 打包后，资源文件位于 sys._MEIPASS (即 _internal 文件夹)
        base_dir = sys._MEIPASS
    else:
        # 否则就是普通的 Python 脚本运行，__file__ 就是本文件路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    # 判断操作系统以确定拓展名
    if sys.platform == "win32":
        ffmpeg_name = "ffmpeg.exe"
    else:
        ffmpeg_name = "ffmpeg"  # macOS 或 Linux 下没有 .exe 后缀
        
    ffmpeg_path = os.path.join(base_dir, 'bin', ffmpeg_name)
    
    # 检查文件是否存在
    if not os.path.exists(ffmpeg_path):
        print(f"[警告] 未在 {ffmpeg_path} 找到 FFmpeg。某些合并音视频或转换格式的操作可能会失败。")
        # 依然返回路径，让 yt-dlp 自己决定是否报错（或者系统 PATH 变量里已经有 FFmpeg）
        return ffmpeg_path
        
    return ffmpeg_path

if __name__ == "__main__":
    # 1. 解析 FFmpeg 路径
    ffmpeg_loc = get_ffmpeg_path()
    
    # 2. 实例化并运行主程序界面
    app = App(ffmpeg_location=ffmpeg_loc)
    
    # 增加 FFmpeg 检查警告显示
    if not os.path.exists(ffmpeg_loc):
        app.after(500, lambda: app.update_log(
            "⚠️ 警告：未找到内置 FFmpeg。合并音视频功能将不可用。"
        ))
        
    app.mainloop()
