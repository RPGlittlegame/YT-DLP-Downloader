from __future__ import annotations

import contextlib
import glob
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable


class DependencyManager:
    """
    核心依赖管理器（单例模式）：
    统一管理 yt-dlp 与 FFmpeg 两个外部系统级可执行文件：
    1. 探测优先级：用户自定义路径 -> 系统环境（macOS 优先 Homebrew /opt/homebrew/bin）-> Full 版内置目录 (bin/)
    2. 不使用 ~/.ydd/bin 私有缓存，一键安装直接部署到系统默认目录
    3. ~/.ydd/config.json 仅保存用户手动指定的自定义路径
    """

    SUPPORTED_TOOLS = ("yt-dlp", "ffmpeg")

    # 官方静态二进制下载地址
    DOWNLOAD_URLS: dict[str, dict[str, str]] = {
        "ffmpeg": {
            "windows_x64": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
            "macos_arm64": "https://evermeet.cx/ffmpeg/getrelease/zip",
            "macos_x86_64": "https://evermeet.cx/ffmpeg/getrelease/zip",
            "linux_x64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        },
        "yt-dlp": {
            "windows_x64": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
            "macos_arm64": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
            "macos_x86_64": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos",
            "linux_x64": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux",
        },
    }

    # 主流 Linux 发行版包管理器安装命令 (Debian/Ubuntu, Fedora/RHEL, Arch/Manjaro)
    LINUX_INSTALL_COMMANDS = {
        "apt": "sudo apt update && sudo apt install -y ffmpeg yt-dlp",
        "dnf": "sudo dnf install -y ffmpeg yt-dlp",
        "pacman": "sudo pacman -S --noconfirm ffmpeg yt-dlp",
    }

    # 各系统终端快速安装命令参考
    INSTALL_COMMANDS = {
        "darwin": "brew install yt-dlp ffmpeg",
        "win32": "winget install yt-dlp.yt-dlp Gyan.FFmpeg",
        "linux": LINUX_INSTALL_COMMANDS["apt"],
    }

    def __init__(self):
        self.app_data_dir = self._get_app_data_dir()
        self.config_file = os.path.join(self.app_data_dir, "config.json")
        self._custom_paths: dict[str, str | None] = self._load_custom_paths()

    @staticmethod
    def _get_app_data_dir() -> str:
        """获取应用配置目录 ~/.ydd/（仅用于保存 config.json）"""
        return os.path.join(os.path.expanduser("~"), ".ydd")

    @staticmethod
    def _config_key(tool: str) -> str:
        return "ytdlp_path" if tool == "yt-dlp" else "ffmpeg_path"

    @staticmethod
    def _exe_name(tool: str) -> str:
        return f"{tool}.exe" if sys.platform == "win32" else tool

    def _load_custom_paths(self) -> dict[str, str | None]:
        """从 ~/.ydd/config.json 读取用户自定义的依赖路径"""
        result: dict[str, str | None] = {"yt-dlp": None, "ffmpeg": None}
        if not os.path.exists(self.config_file):
            return result
        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for tool in self.SUPPORTED_TOOLS:
                    val = data.get(self._config_key(tool))
                    result[tool] = str(val) if val else None
        except Exception:
            pass
        return result

    def save_custom_path(
        self, tool_or_path: str | None, path: str | None = None
    ) -> bool:
        """
        持久化保存用户自定义路径。
        支持新接口 save_custom_path("yt-dlp", "/path/to/yt-dlp")
        也兼容旧接口 save_custom_path("/path/to/ffmpeg") / save_custom_path(None)
        """
        if tool_or_path in self.SUPPORTED_TOOLS:
            tool = tool_or_path
            target_path = path
        elif tool_or_path is None:
            tool = "ffmpeg"
            target_path = None
        else:
            tool = "ffmpeg"
            target_path = tool_or_path

        self._custom_paths[tool] = target_path
        try:
            os.makedirs(self.app_data_dir, exist_ok=True)
            data: dict = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            data = loaded
                except Exception:
                    data = {}

            key = self._config_key(tool)
            if target_path:
                data[key] = target_path
            else:
                data.pop(key, None)

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def verify_executable(path: str, tool: str | None = None) -> tuple[bool, str]:
        """
        验证指定路径的 yt-dlp 或 FFmpeg 二进制是否可用，并提取版本简述
        """
        if not path or not os.path.isfile(path):
            return False, "文件不存在"

        if sys.platform != "win32":
            try:
                st = os.stat(path)
                if not bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                    os.chmod(
                        path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    )
            except OSError:
                pass

        is_ytdlp = (
            tool == "yt-dlp"
            if tool is not None
            else "yt-dlp" in os.path.basename(path).lower()
        )
        ver_flag = "--version" if is_ytdlp else "-version"

        try:
            res = subprocess.run(
                [path, ver_flag],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            if res.returncode == 0:
                out_lines = (res.stdout or "").splitlines()
                first_line = out_lines[0].strip() if out_lines else (tool or "ok")
                return True, first_line
            return False, f"返回码异常: {res.returncode}"
        except Exception as e:
            return False, f"执行失败: {e}"

    @staticmethod
    def get_system_install_dir() -> str:
        """
        获取当前操作系统的默认外部命令安装目录：
        - macOS: 默认安装到 Homebrew 目录（Apple Silicon 或存在 /opt/homebrew 为 /opt/homebrew/bin，Intel 回退 /usr/local/bin）
        - Windows: %LOCALAPPDATA%\\Programs\\bin
        - Linux: /usr/local/bin（若可写），否则 ~/.local/bin
        """
        home = os.path.expanduser("~")
        if sys.platform == "darwin":
            arch = platform.machine().lower()
            if (
                "arm" in arch
                or "aarch64" in arch
                or os.path.isdir("/opt/homebrew/bin")
                or os.path.isdir("/opt/homebrew")
            ):
                return "/opt/homebrew/bin"
            return "/usr/local/bin"

        if sys.platform == "win32":
            localappdata = os.environ.get(
                "LOCALAPPDATA", os.path.join(home, "AppData", "Local")
            )
            win_bin = os.path.join(localappdata, "Programs", "bin")
            with contextlib.suppress(OSError):
                os.makedirs(win_bin, exist_ok=True)
            return win_bin

        # Linux
        if os.path.isdir("/usr/local/bin") and os.access("/usr/local/bin", os.W_OK):
            return "/usr/local/bin"
        return os.path.join(home, ".local", "bin")

    @staticmethod
    def _append_dir_candidates(
        candidates: list[tuple[str, str]],
        dirs: list[str],
        exe_name: str,
        label: str,
    ) -> None:
        for d in dirs:
            candidates.append((os.path.join(d, exe_name), label))

    @staticmethod
    def _append_glob_candidates(
        candidates: list[tuple[str, str]],
        patterns: list[str],
        label: str,
    ) -> None:
        for pat in patterns:
            for match in sorted(glob.glob(pat)):
                candidates.append((match, label))

    @staticmethod
    def _find_imageio_ffmpeg_candidates() -> list[tuple[str, str]]:
        """兜底扫描系统/用户 Python 环境中的 imageio_ffmpeg 静态二进制"""
        home = os.path.expanduser("~")
        patterns: list[str] = []
        conda_roots = ("miniconda3", "anaconda3", "miniforge3", "mambaforge")

        if sys.platform == "darwin":
            patterns.extend([
                os.path.join(home, ".local", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"),
                os.path.join(home, "Library", "Python", "*", "lib", "python", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"),
                "/Library/Frameworks/Python.framework/Versions/*/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg*",
                "/opt/homebrew/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg*",
                "/usr/local/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg*",
            ])
            for root in conda_roots:
                patterns.append(os.path.join(home, root, "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"))
                patterns.append(os.path.join(home, root, "envs", "*", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"))
        elif sys.platform == "win32":
            localappdata = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
            appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            patterns.extend([
                os.path.join(localappdata, "Programs", "Python", "Python*", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*.exe"),
                os.path.join(appdata, "Python", "Python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*.exe"),
                r"C:\Python*\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg*.exe",
            ])
            for root in conda_roots:
                patterns.append(os.path.join(home, root, "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*.exe"))
                patterns.append(os.path.join(home, root, "envs", "*", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*.exe"))
        else:
            patterns.extend([
                os.path.join(home, ".local", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"),
                "/usr/local/lib/python*/dist-packages/imageio_ffmpeg/binaries/ffmpeg*",
                "/usr/local/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg*",
                "/usr/lib/python*/dist-packages/imageio_ffmpeg/binaries/ffmpeg*",
                "/usr/lib/python*/site-packages/imageio_ffmpeg/binaries/ffmpeg*",
            ])
            for root in conda_roots:
                patterns.append(os.path.join(home, root, "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"))
                patterns.append(os.path.join(home, root, "envs", "*", "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"))

        results: list[tuple[str, str]] = []
        for pat in patterns:
            for f in sorted(glob.glob(pat)):
                if not f.endswith((".py", ".pyc", ".md")) and os.path.isfile(f):
                    results.append((f, "Python 静态引擎 (imageio_ffmpeg)"))
        return results

    def _find_system_candidates(self, tool: str) -> list[tuple[str, str]]:
        """
        按平台优先级生成全面覆盖的系统探测候选列表: [(路径, 来源标签), ...]
        macOS 优先探测 Homebrew (/opt/homebrew/bin -> /usr/local/bin)，随后覆盖 PATH、MacPorts/Nix、Python/pip/pipx、Conda、应用目录等
        """
        exe_name = self._exe_name(tool)
        home = os.path.expanduser("~")
        candidates: list[tuple[str, str]] = []
        conda_roots = ("miniconda3", "anaconda3", "miniforge3", "mambaforge")

        if sys.platform == "darwin":
            # 1. macOS 优先 Homebrew
            self._append_dir_candidates(candidates, ["/opt/homebrew/bin"], exe_name, "Homebrew (/opt/homebrew/bin)")
            self._append_dir_candidates(candidates, ["/opt/homebrew/sbin"], exe_name, "Homebrew (/opt/homebrew/sbin)")
            self._append_dir_candidates(candidates, ["/usr/local/bin"], exe_name, "Homebrew (/usr/local/bin)")
            self._append_dir_candidates(candidates, ["/usr/local/sbin"], exe_name, "Homebrew (/usr/local/sbin)")
            self._append_dir_candidates(
                candidates,
                [f"/opt/homebrew/opt/{tool}/bin"],
                exe_name,
                "Homebrew (/opt/homebrew/opt)",
            )
            self._append_dir_candidates(
                candidates,
                [f"/usr/local/opt/{tool}/bin"],
                exe_name,
                "Homebrew (/usr/local/opt)",
            )

            # 2. 环境变量 PATH
            which_path = shutil.which(tool) or shutil.which(exe_name)
            if which_path:
                candidates.append((which_path, "系统 PATH"))

            # 3. MacPorts / Nix / Fink
            self._append_dir_candidates(candidates, ["/opt/local/bin", "/opt/local/sbin"], exe_name, "MacPorts")
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".nix-profile", "bin"),
                    "/nix/var/nix/profiles/default/bin",
                    "/run/current-system/sw/bin",
                ],
                exe_name,
                "Nix",
            )
            self._append_dir_candidates(candidates, ["/sw/bin"], exe_name, "Fink")

            # 4. 用户级工具与版本管理器 (pip / pipx / uv / pyenv / asdf / mise / cargo)
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".local", "bin"),
                    os.path.join(home, "bin"),
                    os.path.join(home, ".cargo", "bin"),
                ],
                exe_name,
                "用户目录",
            )
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".pyenv", "shims"),
                    os.path.join(home, ".asdf", "shims"),
                    os.path.join(home, ".local", "share", "mise", "shims"),
                ],
                exe_name,
                "版本管理器",
            )
            self._append_glob_candidates(
                candidates,
                [os.path.join(home, ".pyenv", "versions", "*", "bin", exe_name)],
                "版本管理器 (pyenv)",
            )

            # 5. Python 框架与用户级 Python bin
            self._append_glob_candidates(
                candidates,
                [
                    f"/opt/homebrew/opt/python*/Frameworks/Python.framework/Versions/*/bin/{exe_name}",
                ],
                "Python 环境 (Homebrew)",
            )
            self._append_glob_candidates(
                candidates,
                [
                    f"/Library/Frameworks/Python.framework/Versions/*/bin/{exe_name}",
                    os.path.join(home, "Library", "Python", "*", "bin", exe_name),
                    f"/usr/local/opt/python*/Frameworks/Python.framework/Versions/*/bin/{exe_name}",
                ],
                "Python 环境",
            )

            # 6. Conda / Miniconda / Anaconda / Miniforge / Mambaforge
            conda_dirs = [os.path.join(home, r, "bin") for r in conda_roots] + [
                "/opt/homebrew/Caskroom/miniforge/base/bin",
                "/opt/homebrew/Caskroom/miniconda/base/bin",
            ]
            self._append_dir_candidates(candidates, conda_dirs, exe_name, "Conda 环境")
            self._append_glob_candidates(
                candidates,
                [os.path.join(home, r, "envs", "*", "bin", exe_name) for r in conda_roots],
                "Conda 环境",
            )

            # 7. 应用目录与系统标准目录
            self._append_dir_candidates(
                candidates,
                [
                    "/Applications",
                    "/Applications/FFmpeg",
                    "/Applications/yt-dlp",
                    os.path.join(home, "Applications"),
                    "/usr/bin",
                    "/bin",
                ],
                exe_name,
                "系统目录",
            )

        elif sys.platform == "win32":
            # 1. 系统 PATH
            which_path = shutil.which(tool) or shutil.which(exe_name)
            if which_path:
                candidates.append((which_path, "系统 PATH"))

            localappdata = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
            appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            progdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
            progfiles = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            progfiles86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")

            # 2. WinGet / Scoop / Chocolatey
            self._append_dir_candidates(
                candidates,
                [os.path.join(localappdata, "Microsoft", "WinGet", "Links")],
                exe_name,
                "WinGet",
            )
            self._append_glob_candidates(
                candidates,
                [
                    os.path.join(localappdata, "Microsoft", "WinGet", "Packages", "*", exe_name),
                    os.path.join(localappdata, "Microsoft", "WinGet", "Packages", "*", "*", "bin", exe_name),
                    os.path.join(localappdata, "Microsoft", "WinGet", "Packages", "*", "*", exe_name),
                ],
                "WinGet",
            )
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, "scoop", "shims"),
                    os.path.join(home, "scoop", "apps", tool, "current", "bin"),
                    os.path.join(home, "scoop", "apps", tool, "current"),
                ],
                exe_name,
                "Scoop",
            )
            self._append_dir_candidates(
                candidates,
                [os.path.join(progdata, "chocolatey", "bin")],
                exe_name,
                "Chocolatey",
            )

            # 3. 常见 Windows 安装目录
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(localappdata, "Programs", "bin"),
                    os.path.join(localappdata, "Programs", tool, "bin"),
                    os.path.join(localappdata, "Programs", tool),
                    os.path.join(progfiles, tool, "bin"),
                    os.path.join(progfiles86, tool, "bin"),
                    r"C:\ffmpeg\bin",
                    r"C:\tools\ffmpeg\bin",
                    r"C:\yt-dlp",
                ],
                exe_name,
                "系统目录",
            )

            # 4. Python & Conda 脚本目录
            self._append_dir_candidates(
                candidates, [os.path.join(home, ".local", "bin")], exe_name, "用户目录"
            )
            self._append_glob_candidates(
                candidates,
                [
                    os.path.join(localappdata, "Programs", "Python", "Python*", "Scripts", exe_name),
                    os.path.join(appdata, "Python", "Python*", "Scripts", exe_name),
                    rf"C:\Python*\Scripts\{exe_name}",
                ],
                "Python 环境",
            )
            win_conda_dirs: list[str] = []
            win_conda_globs: list[str] = []
            for r in conda_roots:
                win_conda_dirs.extend([
                    os.path.join(home, r, "Library", "bin"),
                    os.path.join(home, r, "Scripts"),
                ])
                win_conda_globs.extend([
                    os.path.join(home, r, "envs", "*", "Library", "bin", exe_name),
                    os.path.join(home, r, "envs", "*", "Scripts", exe_name),
                ])
            self._append_dir_candidates(candidates, win_conda_dirs, exe_name, "Conda 环境")
            self._append_glob_candidates(candidates, win_conda_globs, "Conda 环境")

        else:
            # Linux (覆盖 apt / dnf / pacman 及主流跨发行版安装位置)
            # 1. 系统 PATH
            which_path = shutil.which(tool) or shutil.which(exe_name)
            if which_path:
                candidates.append((which_path, "系统 PATH"))

            # 2. apt / dnf / pacman 标准系统安装目录
            self._append_dir_candidates(
                candidates,
                [
                    "/usr/bin",
                    "/usr/local/bin",
                    "/usr/local/sbin",
                    "/usr/sbin",
                    "/bin",
                    "/sbin",
                    "/usr/libexec",
                ],
                exe_name,
                "系统目录 (apt/dnf/pacman)",
            )

            # 3. 跨发行版包管理器 (Linuxbrew / Snap / Flatpak / Nix)
            self._append_dir_candidates(
                candidates,
                ["/home/linuxbrew/.linuxbrew/bin", os.path.join(home, ".linuxbrew", "bin")],
                exe_name,
                "Linuxbrew",
            )
            self._append_dir_candidates(
                candidates, ["/snap/bin", "/var/lib/snapd/snap/bin"], exe_name, "Snap"
            )
            self._append_dir_candidates(
                candidates,
                [
                    "/var/lib/flatpak/exports/bin",
                    os.path.join(home, ".local", "share", "flatpak", "exports", "bin"),
                ],
                exe_name,
                "Flatpak",
            )
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".nix-profile", "bin"),
                    "/nix/var/nix/profiles/default/bin",
                    "/run/current-system/sw/bin",
                ],
                exe_name,
                "Nix",
            )

            # 4. 用户级工具、版本管理器与 Conda
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".local", "bin"),
                    os.path.join(home, "bin"),
                    os.path.join(home, ".cargo", "bin"),
                ],
                exe_name,
                "用户目录",
            )
            self._append_dir_candidates(
                candidates,
                [
                    os.path.join(home, ".pyenv", "shims"),
                    os.path.join(home, ".asdf", "shims"),
                    os.path.join(home, ".local", "share", "mise", "shims"),
                ],
                exe_name,
                "版本管理器",
            )
            self._append_glob_candidates(
                candidates,
                [os.path.join(home, ".pyenv", "versions", "*", "bin", exe_name)],
                "版本管理器 (pyenv)",
            )
            self._append_dir_candidates(
                candidates,
                [os.path.join(home, r, "bin") for r in conda_roots],
                exe_name,
                "Conda 环境",
            )
            self._append_glob_candidates(
                candidates,
                [os.path.join(home, r, "envs", "*", "bin", exe_name) for r in conda_roots],
                "Conda 环境",
            )

        # 兜底：若以上路径均未命中且为 ffmpeg，扫描 Python site-packages 中的 imageio_ffmpeg
        if tool == "ffmpeg":
            candidates.extend(self._find_imageio_ffmpeg_candidates())

        return candidates

    def detect_tool(self, tool: str) -> dict[str, str | None]:
        """
        三级探测指定依赖 (yt-dlp 或 ffmpeg)：
        1. 用户手动指定路径 (~/.ydd/config.json)
        2. 系统环境探测（macOS 优先 /opt/homebrew/bin，再查 /usr/local/bin、PATH 与常见系统目录）
        3. Full 版打包内置目录 (bin/)
        """
        if tool not in self.SUPPORTED_TOOLS:
            raise ValueError(f"Unsupported tool: {tool}")

        exe_name = self._exe_name(tool)

        # 第 1 级：用户手动自定义路径
        custom_path = self._custom_paths.get(tool)
        if custom_path:
            valid, info = self.verify_executable(custom_path, tool)
            if valid:
                return {
                    "path": custom_path,
                    "source": "自定义路径",
                    "status": "ok",
                    "info": info,
                }

        # 第 2 级：系统环境探测
        seen: set[str] = set()
        for cand_path, source_label in self._find_system_candidates(tool):
            norm_path = os.path.normpath(cand_path)
            if norm_path in seen:
                continue
            seen.add(norm_path)
            if os.path.isfile(norm_path):
                valid, info = self.verify_executable(norm_path, tool)
                if valid:
                    return {
                        "path": norm_path,
                        "source": source_label,
                        "status": "ok",
                        "info": info,
                    }

        # 第 3 级：Full 版打包内置 bin/ 目录
        if getattr(sys, "frozen", False):
            base_dir = getattr(
                sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
            )
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        bundle_bin = os.path.join(base_dir, "bin", exe_name)
        if os.path.isfile(bundle_bin):
            valid, info = self.verify_executable(bundle_bin, tool)
            if valid:
                return {
                    "path": bundle_bin,
                    "source": "内置引擎 (Full)",
                    "status": "ok",
                    "info": info,
                }

        return {
            "path": None,
            "source": "未检测到",
            "status": "missing",
            "info": f"未找到可用的 {tool}",
        }

    def detect_ffmpeg(self) -> dict[str, str | None]:
        """探测系统 FFmpeg 依赖"""
        return self.detect_tool("ffmpeg")

    def detect_ytdlp(self) -> dict[str, str | None]:
        """探测系统 yt-dlp 依赖"""
        return self.detect_tool("yt-dlp")

    def detect_all(self) -> dict[str, dict[str, str | None]]:
        """同时探测 yt-dlp 与 FFmpeg"""
        return {
            "yt-dlp": self.detect_ytdlp(),
            "ffmpeg": self.detect_ffmpeg(),
        }

    @classmethod
    def get_linux_install_commands(cls) -> dict[str, str]:
        """返回主流 Linux 发行版包管理器（apt / dnf / pacman）安装命令"""
        return dict(cls.LINUX_INSTALL_COMMANDS)

    def get_quick_install_command(self) -> str:
        """获取当前系统适用的包管理器安装命令（Linux 自动识别 apt / dnf / pacman）"""
        if sys.platform == "darwin":
            return self.INSTALL_COMMANDS["darwin"]
        if sys.platform == "win32":
            return self.INSTALL_COMMANDS["win32"]
        if shutil.which("apt") or shutil.which("apt-get"):
            return self.LINUX_INSTALL_COMMANDS["apt"]
        if shutil.which("dnf"):
            return self.LINUX_INSTALL_COMMANDS["dnf"]
        if shutil.which("pacman"):
            return self.LINUX_INSTALL_COMMANDS["pacman"]
        return " / ".join(f"{k}: {v}" for k, v in self.LINUX_INSTALL_COMMANDS.items())

    def get_download_url(self, tool: str = "ffmpeg") -> str | None:
        """获取适合当前平台架构的官方静态二进制下载地址"""
        tool_urls = self.DOWNLOAD_URLS.get(tool)
        if not tool_urls:
            return None

        system = sys.platform
        arch = platform.machine().lower()

        if system == "win32":
            return tool_urls["windows_x64"]
        if system == "darwin":
            if "arm" in arch or "aarch64" in arch:
                return tool_urls["macos_arm64"]
            return tool_urls["macos_x86_64"]
        if system.startswith("linux"):
            return tool_urls["linux_x64"]
        return None

    def _install_to_system_dir(
        self, staged_bin_path: str, target_dir: str, target_path: str
    ) -> tuple[bool, str]:
        """
        将临时目录中的可执行文件安装到系统默认目录。
        若目标目录需要管理员权限（如 macOS /usr/local/bin），通过系统授权弹窗提权写入。
        """
        try:
            os.makedirs(target_dir, exist_ok=True)
            if os.path.islink(target_path):
                os.unlink(target_path)
            shutil.copy2(staged_bin_path, target_path)
            if sys.platform != "win32":
                os.chmod(target_path, 0o755)
            return True, target_path
        except PermissionError as err:
            if sys.platform == "darwin":
                shell_cmd = (
                    f"mkdir -p {shlex.quote(target_dir)} && "
                    f"rm -f {shlex.quote(target_path)} && "
                    f"cp -f {shlex.quote(staged_bin_path)} {shlex.quote(target_path)} && "
                    f"chmod 755 {shlex.quote(target_path)}"
                )
                apple_escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
                res = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'do shell script "{apple_escaped}" with administrator privileges',
                    ],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return True, target_path
                err_msg = (res.stderr or "").strip() or str(err)
                return False, f"写入系统目录 {target_dir} 被拒绝或取消授权: {err_msg}"
            return False, f"没有权限写入系统目录 {target_dir}: {err}"
        except Exception as e:
            return False, f"安装到系统目录失败: {e}"

    def download_and_install(
        self,
        tool: str,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_event=None,
    ) -> tuple[bool, str]:
        """
        异步流式下载指定工具官方二进制并部署到系统默认目录（macOS 优先 /opt/homebrew/bin）
        :param tool: "yt-dlp" 或 "ffmpeg"
        :param progress_callback: (0.0~1.0, 状态文本)
        :param cancel_event: 外部 threading.Event 控制取消
        """
        if tool not in self.SUPPORTED_TOOLS:
            return False, f"不支持的工具类型: {tool}"

        url = self.get_download_url(tool)
        if not url:
            return (
                False,
                f"暂不支持当前系统架构 ({sys.platform}-{platform.machine()}) 的自动下载",
            )

        exe_name = self._exe_name(tool)
        target_dir = self.get_system_install_dir()
        target_path = os.path.join(target_dir, exe_name)

        temp_dir = tempfile.mkdtemp(prefix=f"ydd_{tool}_")
        temp_download_path = os.path.join(temp_dir, "download.tmp")
        staged_bin_path = os.path.join(temp_dir, exe_name)

        try:
            if progress_callback:
                progress_callback(0.05, f"正在连接 {tool} 官方下载节点...")

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (YT-DLP-Downloader-Installer)"},
            )
            with (
                urllib.request.urlopen(req, timeout=30) as response,
                open(temp_download_path, "wb") as out_file,
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

                    if progress_callback:
                        mb = downloaded / (1024 * 1024)
                        if total_size:
                            pct = 0.05 + 0.75 * (downloaded / total_size)
                            total_mb = total_size / (1024 * 1024)
                            progress_callback(
                                pct,
                                f"正在下载 {tool} ({mb:.1f}/{total_mb:.1f} MB)...",
                            )
                        else:
                            progress_callback(0.4, f"正在下载 {tool} ({mb:.1f} MB)...")

            if progress_callback:
                progress_callback(0.85, f"下载完成，正在解压并部署到 {target_dir}...")

            extracted = False
            expected_names = {exe_name.lower(), tool.lower()}
            if zipfile.is_zipfile(temp_download_path):
                with zipfile.ZipFile(temp_download_path, "r") as zip_ref:
                    for member in zip_ref.namelist():
                        basename = os.path.basename(member).lower()
                        if basename in expected_names:
                            with (
                                zip_ref.open(member) as source,
                                open(staged_bin_path, "wb") as target,
                            ):
                                shutil.copyfileobj(source, target)
                            extracted = True
                            break
            elif tarfile.is_tarfile(temp_download_path):
                with tarfile.open(temp_download_path, "r:*") as tar_ref:
                    for member in tar_ref.getmembers():
                        basename = os.path.basename(member.name).lower()
                        if basename in expected_names:
                            f = tar_ref.extractfile(member)
                            if f:
                                with open(staged_bin_path, "wb") as target:
                                    shutil.copyfileobj(f, target)
                                extracted = True
                                break
            else:
                shutil.copy2(temp_download_path, staged_bin_path)
                extracted = True

            if not extracted or not os.path.isfile(staged_bin_path):
                return False, f"未能从下载文件中提取到 {exe_name}"

            if sys.platform != "win32":
                os.chmod(staged_bin_path, 0o755)

            installed, install_msg = self._install_to_system_dir(
                staged_bin_path, target_dir, target_path
            )
            if not installed:
                return False, install_msg

            if progress_callback:
                progress_callback(0.95, f"正在校验系统 {tool}...")

            valid, info = self.verify_executable(target_path, tool)
            if not valid:
                return False, f"安装后的 {tool} 校验失败: {info}"

            # 若先前有旧的自定义路径指向别处，则清理它，使系统默认目录优先生效
            if self._custom_paths.get(tool) and self._custom_paths[tool] != target_path:
                self.save_custom_path(tool, None)

            if progress_callback:
                progress_callback(1.0, f"{tool} 已部署到 {target_path}")

            return True, target_path

        except Exception as e:
            return False, f"安装失败: {e}"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def download_and_install_ffmpeg(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_event=None,
    ) -> tuple[bool, str]:
        """兼容旧接口：一键下载并安装 FFmpeg 到系统默认目录"""
        return self.download_and_install(
            "ffmpeg",
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )


# 全局单例
dependency_manager = DependencyManager()
