import sys
import os
from gui.app import App

def get_ffmpeg_path():
    """
    动态获取 FFmpeg 二进制文件的路径。
    支持在开发环境和 PyInstaller 打包后的生产环境中查找同级 bin 目录。
    """
    # 检查是否是被 PyInstaller 打包的环境
    if getattr(sys, 'frozen', False):
        # sys.executable 是打包后生成的 exe 文件所在的路径
        base_dir = os.path.dirname(sys.executable)
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
    app.mainloop()
