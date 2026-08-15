from __future__ import annotations

import os
import shutil
import sys
import threading
from tkinter import filedialog
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageTk

from core.downloader import YTDlpDownloader

# 设置主题跟随系统
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self, ffmpeg_location=None, ffmpeg_type="未检测到"):
        super().__init__()

        self.ffmpeg_location = ffmpeg_location
        self.ffmpeg_type = ffmpeg_type
        self.downloader = YTDlpDownloader(
            ffmpeg_location=self.ffmpeg_location,
            log_callback=self.update_log,
            progress_callback=self.update_progress,
            playlist_item_callback=self.update_item_progress,
        )

        # 窗口配置
        self.title("YT-DLP Downloader")
        self.geometry("680x760")
        self.minsize(580, 520)

        # 设置应用图标
        self._set_app_icon()

        # 主网格布局配置：
        # row 0: 顶部输入 (weight=0)
        # row 1: 选项设置 (weight=0)
        # row 2: 播放列表卡片 (weight=0)
        # row 3: 开始下载按钮 (weight=0, 保证绝不被遮挡或压缩)
        # row 4: 进度条与状态 (weight=0, 保证窗口缩小时始终完整可见)
        # row 5: 日志区 (weight=1, 吸收剩余窗口拉伸，极限缩小时可收缩到看不见)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)
        self.grid_rowconfigure(4, weight=0)
        self.grid_rowconfigure(5, weight=1)

        # 默认值及状态变量初始化（必须在 create_widgets 前完成）
        self.output_dir = os.path.expanduser("~/Downloads")
        self.cookie_file = None
        self.cookie_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies"
        )

        # 选项映射表 desc -> {'id': format_id, 'filesize': bytes_or_None}
        self.v_opts_map = {}
        self.a_opts_map = {}
        # 字幕映射表 desc -> lang_code
        self.s_opts_map = {}
        # 播放列表元数据及选择状态
        self.is_playlist = False
        self.playlist_entries = []
        self.playlist_check_vars = []  # 保存每个条目的 BooleanVar
        self.playlist_mode_var = ctk.StringVar(value="全部下载")
        self.playlist_range_var = ctk.StringVar(value="")
        self.resume_download_var = ctk.BooleanVar(value=True)  # 断点续传开关，默认开启

        self.create_widgets()

        self.output_btn.configure(text=f"📁 {self.output_dir}")

        # 绑定选项变化回调，用于动态更新预估大小
        self.v_quality_var.trace_add("write", self.update_size_estimate)
        self.a_quality_var.trace_add("write", self.update_size_estimate)

        # 初始化状态
        self._is_downloading = False
        self._is_fetching = False
        self._download_thread: threading.Thread | None = None
        self._is_closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 初始化 cookie 列表
        self.update_cookie_list()

    # ── 图标设置 ────────────────────────────────────────────────────────────
    def _set_app_icon(self):
        """设置应用图标，优先使用 .ico（Windows），回退到 PNG"""
        if getattr(sys, "frozen", False):
            base_dir = getattr(sys, "_MEIPASS", "")
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        ico_path = os.path.join(base_dir, "YDD.icon", "icon.ico")
        png_path = os.path.join(
            base_dir, "YDD.icon", "Assets", "square.and.arrow.down.fill.png"
        )

        try:
            if os.path.exists(ico_path) and sys.platform == "win32":
                self.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                img = Image.open(png_path)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.iconphoto(True, self._icon_photo)  # type: ignore
        except Exception:
            pass  # 图标设置失败不影响主程序

    # ── 关闭处理 ─────────────────────────────────────────────────────────────
    def on_closing(self):
        """窗口关闭处理：防重复触发，并在有后台任务时优雅等待中止"""
        if self._is_closing:
            return
        self._is_closing = True

        if self._is_downloading:
            self.downloader.cancel_download()
            self.update_log("正在中止后台任务并退出...")
            # 隐藏主窗口避免用户继续点击触发其它操作
            self.withdraw()

            def _wait_and_destroy(retry_count=0):
                # 如果下载线程已安全退出，或者超时（15次 * 100ms = 1.5s），强制销毁退出
                if (
                    self._download_thread is None
                    or not self._download_thread.is_alive()
                    or retry_count >= 15
                ):
                    self.destroy()
                else:
                    self.after(100, lambda: _wait_and_destroy(retry_count + 1))

            self.after(50, _wait_and_destroy)
        else:
            self.destroy()

    # ── 界面构建 ─────────────────────────────────────────────────────────────
    def create_widgets(self):
        # --- 顶部输入区 ---
        self.top_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.url_label = ctk.CTkLabel(
            self.top_frame, text="URL:", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.url_label.grid(row=0, column=0, padx=(0, 5), pady=5)

        self.url_entry = ctk.CTkEntry(
            self.top_frame,
            placeholder_text="在此输入视频链接...",
            height=30,
            corner_radius=6,
        )
        self.url_entry.grid(row=0, column=1, padx=(0, 5), pady=5, sticky="ew")
        self.url_entry.bind("<Return>", lambda event: self.on_fetch())

        self.fetch_btn = ctk.CTkButton(
            self.top_frame,
            text="解析",
            width=60,
            height=30,
            corner_radius=6,
            command=self.on_fetch,
        )
        self.fetch_btn.grid(row=0, column=2, pady=5)

        # 标题与 FFmpeg 状态行
        self.title_row = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self.title_row.grid(row=1, column=0, columnspan=3, pady=(0, 5), sticky="ew")
        self.title_row.grid_columnconfigure(0, weight=1)

        # 解析出的标题显示
        self.title_label = ctk.CTkLabel(
            self.title_row,
            text="等待解析...",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        # FFmpeg 状态徽章
        ffmpeg_is_ok = (
            self.ffmpeg_location is not None and self.ffmpeg_type != "未检测到"
        )
        badge_text = f"⚙️ FFmpeg: {self.ffmpeg_type}"
        badge_fg = ("#D4EDDA", "#1E3A2F") if ffmpeg_is_ok else ("#F8D7DA", "#3E2723")
        badge_text_color = (
            ("#155724", "#4CAF50") if ffmpeg_is_ok else ("#721C24", "#EF5350")
        )

        self.ffmpeg_badge = ctk.CTkButton(
            self.title_row,
            text=badge_text,
            fg_color=badge_fg,
            text_color=badge_text_color,
            hover_color=badge_fg,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            height=24,
            command=self.open_dependency_settings,
        )
        self.ffmpeg_badge.grid(row=0, column=1, sticky="e")

        # --- 选项设置区 ---
        self.options_frame = ctk.CTkFrame(self, corner_radius=10)
        self.options_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.options_frame.grid_columnconfigure(1, weight=1)
        self.options_frame.grid_columnconfigure(3, weight=1)

        # 行 0：视频清晰度 + 音频质量
        self.v_quality_label = ctk.CTkLabel(self.options_frame, text="视频:")
        self.v_quality_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.v_quality_var = ctk.StringVar(value="自动 (Best)")
        self.v_quality_combo = ctk.CTkComboBox(
            self.options_frame,
            variable=self.v_quality_var,
            values=["自动 (Best)"],
            corner_radius=6,
            width=160,
        )
        self.v_quality_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        self.a_quality_label = ctk.CTkLabel(self.options_frame, text="音频:")
        self.a_quality_label.grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.a_quality_var = ctk.StringVar(value="自动 (Best)")
        self.a_quality_combo = ctk.CTkComboBox(
            self.options_frame,
            variable=self.a_quality_var,
            values=["自动 (Best)"],
            corner_radius=6,
            width=160,
        )
        self.a_quality_combo.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        # 行 1：格式 + 保存至
        self.format_label = ctk.CTkLabel(self.options_frame, text="格式:")
        self.format_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.format_var = ctk.StringVar(value="MP4")
        self.format_combo = ctk.CTkComboBox(
            self.options_frame,
            variable=self.format_var,
            values=["MP4", "MKV", "AVI", "WMV", "MOV", "MP3"],
            corner_radius=6,
            width=160,
        )
        self.format_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        self.path_label = ctk.CTkLabel(self.options_frame, text="保存至:")
        self.path_label.grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.output_btn = ctk.CTkButton(
            self.options_frame,
            text="选择目录",
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "#DCE4EE"),
            corner_radius=6,
            command=self.choose_output_dir,
            width=160,
        )
        self.output_btn.grid(row=1, column=3, padx=5, pady=5, sticky="w")

        # 行 2：字幕语言 + 字幕模式
        self.sub_label = ctk.CTkLabel(self.options_frame, text="字幕:")
        self.sub_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")

        self.sub_var = ctk.StringVar(value="无字幕")
        self.sub_combo = ctk.CTkComboBox(
            self.options_frame,
            variable=self.sub_var,
            values=["无字幕"],
            corner_radius=6,
            width=160,
            command=self._on_subtitle_select,
        )
        self.sub_combo.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        self.sub_mode_label = ctk.CTkLabel(self.options_frame, text="字幕模式:")
        self.sub_mode_label.grid(row=2, column=2, padx=10, pady=5, sticky="w")

        self.sub_mode_var = ctk.StringVar(value="嵌入视频")
        self.sub_mode_btn = ctk.CTkSegmentedButton(
            self.options_frame,
            values=["嵌入视频", "单独下载"],
            variable=self.sub_mode_var,
            width=160,
        )
        self.sub_mode_btn.grid(row=2, column=3, padx=5, pady=5, sticky="w")

        # 行 3：Cookie 选择
        self.cookie_label = ctk.CTkLabel(self.options_frame, text="Cookies:")
        self.cookie_label.grid(row=3, column=0, padx=10, pady=5, sticky="w")

        self.cookie_frame = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        self.cookie_frame.grid(
            row=3, column=1, columnspan=3, padx=5, pady=5, sticky="ew"
        )
        self.cookie_frame.grid_columnconfigure(0, weight=1)

        self.cookie_var = ctk.StringVar(value="未选择 (可选)")
        self.cookie_menu = ctk.CTkOptionMenu(
            self.cookie_frame,
            variable=self.cookie_var,
            values=["未选择 (可选)"],
            corner_radius=6,
            command=self.on_cookie_select,
        )
        self.cookie_menu.grid(row=0, column=0, sticky="ew")

        self.cookie_import_btn = ctk.CTkButton(
            self.cookie_frame,
            text="导入 Cookie",
            width=90,
            corner_radius=6,
            command=self.import_cookie_file,
        )
        self.cookie_import_btn.grid(row=0, column=1, padx=(5, 0))

        # 行 4：高级下载选项（断点续传开关）
        self.adv_label = ctk.CTkLabel(self.options_frame, text="高级:")
        self.adv_label.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="w")

        self.adv_frame = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        self.adv_frame.grid(
            row=4, column=1, columnspan=3, padx=5, pady=(0, 10), sticky="ew"
        )

        self.resume_switch = ctk.CTkSwitch(
            self.adv_frame,
            text="启用断点续传（下载中断时保留 .part 临时文件以便续传）",
            variable=self.resume_download_var,
            font=ctk.CTkFont(size=12),
        )
        self.resume_switch.pack(side="left", anchor="w")

        # --- 播放列表选集卡片 (初始隐藏，解析到 Playlist 时展开) ---
        self.playlist_frame = ctk.CTkFrame(self, corner_radius=10)
        self.playlist_frame.grid_columnconfigure(0, weight=1)

        # 播放列表头部控制栏
        self.pl_header = ctk.CTkFrame(self.playlist_frame, fg_color="transparent")
        self.pl_header.pack(fill="x", padx=10, pady=(10, 5))
        self.pl_header.grid_columnconfigure(1, weight=1)

        self.pl_title_label = ctk.CTkLabel(
            self.pl_header,
            text="📑 播放列表选项:",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.pl_title_label.grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.pl_mode_btn = ctk.CTkSegmentedButton(
            self.pl_header,
            values=["全部下载", "范围选取", "勾选单集"],
            variable=self.playlist_mode_var,
            command=self._on_playlist_mode_change,
        )
        self.pl_mode_btn.grid(row=0, column=1, sticky="w")

        # 范围输入容器
        self.pl_range_container = ctk.CTkFrame(
            self.playlist_frame, fg_color="transparent"
        )
        self.pl_range_container.grid_columnconfigure(1, weight=1)

        self.pl_range_label = ctk.CTkLabel(
            self.pl_range_container,
            text="范围 (例如 1-5, 8, 11-13):",
            font=ctk.CTkFont(size=11),
        )
        self.pl_range_label.grid(row=0, column=0, padx=(10, 5), pady=2, sticky="w")

        self.pl_range_entry = ctk.CTkEntry(
            self.pl_range_container,
            textvariable=self.playlist_range_var,
            placeholder_text="1-10 或 1,3,5...",
            height=28,
            corner_radius=6,
        )
        self.pl_range_entry.grid(row=0, column=1, padx=(0, 10), pady=2, sticky="ew")

        # 勾选单集工具栏（全选 / 反选 / 状态统计）
        self.pl_check_toolbar = ctk.CTkFrame(
            self.playlist_frame, fg_color="transparent"
        )
        self.pl_check_toolbar.grid_columnconfigure(2, weight=1)

        self.pl_select_all_btn = ctk.CTkButton(
            self.pl_check_toolbar,
            text="全选",
            width=50,
            height=24,
            font=ctk.CTkFont(size=11),
            corner_radius=4,
            command=self._select_all_playlist_items,
        )
        self.pl_select_all_btn.grid(row=0, column=0, padx=(10, 5), pady=2)

        self.pl_deselect_all_btn = ctk.CTkButton(
            self.pl_check_toolbar,
            text="全不选",
            width=50,
            height=24,
            font=ctk.CTkFont(size=11),
            corner_radius=4,
            command=self._deselect_all_playlist_items,
        )
        self.pl_deselect_all_btn.grid(row=0, column=1, padx=5, pady=2)

        self.pl_count_label = ctk.CTkLabel(
            self.pl_check_toolbar,
            text="已选择: 0 / 0",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.pl_count_label.grid(row=0, column=2, padx=(5, 10), sticky="e")

        # 勾选单集滚动列表 (限制高度为 85px，避免条目填满时挤占底部操作栏与进度条)
        self.pl_scroll_frame = ctk.CTkScrollableFrame(
            self.playlist_frame, height=85, corner_radius=6
        )
        self.pl_scroll_frame.grid_columnconfigure(1, weight=1)

        # --- 下载按钮区（含预估大小标签，固定在 row 3，永不被挤压）---
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.action_frame.grid_columnconfigure(1, weight=0)

        # 预估大小标签（横跨两列）
        self.size_label = ctk.CTkLabel(
            self.action_frame,
            text="预估大小: 解析后显示",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.size_label.grid(
            row=0, column=0, columnspan=2, sticky="w", padx=2, pady=(0, 4)
        )

        self.download_btn = ctk.CTkButton(
            self.action_frame,
            text="开 始 下 载",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=35,
            corner_radius=6,
            command=self.on_download,
        )
        self.download_btn.grid(row=1, column=0, sticky="ew", padx=(0, 5))

        self.cancel_btn = ctk.CTkButton(
            self.action_frame,
            text="取消",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=80,
            height=35,
            corner_radius=6,
            fg_color="#E74C3C",
            hover_color="#C0392B",
            state="disabled",
            command=self.on_cancel,
        )
        self.cancel_btn.grid(row=1, column=1, sticky="e")

        # --- 进度条与状态区 (位于 row 4，weight=0 保证窗口高度最小时始终包含) ---
        self.progress_frame = ctk.CTkFrame(self, corner_radius=10)
        self.progress_frame.grid(row=4, column=0, padx=10, pady=(5, 5), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, corner_radius=6)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(
            self.progress_frame, text="准备就绪", font=ctk.CTkFont(size=11)
        )
        self.status_label.grid(row=1, column=0, pady=(0, 8))

        # --- 日志区 (位于 row 5，weight=1 吸收剩余高度，窗口高度最小时可收缩至隐藏) ---
        self.log_box = ctk.CTkTextbox(
            self,
            corner_radius=10,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_box.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.log_box.configure(state="disabled")

    # ── 播放列表控制逻辑 ─────────────────────────────────────────────────────
    def _on_playlist_mode_change(self, mode):
        """播放列表模式切换：全部下载 / 范围选取 / 勾选单集"""
        if mode == "全部下载":
            self.pl_range_container.pack_forget()
            self.pl_check_toolbar.pack_forget()
            self.pl_scroll_frame.pack_forget()
        elif mode == "范围选取":
            self.pl_check_toolbar.pack_forget()
            self.pl_scroll_frame.pack_forget()
            self.pl_range_container.pack(fill="x", padx=10, pady=(0, 5))
        elif mode == "勾选单集":
            self.pl_range_container.pack_forget()
            self.pl_check_toolbar.pack(fill="x", padx=10, pady=(0, 2))
            self.pl_scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 5))

    def _select_all_playlist_items(self):
        """全选播放列表中的条目"""
        for var in self.playlist_check_vars:
            var.set(True)
        self._update_playlist_count_label()

    def _deselect_all_playlist_items(self):
        """全不选播放列表中的条目"""
        for var in self.playlist_check_vars:
            var.set(False)
        self._update_playlist_count_label()

    def _update_playlist_count_label(self):
        """更新勾选计数显示"""
        selected_count = sum(1 for var in self.playlist_check_vars if var.get())
        total_count = len(self.playlist_check_vars)
        self.pl_count_label.configure(
            text=f"已选择: {selected_count} / {total_count}",
            text_color="#3498DB" if selected_count > 0 else "gray",
        )

    def _render_playlist_entries(self):
        """渲染播放列表条目到可滚动列表区域"""
        # 清除旧控件
        for widget in self.pl_scroll_frame.winfo_children():
            widget.destroy()

        self.playlist_check_vars.clear()

        for entry in self.playlist_entries:
            idx = entry.get("index", 1)
            title = entry.get("title", f"视频 {idx}")
            duration = entry.get("duration_str", "")

            # 条目行容器
            row_frame = ctk.CTkFrame(self.pl_scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            row_frame.grid_columnconfigure(1, weight=1)

            # 复选框
            chk_var = ctk.BooleanVar(value=True)
            self.playlist_check_vars.append(chk_var)

            chk = ctk.CTkCheckBox(
                row_frame,
                text=f"{idx:02d}. {title}",
                variable=chk_var,
                font=ctk.CTkFont(size=11),
                command=self._update_playlist_count_label,
            )
            chk.grid(row=0, column=0, columnspan=2, sticky="w", padx=2)

            if duration:
                dur_lbl = ctk.CTkLabel(
                    row_frame,
                    text=duration,
                    font=ctk.CTkFont(size=10),
                    text_color="gray",
                    fg_color=("gray85", "gray25"),
                    corner_radius=4,
                    padx=4,
                    pady=1,
                )
                dur_lbl.grid(row=0, column=2, sticky="e", padx=(5, 2))

        self._update_playlist_count_label()

    def _get_selected_playlist_items_param(self):
        """根据当前播放列表选择模式组装 yt-dlp 的 playlist_items 参数"""
        if not self.is_playlist:
            return None

        mode = self.playlist_mode_var.get()
        if mode == "全部下载":
            return None
        elif mode == "范围选取":
            val = self.playlist_range_var.get().strip()
            return val if val else None
        elif mode == "勾选单集":
            selected_indices = [
                str(entry.get("index", i + 1))
                for i, (entry, var) in enumerate(
                    zip(self.playlist_entries, self.playlist_check_vars, strict=False)
                )
                if var.get()
            ]
            if not selected_indices:
                return "0"  # 未勾选任何条目
            return ",".join(selected_indices)

        return None

    # ── 目录选择 ─────────────────────────────────────────────────────────────
    def choose_output_dir(self):
        dir_path = filedialog.askdirectory(initialdir=self.output_dir)
        if dir_path:
            self.output_dir = dir_path
            self.output_btn.configure(text=f"📁 {self.output_dir}")

    # ── Cookie 管理 ──────────────────────────────────────────────────────────
    def update_cookie_list(self):
        try:
            if not os.path.exists(self.cookie_dir):
                os.makedirs(self.cookie_dir, exist_ok=True)
            files = os.listdir(self.cookie_dir)
        except OSError as e:
            self.update_log(f"⚠️ 无法访问 Cookie 目录: {e}")
            files = []

        cookies = ["未选择 (可选)"]
        for f in files:
            if f.endswith(".txt"):
                cookies.append(f)

        self.cookie_menu.configure(values=cookies)

        # 如果当前选中的不再列表中，重置为未选择
        if self.cookie_var.get() not in cookies:
            self.cookie_var.set("未选择 (可选)")
            self.cookie_file = None

    def on_cookie_select(self, choice):
        if choice == "未选择 (可选)":
            self.cookie_file = None
            return

        path = os.path.join(self.cookie_dir, choice)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
            if "Netscape" not in first_line and not first_line.startswith("#"):
                self.update_log(
                    f"⚠️ 警告: {choice} 可能不是有效的 Netscape Cookie 格式文件。"
                )
        except OSError:
            self.update_log(f"⚠️ 警告: 无法读取 Cookie 文件 {choice}。")

        self.cookie_file = path

    def import_cookie_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                if not os.path.exists(self.cookie_dir):
                    os.makedirs(self.cookie_dir, exist_ok=True)
            except OSError as e:
                self.update_log(f"❌ 创建 Cookie 目录失败: {e}")
                return

            filename = os.path.basename(file_path)
            dest_path = os.path.join(self.cookie_dir, filename)

            if not os.path.abspath(dest_path).startswith(
                os.path.abspath(self.cookie_dir)
            ):
                self.update_log("错误: 非法的 Cookie 文件名。")
                return

            try:
                if os.path.abspath(file_path) != os.path.abspath(dest_path):
                    shutil.copy2(file_path, dest_path)

                self.update_cookie_list()
                self.cookie_var.set(filename)
                self.cookie_file = dest_path
                self.update_log(f"成功导入 Cookie: {filename}")
            except Exception as e:
                self.update_log(f"导入 Cookie 失败: {str(e)}")

    # ── 字幕处理 ─────────────────────────────────────────────────────────────
    def _on_subtitle_select(self, choice):
        """字幕选择变化时，更新字幕模式按钮的可用状态"""
        if choice == "无字幕":
            self.sub_mode_btn.configure(state="disabled")
        else:
            self.sub_mode_btn.configure(state="normal")

    # ── 预估大小 ─────────────────────────────────────────────────────────────
    def update_size_estimate(self, *_):
        """根据当前选中的视频/音频格式计算并显示预估文件大小"""
        if not self.v_opts_map and not self.a_opts_map:
            return  # 尚未解析，不更新

        total_bytes = 0
        has_any_size = False

        v_desc = self.v_quality_var.get()
        v_info = self.v_opts_map.get(v_desc, {})
        v_size = v_info.get("filesize") if v_info else None
        if v_size:
            total_bytes += v_size
            has_any_size = True

        a_desc = self.a_quality_var.get()
        a_info = self.a_opts_map.get(a_desc, {})
        a_size = a_info.get("filesize") if a_info else None
        if a_size:
            total_bytes += a_size
            has_any_size = True

        if has_any_size:
            if total_bytes >= 1024**3:
                size_str = f"{total_bytes / 1024**3:.2f} GB"
            elif total_bytes >= 1024**2:
                size_str = f"{total_bytes / 1024**2:.1f} MB"
            elif total_bytes >= 1024:
                size_str = f"{total_bytes / 1024:.1f} KB"
            else:
                size_str = f"{total_bytes} B"
            self.size_label.configure(
                text=f"📦 预估大小: ~{size_str}", text_color=("gray30", "gray70")
            )
        else:
            self.size_label.configure(
                text="📦 预估大小: 未知（平台未提供）", text_color="gray"
            )

    # ── 日志 & 进度 ──────────────────────────────────────────────────────────
    def update_log(self, msg):
        """线程安全的日志更新"""

        def task():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, task)

    def update_progress(self, percent, speed, eta):
        """线程安全的进度条更新"""

        def task():
            self.progress_bar.set(percent)
            if (
                self.is_playlist
                and hasattr(self, "_current_item_info")
                and self._current_item_info
            ):
                idx, total, item_title = self._current_item_info
                self.status_label.configure(
                    text=f"[{idx}/{total}] {percent * 100:.1f}% | 速度: {speed} | 剩余: {eta}"
                )
            else:
                self.status_label.configure(
                    text=f"{percent * 100:.1f}% | 速度: {speed} | 剩余: {eta}"
                )

        self.after(0, task)

    def update_item_progress(self, index, total, title):
        """播放列表下载时多条目切换回调"""
        self._current_item_info = (index, total, title)

        def task():
            self.update_log(f"▶️ 开始处理播放列表条目 [{index}/{total}]: {title}")
            self.status_label.configure(
                text=f"[{index}/{total}] 准备下载: {title[:20]}..."
            )
            self.progress_bar.set(0)

        self.after(0, task)

    # ── 取消下载 ─────────────────────────────────────────────────────────────
    def on_cancel(self):
        self.update_log("正在取消下载，请稍候...")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text="正在中止并清理文件...")
        self.downloader.cancel_download()

    # ── 解析视频 ─────────────────────────────────────────────────────────────
    def on_fetch(self):
        if self._is_fetching or self._is_closing:
            return

        url = self.url_entry.get().strip()
        if not url:
            self.update_log("错误: 请输入有效的 URL。")
            return

        self._is_fetching = True
        self.fetch_btn.configure(state="disabled")
        self.title_label.configure(text="正在解析中，请稍候...", text_color="white")
        self.update_log(f"开始解析: {url}")
        self.size_label.configure(text="📦 预估大小: 解析中...", text_color="gray")

        def fetch_task():
            res: dict[str, Any]
            try:
                res = self.downloader.fetch_info(url, self.cookie_file)
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            def update_ui():
                try:
                    if res.get("status") == "success":
                        self.is_playlist = bool(res.get("is_playlist", False))
                        self.playlist_entries = res.get("items", []) or res.get(
                            "entries", []
                        )
                        self._current_item_info = None

                        if self.is_playlist:
                            entry_count = len(self.playlist_entries)
                            self.title_label.configure(
                                text=f"📑 [播放列表/合集] {res['title']} (共 {entry_count} 个视频)",
                                text_color="#3498DB",
                            )
                            self.update_log(
                                f"解析到播放列表/合集: {res['title']} (共 {entry_count} 个视频)"
                            )
                            # 渲染并展开播放列表交互卡片
                            self._render_playlist_entries()
                            self.playlist_mode_var.set("全部下载")
                            self._on_playlist_mode_change("全部下载")
                            self.playlist_frame.grid(
                                row=2, column=0, padx=10, pady=(0, 5), sticky="ew"
                            )
                        else:
                            # 隐藏播放列表卡片
                            self.playlist_frame.grid_forget()
                            self.title_label.configure(
                                text=f"📌 {res['title']}", text_color="#2CC985"
                            )
                            self.update_log(f"解析成功: {res['title']}")

                        # 重置映射表
                        self.v_opts_map = {
                            "自动 (Best)": {"id": "best", "filesize": None},
                            "无 (仅音频)": {"id": "none", "filesize": None},
                        }
                        self.a_opts_map = {
                            "自动 (Best)": {"id": "best", "filesize": None},
                            "无 (仅视频)": {"id": "none", "filesize": None},
                        }
                        self.s_opts_map = {"无字幕": None}

                        v_vals = ["自动 (Best)", "无 (仅音频)"]
                        for vo in res.get("video_opts", []):
                            if isinstance(vo, dict):
                                v_vals.append(str(vo.get("desc", "")))
                                self.v_opts_map[str(vo.get("desc", ""))] = {
                                    "id": str(vo.get("id", "")),
                                    "filesize": vo.get("filesize"),
                                }

                        a_vals = ["自动 (Best)", "无 (仅视频)"]
                        for ao in res.get("audio_opts", []):
                            if isinstance(ao, dict):
                                a_vals.append(str(ao.get("desc", "")))
                                self.a_opts_map[str(ao.get("desc", ""))] = {
                                    "id": str(ao.get("id", "")),
                                    "filesize": ao.get("filesize"),
                                }

                        # 填充字幕下拉框
                        s_vals = ["无字幕"]
                        for so in res.get("subtitle_opts", []):
                            if isinstance(so, dict):
                                s_vals.append(str(so.get("desc", "")))
                                self.s_opts_map[str(so.get("desc", ""))] = so.get(
                                    "lang"
                                )

                        self.v_quality_combo.configure(values=v_vals)
                        self.a_quality_combo.configure(values=a_vals)
                        self.sub_combo.configure(values=s_vals)

                        self.v_quality_var.set("自动 (Best)")
                        self.a_quality_var.set("自动 (Best)")
                        self.sub_var.set("无字幕")
                        self.sub_mode_btn.configure(state="disabled")

                        # 有字幕时提示
                        sub_count = len(res.get("subtitle_opts", []))
                        if sub_count > 0:
                            self.update_log(
                                f"✅ 检测到 {sub_count} 个字幕轨道，可在字幕选项中选择。"
                            )
                        else:
                            self.update_log("ℹ️ 该视频暂无可用字幕。")

                        # 立即计算一次预估大小
                        self.update_size_estimate()

                    else:
                        self.is_playlist = False
                        self.playlist_entries = []
                        self._current_item_info = None
                        self.title_label.configure(
                            text="解析失败", text_color="#FF4A4A"
                        )
                        self.update_log(f"解析失败: {res.get('message')}")
                        self.size_label.configure(
                            text="📦 预估大小: 解析后显示", text_color="gray"
                        )
                finally:
                    self._is_fetching = False
                    if not self._is_closing:
                        self.fetch_btn.configure(state="normal")

            self.after(0, update_ui)

        threading.Thread(target=fetch_task, daemon=True).start()

    def open_dependency_settings(self):
        """打开依赖设置/引导弹窗"""
        if self.ffmpeg_location and self.ffmpeg_type != "未检测到":
            self.update_log(
                f"ℹ️ 当前 FFmpeg 就绪状态: {self.ffmpeg_type} (路径: {self.ffmpeg_location})"
            )
        else:
            self.update_log(
                "⚠️ 未检测到 FFmpeg 引擎，请执行 pip install imageio-ffmpeg 或安装系统 FFmpeg。"
            )

    def on_dependency_updated(self, path, source):
        """当依赖发生更新时刷新界面状态与下载器配置"""
        self.ffmpeg_location = path
        self.ffmpeg_type = source
        self.downloader.ffmpeg_location = path

        ffmpeg_is_ok = (
            self.ffmpeg_location is not None and self.ffmpeg_type != "未检测到"
        )
        badge_text = f"⚙️ FFmpeg: {self.ffmpeg_type}"
        badge_fg = ("#D4EDDA", "#1E3A2F") if ffmpeg_is_ok else ("#F8D7DA", "#3E2723")
        badge_text_color = (
            ("#155724", "#4CAF50") if ffmpeg_is_ok else ("#721C24", "#EF5350")
        )

        self.ffmpeg_badge.configure(
            text=badge_text,
            fg_color=badge_fg,
            text_color=badge_text_color,
            hover_color=badge_fg,
        )
        if ffmpeg_is_ok:
            self.update_log(f"✅ FFmpeg 依赖已就绪: {self.ffmpeg_type} -> {path}")
        else:
            self.update_log("⚠️ 当前未检测到可用 FFmpeg 引擎。")

    def on_download(self):
        if self._is_downloading:
            return

        if not self.ffmpeg_location or self.ffmpeg_type == "未检测到":
            self.update_log(
                "⚠️ 提示: 缺少 FFmpeg 引擎可能导致部分清晰度合并或转码失败，点击右上角【⚙️ FFmpeg】可配置。"
            )

        if self.fetch_btn.cget("state") == "disabled":
            self.update_log("错误: 请等待解析完成后再开始下载。")
            return

        url = self.url_entry.get().strip()
        if not url:
            self.update_log("错误: 请先输入视频链接。")
            return

        if not os.path.isdir(self.output_dir):
            self.update_log(f"错误: 保存目录不存在，请重新选择: {self.output_dir}")
            return

        # 映射UI选择到后台参数
        v_desc = self.v_quality_var.get()
        a_desc = self.a_quality_var.get()
        v_id = self.v_opts_map.get(v_desc, {"id": "best"})["id"]
        a_id = self.a_opts_map.get(a_desc, {"id": "best"})["id"]
        format_type = self.format_var.get().lower()

        # 字幕参数
        s_desc = self.sub_var.get()
        subtitle_lang = self.s_opts_map.get(s_desc, None)  # None = 无字幕
        subtitle_embed = self.sub_mode_var.get() == "嵌入视频"

        # 播放列表选集过滤
        playlist_items_param = (
            self._get_selected_playlist_items_param() if self.is_playlist else None
        )
        if (
            self.is_playlist
            and self.playlist_mode_var.get() == "勾选单集"
            and playlist_items_param == "0"
        ):
            self.update_log("错误: 请至少勾选一个要下载的视频条目。")
            return

        # 高级设置：断点续传与缓存保留
        keep_cache = self.resume_download_var.get()
        cleanup_on_cancel = not keep_cache

        self._is_downloading = True
        self.download_btn.configure(state="disabled", text="下 载 中 ...")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0)
        self.status_label.configure(text="初始化下载...")

        def download_task():
            self.update_log("\n--- 开始下载任务 ---")
            self.update_log(f"URL: {url}")
            if self.is_playlist:
                mode_name = self.playlist_mode_var.get()
                self.update_log(f"任务类型: 播放列表/合集批量下载 (模式: {mode_name})")
                if playlist_items_param:
                    self.update_log(f"选集范围/序号: {playlist_items_param}")
            self.update_log(f"视频选项: {v_desc}")
            self.update_log(f"音频选项: {a_desc}")
            self.update_log(f"输出格式: {format_type}")
            if subtitle_lang:
                mode_str = "嵌入视频" if subtitle_embed else "单独下载"
                self.update_log(f"字幕语言: {s_desc} ({mode_str})")
            self.update_log(
                f"断点续传: {'开启 (保留未完成缓存)' if keep_cache else '关闭'}"
            )
            self.update_log(f"保存至: {self.output_dir}")

            res = self.downloader.download(
                url=url,
                output_path=self.output_dir,
                video_format_id=v_id,
                audio_format_id=a_id,
                format_type=format_type,
                cookiefile=self.cookie_file,
                subtitle_lang=subtitle_lang,
                subtitle_embed=subtitle_embed,
                is_playlist=self.is_playlist,
                playlist_items=playlist_items_param,
                cleanup_on_cancel=cleanup_on_cancel,
            )

            def update_ui():
                self._is_downloading = False
                self.download_btn.configure(state="normal", text="开 始 下 载")
                self.cancel_btn.configure(state="disabled")
                if res["status"] == "success":
                    self.status_label.configure(text="✅ 下载完成！")
                    self.update_log("--- 任务圆满完成 ---")
                elif res["status"] == "cancelled":
                    self.status_label.configure(text="⏸️ 已取消")
                    self.progress_bar.set(0)
                    self.update_log("下载已取消")
                else:
                    self.status_label.configure(text="❌ 下载出错")
                    self.update_log(f"错误信息: {res.get('message')}")

            self.after(0, update_ui)

        self._download_thread = threading.Thread(target=download_task, daemon=True)
        self._download_thread.start()
