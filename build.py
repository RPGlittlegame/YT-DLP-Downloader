#!/usr/bin/env python3
"""
YT-DLP Downloader 双轨自动构建脚本
支持构建:
  --edition slim (精简版: 不打包 FFmpeg, 依赖系统环境或首次启动按需下载, ~15MB)
  --edition full (完整版: 内置当前平台的静态 FFmpeg 二进制, 100% 离线开箱即用, ~50MB)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="YT-DLP Downloader 统一构建工具")
    parser.add_argument(
        "--edition",
        choices=["slim", "full"],
        default="slim",
        help="打包版本: slim (精简版) 或 full (全量内置版，默认: slim)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="打包前清理 build/ 和 dist/ 缓存",
    )
    return parser.parse_args()


def safe_makedirs(path: str):
    """安全创建目录并忽略异常"""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


def safe_rmtree(path: str):
    """安全删除目录并忽略异常"""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def prepare_environment(edition: str) -> dict:
    env = os.environ.copy()
    env["YDD_BUILD_EDITION"] = edition

    system = platform.system()
    print(f"[*] 当前操作系统: {system} ({platform.machine()})")
    print(f"[*] 目标构建版本: {edition.upper()}")

    if edition == "full":
        # 检查或准备本地 bin/ 目录下的 ffmpeg
        bin_dir = os.path.join(os.path.dirname(__file__), "bin")
        exe_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
        local_ffmpeg = os.path.join(bin_dir, exe_name)

        if not os.path.exists(local_ffmpeg):
            print(f"[!] 警告: Full 版本需要内置静态 FFmpeg 二进制 ({local_ffmpeg})")
            # 尝试从系统拷贝一份或提示
            sys_ffmpeg = shutil.which("ffmpeg")
            if sys_ffmpeg:
                print(f"[*] 从系统环境拷贝可用 FFmpeg: {sys_ffmpeg} -> {local_ffmpeg}")
                safe_makedirs(bin_dir)
                shutil.copy2(sys_ffmpeg, local_ffmpeg)
                if system != "Windows":
                    os.chmod(local_ffmpeg, 0o755)
            else:
                print(
                    f"[!] 错误: 未能在本地 bin/ 或系统环境中找到 {exe_name}，请先放置静态二进制或安装 ffmpeg。"
                )
                sys.exit(1)
        else:
            print(f"[*] 检测到内置 FFmpeg 文件: {local_ffmpeg}")

    return env


def run_build(edition: str, clean: bool = False):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()

    if clean:
        print("[*] 清理旧构建产物...")
        for d in ["build", "dist"]:
            p = os.path.join(root_dir, d)
            if os.path.exists(p):
                safe_rmtree(p)

    env = prepare_environment(edition)

    # 选择对应的 spec 文件
    if system == "Darwin":
        spec_file = "YT-DLP_Downloader_macOS.spec"
    else:
        spec_file = "YT-DLP_Downloader.spec"

    cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--noconfirm"]
    print(f"[*] 执行构建命令: {' '.join(cmd)}")

    ret = subprocess.run(cmd, cwd=root_dir, env=env)
    if ret.returncode != 0:
        print(f"[x] 打包失败，退出码: {ret.returncode}")
        sys.exit(ret.returncode)

    print(f"[✓] 构建完成！产物位于 dist/ 目录。版本模式: {edition.upper()}")


if __name__ == "__main__":
    args = parse_args()
    run_build(edition=args.edition, clean=args.clean)
