from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable


class DependencyManager:
    """
    依赖管理器（单例模式）：
    负责探测、校验系统环境中的 FFmpeg、管理用户自定义路径、本地缓存目录及提供一键下载解压能力。
    """

    # 官方/权威免安装静态二进制包下载镜像源
    FFMPEG_DOWNLOAD_URLS = {
        "windows_x64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "macos_arm64": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "macos_x86_64": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "linux_x64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    }

    # 各系统终端快速安装命令参考
    INSTALL_COMMANDS = {
        "darwin": "brew install ffmpeg",
        "win32": "winget install Gyan.FFmpeg",
        "linux": "sudo apt update && sudo apt install ffmpeg",
    }

    def _ensure_dir(self, directory: str) -> None:
        try:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
        except OSError:
            pass

    def __init__(self):
        self.app_data_dir = self._get_app_data_dir()
        self.bin_cache_dir = os.path.join(self.app_data_dir, "bin")
        self.config_file = os.path.join(self.app_data_dir, "config.json")
        self._ensure_dir(self.bin_cache_dir)
        self._custom_ffmpeg_path = self._load_custom_path()

    @staticmethod
    def _get_app_data_dir() -> str:
        """获取应用全局配置/缓存目录 ~/.ydd/"""
        home = os.path.expanduser("~")
        return os.path.join(home, ".ydd")

    def _load_custom_path(self) -> str | None:
        """从配置文件中读取用户自定义的 FFmpeg 路径"""
        if not os.path.exists(self.config_file):
            return None
        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("ffmpeg_path")
                return str(val) if val else None
        except Exception:
            return None

    def save_custom_path(self, path: str | None) -> bool:
        """持久化保存用户自定义的 FFmpeg 路径"""
        self._custom_ffmpeg_path = path
        try:
            data = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            if path:
                data["ffmpeg_path"] = path
            else:
                data.pop("ffmpeg_path", None)

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def verify_executable(path: str) -> tuple[bool, str]:
        """
        验证指定路径的 FFmpeg 二进制是否可用及可执行，并提取版本简述
        """
        if not path or not os.path.exists(path):
            return False, "文件不存在"

        # 检查可执行权限
        if sys.platform != "win32":
            try:
                st = os.stat(path)
                if not bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                    os.chmod(
                        path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    )
            except OSError:
                pass

        try:
            # 运行 ffmpeg -version 进行真实验证
            res = subprocess.run(
                [path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            if res.returncode == 0:
                first_line = res.stdout.splitlines()[0] if res.stdout else "ffmpeg"
                return True, first_line
            return False, f"返回码异常: {res.returncode}"
        except Exception as e:
            return False, f"执行失败: {e}"

    def detect_ffmpeg(self) -> dict[str, str | None]:
        """
        多级探测 FFmpeg 依赖可用性：
        1. 用户自定义配置 (Custom)
        2. 系统 PATH 环境 (System PATH)
        3. 应用本地数据缓存目录 (~/.ydd/bin/ffmpeg)
        4. 打包内置 bin/ 目录 (Bundled bin)
        5. Python 静态库 imageio_ffmpeg
        """
        ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

        # 1. 检查用户配置
        if self._custom_ffmpeg_path:
            valid, info = self.verify_executable(self._custom_ffmpeg_path)
            if valid:
                return {
                    "path": self._custom_ffmpeg_path,
                    "source": "自定义路径",
                    "status": "ok",
                    "info": info,
                }

        # 2. 检查系统全局 PATH 环境变量 (系统优先，零冗余)
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            valid, info = self.verify_executable(system_ffmpeg)
            if valid:
                return {
                    "path": system_ffmpeg,
                    "source": "系统 PATH",
                    "status": "ok",
                    "info": info,
                }

        # 3. 检查应用本地缓存目录 ~/.ydd/bin/
        cached_bin = os.path.join(self.bin_cache_dir, ffmpeg_name)
        if os.path.exists(cached_bin):
            valid, info = self.verify_executable(cached_bin)
            if valid:
                return {
                    "path": cached_bin,
                    "source": "本地缓存 (一键安装)",
                    "status": "ok",
                    "info": info,
                }

        # 4. 检查打包内置 / bin/ 目录
        if getattr(sys, "frozen", False):
            base_dir = getattr(
                sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
            )
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundle_bin = os.path.join(base_dir, "bin", ffmpeg_name)
        if os.path.exists(bundle_bin):
            valid, info = self.verify_executable(bundle_bin)
            if valid:
                return {
                    "path": bundle_bin,
                    "source": "内置引擎 (bin)",
                    "status": "ok",
                    "info": info,
                }

        # 5. 检查 imageio_ffmpeg 静态库
        if importlib.util.find_spec("imageio_ffmpeg") is not None:
            try:
                imageio_ffmpeg_mod = importlib.import_module("imageio_ffmpeg")
                get_exe = getattr(imageio_ffmpeg_mod, "get_ffmpeg_exe", None)
                if callable(get_exe):
                    img_ffmpeg = get_exe()
                    if isinstance(img_ffmpeg, str) and os.path.exists(img_ffmpeg):
                        valid, info = self.verify_executable(img_ffmpeg)
                        if valid:
                            return {
                                "path": img_ffmpeg,
                                "source": "静态引擎 (imageio)",
                                "status": "ok",
                                "info": info,
                            }
            except Exception:
                pass

        return {
            "path": None,
            "source": "未检测到",
            "status": "missing",
            "info": "未找到可用的 FFmpeg",
        }

    def get_quick_install_command(self) -> str:
        """获取当前系统适用的快速包管理安装命令"""
        if sys.platform == "darwin":
            return self.INSTALL_COMMANDS["darwin"]
        elif sys.platform == "win32":
            return self.INSTALL_COMMANDS["win32"]
        return self.INSTALL_COMMANDS["linux"]

    def get_download_url(self) -> str | None:
        """获取适合当前平台架构的官方静态二进制下载地址"""
        system = sys.platform
        arch = platform.machine().lower()

        if system == "win32":
            return self.FFMPEG_DOWNLOAD_URLS["windows_x64"]
        elif system == "darwin":
            if "arm" in arch or "aarch64" in arch:
                return self.FFMPEG_DOWNLOAD_URLS["macos_arm64"]
            return self.FFMPEG_DOWNLOAD_URLS["macos_x86_64"]
        elif system.startswith("linux"):
            return self.FFMPEG_DOWNLOAD_URLS["linux_x64"]
        return None

    def download_and_install_ffmpeg(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_event=None,
    ) -> tuple[bool, str]:
        """
        异步流式下载静态 FFmpeg 并解压配置到 ~/.ydd/bin/
        :param progress_callback: (0.0~1.0, 状态文本)
        :param cancel_event: 外部 threading.Event 控制取消
        """
        url = self.get_download_url()
        if not url:
            return (
                False,
                f"暂不支持当前系统架构 ({sys.platform}-{platform.machine()}) 的自动下载",
            )

        ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        target_path = os.path.join(self.bin_cache_dir, ffmpeg_name)
        archive_name = "ffmpeg_download.tmp"
        temp_archive_path = os.path.join(self.app_data_dir, archive_name)

        try:
            if progress_callback:
                progress_callback(0.05, "正在连接下载节点...")

            # 1. 下载文件
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (YT-DLP-Downloader-Installer)"},
            )
            with (
                urllib.request.urlopen(req, timeout=30) as response,
                open(temp_archive_path, "wb") as out_file,
            ):
                total_length = response.headers.get("content-length")
                total_size = int(total_length) if total_length else None
                downloaded = 0
                block_size = 1024 * 64

                while True:
                    if cancel_event and cancel_event.is_set():
                        return False, "用户已取消下载"
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    downloaded += len(buffer)
                    out_file.write(buffer)

                    if progress_callback and total_size:
                        pct = 0.05 + 0.75 * (downloaded / total_size)
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        progress_callback(
                            pct, f"正在下载引擎包 ({mb:.1f}/{total_mb:.1f} MB)..."
                        )

            if progress_callback:
                progress_callback(0.85, "下载完成，正在解压与校验...")

            # 2. 解压提取 ffmpeg
            extracted = False
            # 尝试作为 zip 解压
            if zipfile.is_zipfile(temp_archive_path):
                with zipfile.ZipFile(temp_archive_path, "r") as zip_ref:
                    for member in zip_ref.namelist():
                        basename = os.path.basename(member)
                        if basename.lower() in ["ffmpeg.exe", "ffmpeg"]:
                            with (
                                zip_ref.open(member) as source,
                                open(target_path, "wb") as target,
                            ):
                                shutil.copyfileobj(source, target)
                            extracted = True
                            break
            # 尝试作为 tar 解压
            elif tarfile.is_tarfile(temp_archive_path):
                with tarfile.open(temp_archive_path, "r:*") as tar_ref:
                    for member in tar_ref.getmembers():
                        basename = os.path.basename(member.name)
                        if basename.lower() in ["ffmpeg.exe", "ffmpeg"]:
                            f = tar_ref.extractfile(member)
                            if f:
                                with open(target_path, "wb") as target:
                                    shutil.copyfileobj(f, target)
                                extracted = True
                                break
            else:
                # 可能是直接的二进制流文件
                shutil.copy(temp_archive_path, target_path)
                extracted = True

            # 清理临时下载文件
            if os.path.exists(temp_archive_path):
                with contextlib.suppress(Exception):
                    os.remove(temp_archive_path)

            if not extracted or not os.path.exists(target_path):
                return False, "未能从下载归档中提取到 ffmpeg 二进制文件"

            # 3. 赋予可执行权限并进行校验
            if sys.platform != "win32":
                st = os.stat(target_path)
                os.chmod(
                    target_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )

            valid, info = self.verify_executable(target_path)
            if not valid:
                return False, f"安装后的 FFmpeg 校验失败: {info}"

            if progress_callback:
                progress_callback(1.0, "FFmpeg 引擎已成功配置就绪！")

            return True, target_path

        except Exception as e:
            if os.path.exists(temp_archive_path):
                with contextlib.suppress(Exception):
                    os.remove(temp_archive_path)
            return False, f"安装失败: {e}"


# 全局单例
dependency_manager = DependencyManager()
