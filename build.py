#!/usr/bin/env python3
"""
YT-DLP Downloader 双轨自动构建脚本
支持构建:
  --edition slim (精简版: 不打包 FFmpeg 与 yt-dlp, 依赖系统环境或引导安装到系统目录)
  --edition full (完整版: 内置当前平台的静态 FFmpeg 与 yt-dlp 二进制, 100% 离线开箱即用)
"""

from __future__ import annotations

import argparse
import contextlib
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
    parser.add_argument(
        "--dmg",
        action="store_true",
        help="在 macOS 下自动生成 .dmg 安装镜像",
    )
    parser.add_argument(
        "--dmg-dir",
        type=str,
        default="",
        help="指定 .dmg 文件的输出目录（默认为 dist/）",
    )
    return parser.parse_args()


def safe_makedirs(path: str):
    """安全创建目录并忽略异常"""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        _ = e


def safe_rmtree(path: str):
    """安全删除目录并忽略异常"""
    try:
        shutil.rmtree(path)
    except Exception as e:
        _ = e


def prepare_environment(edition: str) -> dict:
    env = os.environ.copy()
    env["YDD_BUILD_EDITION"] = edition

    system = platform.system()
    print(f"[*] 当前操作系统: {system} ({platform.machine()})")
    print(f"[*] 目标构建版本: {edition.upper()}")

    if edition == "full":
        # 检查或准备本地 bin/ 目录下的 ffmpeg 与 yt-dlp
        bin_dir = os.path.join(os.path.dirname(__file__), "bin")
        tools = ["ffmpeg", "yt-dlp"]
        for tool in tools:
            exe_name = f"{tool}.exe" if system == "Windows" else tool
            local_bin = os.path.join(bin_dir, exe_name)

            if not os.path.exists(local_bin):
                print(f"[!] 警告: Full 版本需要内置 {tool} 二进制 ({local_bin})")
                sys_bin = None
                if system == "Darwin":
                    for cand in (
                        f"/opt/homebrew/bin/{exe_name}",
                        f"/usr/local/bin/{exe_name}",
                    ):
                        if os.path.isfile(cand):
                            sys_bin = cand
                            break
                if not sys_bin:
                    sys_bin = shutil.which(tool)
                if sys_bin:
                    print(f"[*] 从系统环境拷贝可用 {tool}: {sys_bin} -> {local_bin}")
                    safe_makedirs(bin_dir)
                    shutil.copy2(sys_bin, local_bin)
                    if system != "Windows":
                        os.chmod(local_bin, 0o755)
                        with open(local_bin, "rb") as bf:
                            if bf.read(2) == b"#!":
                                print(
                                    f"[!] 提示: 拷贝的 {tool} 是依赖本地解释器的脚本文件；若需跨机器离线分发 Full 版，建议替换为官方独立静态二进制 (如 yt-dlp_macos)。"
                                )
                else:
                    print(
                        f"[!] 错误: 未能在本地 bin/ 或系统环境中找到 {exe_name}，请先放置静态二进制或安装 {tool}。"
                    )
                    sys.exit(1)
            else:
                print(f"[*] 检测到内置 {tool} 文件: {local_bin}")

    return env


def create_macos_dmg(edition: str, app_path: str, output_dir: str) -> str:
    """在 macOS 下将 .app 打包为 DMG 镜像并输出到指定目录"""
    dmg_name = f"YT-DLP_Downloader_{edition.capitalize()}_macOS.dmg"
    final_dmg_path = os.path.join(output_dir, dmg_name)

    print(f"[*] 正在为 {edition.upper()} 版本创建 macOS DMG 镜像...")

    # 创建用于组装 DMG 根目录的临时文件夹
    temp_dmg_src = os.path.join(os.path.dirname(app_path), f"dmg_temp_{edition}")
    safe_rmtree(temp_dmg_src)
    safe_makedirs(temp_dmg_src)

    try:
        # 拷贝 .app 到临时目录
        target_app = os.path.join(temp_dmg_src, "YT-DLP_Downloader.app")
        shutil.copytree(app_path, target_app, symlinks=True)

        # 创建 /Applications 快捷方式软链接，方便用户拖拽安装
        apps_link = os.path.join(temp_dmg_src, "Applications")
        if not os.path.exists(apps_link):
            os.symlink("/Applications", apps_link)

        # 如果已有同名 dmg，先删除
        if os.path.exists(final_dmg_path):
            with contextlib.suppress(OSError):
                os.remove(final_dmg_path)

        # 使用 hdiutil 创建 UDZO 压缩镜像
        cmd = [
            "hdiutil",
            "create",
            "-volname",
            f"YT-DLP Downloader ({edition.capitalize()})",
            "-srcfolder",
            temp_dmg_src,
            "-ov",
            "-format",
            "UDZO",
            final_dmg_path,
        ]
        ret = subprocess.run(cmd, capture_output=True, text=True)
        if ret.returncode != 0:
            print(f"[!] 创建 DMG 失败: {ret.stderr}")
            return ""

        print(f"[✓] DMG 制作成功: {final_dmg_path}")
        return final_dmg_path
    finally:
        safe_rmtree(temp_dmg_src)


def run_build(
    edition: str,
    clean: bool = False,
    create_dmg: bool = False,
    target_dmg_dir: str | None = None,
):
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

    if system == "Darwin" and create_dmg:
        app_path = os.path.join(root_dir, "dist", "YT-DLP_Downloader.app")
        dmg_out_dir = target_dmg_dir or os.path.join(root_dir, "dist")
        safe_makedirs(dmg_out_dir)
        create_macos_dmg(edition, app_path, dmg_out_dir)


if __name__ == "__main__":
    args = parse_args()
    run_build(
        edition=args.edition,
        clean=args.clean,
        create_dmg=args.dmg,
        target_dmg_dir=args.dmg_dir or None,
    )
