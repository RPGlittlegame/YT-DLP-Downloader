from __future__ import annotations

import sys
import threading
import tkinter.filedialog
import tkinter.messagebox
from collections.abc import Callable

import customtkinter as ctk

from core.dependency_manager import dependency_manager


class DependencyDialog(ctk.CTkToplevel):
    """
    依赖管理与引导安装弹窗：
    当系统未检测到 FFmpeg 依赖或用户点击设置时弹出，提供：
    1. 当前依赖检测状态展示与说明
    2. 一键从官方源极速下载并自动解压配置（异步进度条）
    3. 手动选择已有本地 FFmpeg 二进制路径
    4. 复制系统包管理器一键安装命令 (brew / winget / apt)
    """

    def __init__(
        self,
        parent,
        on_dependency_updated: Callable[[str | None, str], None] | None = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.on_dependency_updated = on_dependency_updated

        self.title("FFmpeg 媒体引擎配置")
        self.geometry("560x440")
        self.resizable(False, False)

        # 模态与置顶
        self.transient(parent)
        self.grab_set()

        self._download_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._is_installing = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.create_widgets()
        self.refresh_status()

    def create_widgets(self):
        # 1. 顶部标题与说明
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=20, pady=(15, 10))

        self.title_lbl = ctk.CTkLabel(
            self.header_frame,
            text="⚙️ FFmpeg 媒体引擎管理",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.title_lbl.pack(anchor="w")

        self.desc_lbl = ctk.CTkLabel(
            self.header_frame,
            text="音视频高画质混流、1080P/4K/8K 封装与格式转换均需要 FFmpeg 引擎支持。",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            wraplength=520,
            justify="left",
        )
        self.desc_lbl.pack(anchor="w", pady=(4, 0))

        # 2. 当前状态卡片
        self.status_card = ctk.CTkFrame(self, corner_radius=8)
        self.status_card.pack(fill="x", padx=20, pady=5)

        self.status_title = ctk.CTkLabel(
            self.status_card,
            text="当前引擎状态:",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_title.pack(anchor="w", padx=15, pady=(10, 2))

        self.status_detail = ctk.CTkLabel(
            self.status_card,
            text="正在检测中...",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            wraplength=490,
            justify="left",
        )
        self.status_detail.pack(anchor="w", padx=15, pady=(0, 10))

        # 3. 安装/引导方式选项卡/分组
        self.action_frame = ctk.CTkFrame(self, corner_radius=8)
        self.action_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 方案 A: 一键在线安装
        self.opt_a_lbl = ctk.CTkLabel(
            self.action_frame,
            text="选项 1：一键自动配置 (推荐)",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.opt_a_lbl.pack(anchor="w", padx=15, pady=(12, 2))

        self.opt_a_desc = ctk.CTkLabel(
            self.action_frame,
            text="从官方静态镜像自动下载适合当前系统的免安装引擎并部署到本地 (~/.ydd/bin/)。",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        self.opt_a_desc.pack(anchor="w", padx=15, pady=(0, 6))

        self.download_box = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.download_box.pack(fill="x", padx=15, pady=(0, 10))

        self.install_btn = ctk.CTkButton(
            self.download_box,
            text="⚡ 一键自动安装",
            width=140,
            height=32,
            command=self.on_start_auto_install,
        )
        self.install_btn.pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(self.download_box, height=10)
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10)

        self.progress_lbl = ctk.CTkLabel(
            self.action_frame,
            text="",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        )
        self.progress_lbl.pack(anchor="w", padx=15, pady=(0, 8))

        # 分割线
        self.sep = ctk.CTkFrame(
            self.action_frame, height=1, fg_color=("gray80", "gray30")
        )
        self.sep.pack(fill="x", padx=15, pady=4)

        # 方案 B: 手动选取已有路径
        self.opt_b_lbl = ctk.CTkLabel(
            self.action_frame,
            text="选项 2：手动选择本地已有可执行文件",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.opt_b_lbl.pack(anchor="w", padx=15, pady=(6, 2))

        self.browse_box = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.browse_box.pack(fill="x", padx=15, pady=(0, 8))

        self.browse_btn = ctk.CTkButton(
            self.browse_box,
            text="📁 浏览文件...",
            width=110,
            height=28,
            command=self.on_browse_file,
        )
        self.browse_btn.pack(side="left")

        self.reset_btn = ctk.CTkButton(
            self.browse_box,
            text="🔄 恢复默认探测",
            width=110,
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self.on_reset_custom,
        )
        self.reset_btn.pack(side="left", padx=10)

        # 方案 C: 系统命令快速复制
        cmd = dependency_manager.get_quick_install_command()
        self.opt_c_box = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.opt_c_box.pack(fill="x", padx=15, pady=(4, 10))

        self.cmd_lbl = ctk.CTkLabel(
            self.opt_c_box,
            text=f"终端命令: {cmd}",
            font=ctk.CTkFont(size=11, family="Courier"),
            text_color=("gray40", "gray60"),
        )
        self.cmd_lbl.pack(side="left")

        self.copy_btn = ctk.CTkButton(
            self.opt_c_box,
            text="复制",
            width=50,
            height=24,
            font=ctk.CTkFont(size=11),
            command=lambda: self.copy_to_clipboard(cmd),
        )
        self.copy_btn.pack(side="right")

    def copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.progress_lbl.configure(
            text="已复制安装命令到剪贴板！", text_color="#4CAF50"
        )

    def refresh_status(self):
        """探测并刷新当前状态卡片"""
        info = dependency_manager.detect_ffmpeg()
        status = info.get("status")
        source = info.get("source")
        path = info.get("path")
        detail = info.get("info")

        if status == "ok" and path:
            self.status_title.configure(
                text=f"✅ 当前引擎就绪 ({source})", text_color=("#155724", "#4CAF50")
            )
            self.status_detail.configure(
                text=f"路径: {path}\n版本: {detail}",
                text_color=("#155724", "#A5D6A7"),
            )
            self.install_btn.configure(text="⚡ 重新下载安装")
        else:
            self.status_title.configure(
                text="⚠️ 未检测到可用的 FFmpeg", text_color=("#721C24", "#EF5350")
            )
            self.status_detail.configure(
                text="当前系统缺少 FFmpeg 依赖。请从下方选择一键自动安装或手动指定。",
                text_color=("#721C24", "#FFCDD2"),
            )
            self.install_btn.configure(text="⚡ 一键自动安装")

    def on_browse_file(self):
        """手动选取本地 FFmpeg 可执行文件"""
        file_types = (
            [("FFmpeg Executable", "*.exe")]
            if sys.platform == "win32"
            else [("All Files", "*")]
        )
        selected = tkinter.filedialog.askopenfilename(
            title="选择 FFmpeg 可执行文件",
            filetypes=file_types,
            parent=self,
        )
        if not selected:
            return

        valid, msg = dependency_manager.verify_executable(selected)
        if not valid:
            tkinter.messagebox.showerror(
                "无效的 FFmpeg 文件",
                f"所选文件无法执行或非有效 FFmpeg 二进制:\n{msg}",
                parent=self,
            )
            return

        dependency_manager.save_custom_path(selected)
        self.refresh_status()
        if self.on_dependency_updated:
            det = dependency_manager.detect_ffmpeg()
            self.on_dependency_updated(
                det.get("path"), str(det.get("source") or "自定义")
            )
        tkinter.messagebox.showinfo(
            "配置成功", f"已成功关联 FFmpeg 引擎:\n{selected}", parent=self
        )

    def on_reset_custom(self):
        """清除自定义路径设置"""
        dependency_manager.save_custom_path(None)
        self.refresh_status()
        if self.on_dependency_updated:
            det = dependency_manager.detect_ffmpeg()
            self.on_dependency_updated(
                det.get("path"), str(det.get("source") or "未检测到")
            )

    def on_start_auto_install(self):
        """触发一键后台下载安装"""
        if self._is_installing:
            return

        self._is_installing = True
        self._cancel_event.clear()
        self.install_btn.configure(state="disabled", text="正在安装...")
        self.browse_btn.configure(state="disabled")
        self.progress_bar.set(0.05)
        self.progress_lbl.configure(text="正在准备安装环境...", text_color="gray")

        def _update_ui(pct: float, text: str):
            self.after(0, lambda: self._apply_progress(pct, text))

        def _task():
            ok, result_msg = dependency_manager.download_and_install_ffmpeg(
                progress_callback=_update_ui,
                cancel_event=self._cancel_event,
            )
            self.after(0, lambda: self._on_install_finished(ok, result_msg))

        self._download_thread = threading.Thread(target=_task, daemon=True)
        self._download_thread.start()

    def _apply_progress(self, pct: float, text: str):
        self.progress_bar.set(pct)
        self.progress_lbl.configure(text=text, text_color="gray")

    def _on_install_finished(self, ok: bool, message: str):
        self._is_installing = False
        self.install_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")

        if ok:
            self.progress_bar.set(1.0)
            self.progress_lbl.configure(
                text="✅ 安装并校验成功！", text_color="#4CAF50"
            )
            self.refresh_status()
            if self.on_dependency_updated:
                det = dependency_manager.detect_ffmpeg()
                self.on_dependency_updated(
                    det.get("path"), str(det.get("source") or "本地缓存")
                )
            tkinter.messagebox.showinfo(
                "安装成功", "FFmpeg 引擎已成功下载并配置就绪！", parent=self
            )
        else:
            self.progress_lbl.configure(text=f"❌ {message}", text_color="#EF5350")
            self.refresh_status()
            tkinter.messagebox.showerror(
                "安装失败", f"自动下载安装未能完成:\n{message}", parent=self
            )

    def on_close(self):
        if self._is_installing:
            self._cancel_event.set()
        self.grab_release()
        self.destroy()
