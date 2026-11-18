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
    核心依赖管理与引导安装弹窗（支持 yt-dlp 与 FFmpeg 双依赖）：
    1. 展示两个核心依赖的系统探测状态、路径与版本
    2. 一键下载官方静态二进制并直接安装到系统默认目录（macOS 优先 /opt/homebrew/bin）
    3. 分别支持手动浏览选择本地可执行文件或恢复自动探测
    4. 提供终端包管理器一键安装命令复制
    """

    TOOL_META = {
        "yt-dlp": {
            "title": "yt-dlp（视频解析与下载核心）",
            "missing_hint": "未检测到系统 yt-dlp。缺失时无法解析和下载视频。",
        },
        "ffmpeg": {
            "title": "FFmpeg（音视频合并与转码引擎）",
            "missing_hint": "未检测到系统 FFmpeg。缺失时 1080P+ 混流与 MP3 转码会受限。",
        },
    }

    def __init__(
        self,
        parent,
        on_dependency_updated: Callable[[dict[str, dict]], None] | None = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.on_dependency_updated = on_dependency_updated

        self.title("核心依赖配置 (yt-dlp & FFmpeg)")
        self.geometry("620x580")
        self.resizable(False, False)

        self.transient(parent)
        self.grab_set()

        self._download_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._is_installing = False
        self._tool_widgets: dict[str, dict] = {}
        self._current_states: dict[str, dict] = {}

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.create_widgets()
        self.refresh_status()

    def create_widgets(self):
        # 1. 顶部标题与默认安装目录说明
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=20, pady=(15, 8))

        self.title_lbl = ctk.CTkLabel(
            self.header_frame,
            text="⚙️ 核心依赖管理 (yt-dlp & FFmpeg)",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.title_lbl.pack(anchor="w")

        install_dir = dependency_manager.get_system_install_dir()
        plat_note = "（macOS 优先 Homebrew 目录）" if sys.platform == "darwin" else ""
        self.desc_lbl = ctk.CTkLabel(
            self.header_frame,
            text=(
                "优先探测并使用系统环境已有依赖；缺失时将直接安装到系统默认目录：\n"
                f"📂 {install_dir} {plat_note}"
            ),
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=12),
            wraplength=580,
            justify="left",
        )
        self.desc_lbl.pack(anchor="w", pady=(4, 0))

        # 2. 双依赖状态卡片区
        for tool in ("yt-dlp", "ffmpeg"):
            self._create_tool_card(tool)

        # 3. 一键安装与进度区
        self.batch_frame = ctk.CTkFrame(self, corner_radius=8)
        self.batch_frame.pack(fill="x", padx=20, pady=(8, 8))

        self.batch_top = ctk.CTkFrame(self.batch_frame, fg_color="transparent")
        self.batch_top.pack(fill="x", padx=15, pady=(12, 6))

        self.install_all_btn = ctk.CTkButton(
            self.batch_top,
            text="⚡ 一键安装缺失依赖到系统目录",
            width=220,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_install_all_missing,
        )
        self.install_all_btn.pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(self.batch_top, height=10)
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.progress_lbl = ctk.CTkLabel(
            self.batch_frame,
            text="提示：安装完成后将直接作为系统级命令生效，无需额外私有缓存。",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=550,
            justify="left",
        )
        self.progress_lbl.pack(anchor="w", padx=15, pady=(0, 10))

        # 4. 终端包管理器参考命令
        cmd = dependency_manager.get_quick_install_command()
        self.cmd_frame = ctk.CTkFrame(self, corner_radius=8)
        self.cmd_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.cmd_lbl = ctk.CTkLabel(
            self.cmd_frame,
            text=f"终端命令参考: {cmd}",
            font=ctk.CTkFont(size=11, family="Courier"),
            text_color=("gray35", "gray70"),
        )
        self.cmd_lbl.pack(side="left", padx=15, pady=10)

        self.copy_btn = ctk.CTkButton(
            self.cmd_frame,
            text="复制命令",
            width=72,
            height=26,
            font=ctk.CTkFont(size=11),
            command=lambda: self.copy_to_clipboard(cmd),
        )
        self.copy_btn.pack(side="right", padx=15, pady=8)

    def _create_tool_card(self, tool: str):
        meta = self.TOOL_META[tool]
        card = ctk.CTkFrame(self, corner_radius=8)
        card.pack(fill="x", padx=20, pady=5)
        card.grid_columnconfigure(0, weight=1)

        info_box = ctk.CTkFrame(card, fg_color="transparent")
        info_box.grid(row=0, column=0, sticky="ew", padx=(15, 8), pady=(10, 4))

        status_title = ctk.CTkLabel(
            info_box,
            text=f"{meta['title']} - 检测中...",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        status_title.pack(anchor="w")

        status_detail = ctk.CTkLabel(
            info_box,
            text="正在探测系统路径...",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=550,
            justify="left",
            anchor="w",
        )
        status_detail.pack(anchor="w", pady=(2, 0))

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.grid(row=1, column=0, sticky="ew", padx=15, pady=(2, 10))

        install_btn = ctk.CTkButton(
            btn_box,
            text="⚡ 自动安装到系统",
            width=130,
            height=28,
            font=ctk.CTkFont(size=12),
            command=lambda t=tool: self.on_install_single(t),
        )
        install_btn.pack(side="left")

        browse_btn = ctk.CTkButton(
            btn_box,
            text="📁 手动选择...",
            width=105,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=("gray82", "gray28"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
            command=lambda t=tool: self.on_browse_file(t),
        )
        browse_btn.pack(side="left", padx=8)

        reset_btn = ctk.CTkButton(
            btn_box,
            text="🔄 恢复默认探测",
            width=110,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray85"),
            command=lambda t=tool: self.on_reset_custom(t),
        )
        reset_btn.pack(side="left")

        self._tool_widgets[tool] = {
            "status_title": status_title,
            "status_detail": status_detail,
            "install_btn": install_btn,
            "browse_btn": browse_btn,
            "reset_btn": reset_btn,
        }

    def copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.progress_lbl.configure(
            text="✅ 已复制终端安装命令到剪贴板！", text_color=("#155724", "#4CAF50")
        )

    def _notify_parent(self):
        if self.on_dependency_updated:
            self.on_dependency_updated(self._current_states)

    def refresh_status(self):
        """探测并刷新 yt-dlp 与 FFmpeg 当前状态"""
        self._current_states = dependency_manager.detect_all()
        missing_tools: list[str] = []

        for tool in ("yt-dlp", "ffmpeg"):
            info = self._current_states.get(tool, {})
            widgets = self._tool_widgets[tool]
            meta = self.TOOL_META[tool]

            status = info.get("status")
            source = info.get("source") or "未检测到"
            path = info.get("path")
            detail = info.get("info") or ""

            if status == "ok" and path:
                widgets["status_title"].configure(
                    text=f"✅ {meta['title']}  [{source}]",
                    text_color=("#155724", "#4CAF50"),
                )
                widgets["status_detail"].configure(
                    text=f"路径: {path}\n版本: {detail}",
                    text_color=("#155724", "#A5D6A7"),
                )
                widgets["install_btn"].configure(text="⚡ 重新安装/更新")
            else:
                missing_tools.append(tool)
                widgets["status_title"].configure(
                    text=f"⚠️ {meta['title']}  [未检测到]",
                    text_color=("#721C24", "#EF5350"),
                )
                widgets["status_detail"].configure(
                    text=meta["missing_hint"],
                    text_color=("#721C24", "#FFCDD2"),
                )
                widgets["install_btn"].configure(text="⚡ 自动安装到系统")

        if not self._is_installing:
            if missing_tools:
                missing_str = " & ".join(missing_tools)
                self.install_all_btn.configure(
                    state="normal",
                    text=f"⚡ 一键安装缺失项 ({missing_str})",
                )
            else:
                self.install_all_btn.configure(
                    state="disabled",
                    text="✅ 全部核心依赖已就绪",
                )

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for tool in ("yt-dlp", "ffmpeg"):
            w = self._tool_widgets[tool]
            w["install_btn"].configure(state=state)
            w["browse_btn"].configure(state=state)
            w["reset_btn"].configure(state=state)
        if not enabled:
            self.install_all_btn.configure(state="disabled")

    def on_browse_file(self, tool: str):
        """手动选取本地可执行文件"""
        if self._is_installing:
            return
        file_types = (
            [(f"{tool} Executable", "*.exe"), ("All Files", "*.*")]
            if sys.platform == "win32"
            else [("All Files", "*")]
        )
        selected = tkinter.filedialog.askopenfilename(
            title=f"选择 {tool} 可执行文件",
            filetypes=file_types,
            parent=self,
        )
        if not selected:
            return

        valid, msg = dependency_manager.verify_executable(selected, tool)
        if not valid:
            tkinter.messagebox.showerror(
                f"无效的 {tool} 文件",
                f"所选文件无法执行或非有效 {tool} 二进制:\n{msg}",
                parent=self,
            )
            return

        dependency_manager.save_custom_path(tool, selected)
        self.refresh_status()
        self._notify_parent()
        tkinter.messagebox.showinfo(
            "配置成功", f"已关联 {tool} 路径:\n{selected}", parent=self
        )

    def on_reset_custom(self, tool: str):
        """清除指定工具的自定义路径并恢复系统探测"""
        if self._is_installing:
            return
        dependency_manager.save_custom_path(tool, None)
        self.refresh_status()
        self._notify_parent()
        self.progress_lbl.configure(
            text=f"🔄 已恢复 {tool} 默认系统探测顺序。",
            text_color="gray",
        )

    def on_install_single(self, tool: str):
        """安装或更新单个依赖到系统默认目录"""
        self._start_install([tool])

    def on_install_all_missing(self):
        """一键安装全部缺失依赖到系统默认目录"""
        self.refresh_status()
        missing = [
            t
            for t in ("yt-dlp", "ffmpeg")
            if self._current_states.get(t, {}).get("status") != "ok"
        ]
        if not missing:
            tkinter.messagebox.showinfo(
                "依赖已就绪", "yt-dlp 与 FFmpeg 均已在系统中就绪。", parent=self
            )
            return
        self._start_install(missing)

    def _start_install(self, tools: list[str]):
        if self._is_installing or not tools:
            return

        self._is_installing = True
        self._cancel_event.clear()
        self._set_controls_enabled(False)
        self.progress_bar.set(0.03)
        self.progress_lbl.configure(
            text=f"准备安装 {', '.join(tools)} 到系统目录...", text_color="gray"
        )

        total_count = len(tools)

        def _post_progress(pct: float, text: str):
            if self.winfo_exists():
                self.after(0, lambda p=pct, msg=text: self._apply_progress(p, msg))

        def _task():
            installed_paths: list[tuple[str, str]] = []
            for idx, tool in enumerate(tools):
                if self._cancel_event.is_set():
                    if self.winfo_exists():
                        self.after(
                            0,
                            lambda: self._on_install_finished(
                                False, "用户已取消安装", installed_paths
                            ),
                        )
                    return

                def _sub_progress(sub_pct: float, sub_msg: str, i=idx, t=tool):
                    overall = (i + sub_pct) / total_count
                    prefix = f"[{i + 1}/{total_count} {t}] " if total_count > 1 else ""
                    _post_progress(overall, f"{prefix}{sub_msg}")

                ok, result = dependency_manager.download_and_install(
                    tool,
                    progress_callback=_sub_progress,
                    cancel_event=self._cancel_event,
                )
                if not ok:
                    if self.winfo_exists():
                        self.after(
                            0,
                            lambda err=result, t=tool: self._on_install_finished(
                                False, f"{t} 安装失败: {err}", installed_paths
                            ),
                        )
                    return
                installed_paths.append((tool, result))

            if self.winfo_exists():
                self.after(
                    0,
                    lambda: self._on_install_finished(True, "", installed_paths),
                )

        self._download_thread = threading.Thread(target=_task, daemon=True)
        self._download_thread.start()

    def _apply_progress(self, pct: float, text: str):
        if not self.winfo_exists():
            return
        self.progress_bar.set(pct)
        self.progress_lbl.configure(text=text, text_color="gray")

    def _on_install_finished(
        self,
        ok: bool,
        error_message: str,
        installed_paths: list[tuple[str, str]],
    ):
        if not self.winfo_exists():
            return

        self._is_installing = False
        self._set_controls_enabled(True)
        self.refresh_status()
        self._notify_parent()

        if ok:
            self.progress_bar.set(1.0)
            self.progress_lbl.configure(
                text="✅ 已成功部署到系统目录并完成校验！",
                text_color=("#155724", "#4CAF50"),
            )
            details = "\n".join(f"• {t}: {p}" for t, p in installed_paths)
            tkinter.messagebox.showinfo(
                "安装成功",
                f"核心依赖已成功安装到系统默认目录：\n\n{details}",
                parent=self,
            )
        else:
            self.progress_lbl.configure(
                text=f"❌ {error_message}",
                text_color=("#721C24", "#EF5350"),
            )
            tkinter.messagebox.showerror(
                "安装失败",
                f"自动安装未能完成：\n{error_message}",
                parent=self,
            )

    def on_close(self):
        if self._is_installing:
            self._cancel_event.set()
        self.grab_release()
        self.destroy()
