import os
import shutil
import threading
import customtkinter as ctk
from tkinter import filedialog
from core.downloader import YTDlpDownloader

# 设置主题跟随系统
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self, ffmpeg_location=None):
        super().__init__()

        self.ffmpeg_location = ffmpeg_location
        self.downloader = YTDlpDownloader(
            ffmpeg_location=self.ffmpeg_location,
            log_callback=self.update_log,
            progress_callback=self.update_progress
        )
        
        # 窗口配置
        self.title("YT-DLP Downloader")
        self.geometry("600x550")
        self.minsize(500, 500)
        
        # 网格布局配置
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        
        self.create_widgets()
        
        # 默认值设置
        self.output_dir = os.path.expanduser("~/Downloads")
        self.output_btn.configure(text=f"📁 {self.output_dir}")
        self.cookie_file = None
        self.cookie_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies")
        self.v_opts_map = {}
        self.a_opts_map = {}
        
        # 初始化状态
        self._is_downloading = False
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 初始化 cookie 列表
        self.update_cookie_list()

    def on_closing(self):
        if self._is_downloading:
            self.downloader.cancel_download()
        self.destroy()

    def create_widgets(self):
        # --- 顶部输入区 ---
        self.top_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.top_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.url_label = ctk.CTkLabel(self.top_frame, text="URL:", font=ctk.CTkFont(size=13, weight="bold"))
        self.url_label.grid(row=0, column=0, padx=(0, 5), pady=5)

        self.url_entry = ctk.CTkEntry(self.top_frame, placeholder_text="在此输入视频链接...", height=30, corner_radius=6)
        self.url_entry.grid(row=0, column=1, padx=(0, 5), pady=5, sticky="ew")

        self.fetch_btn = ctk.CTkButton(self.top_frame, text="解析", width=60, height=30, corner_radius=6, command=self.on_fetch)
        self.fetch_btn.grid(row=0, column=2, pady=5)

        # 解析出的标题显示
        self.title_label = ctk.CTkLabel(self.top_frame, text="等待解析...", text_color="gray", font=ctk.CTkFont(size=12))
        self.title_label.grid(row=1, column=0, columnspan=3, pady=(0, 5), sticky="w")

        # --- 选项设置区 ---
        self.options_frame = ctk.CTkFrame(self, corner_radius=10)
        self.options_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.options_frame.grid_columnconfigure(1, weight=1)
        self.options_frame.grid_columnconfigure(3, weight=1)

        # 视频清晰度
        self.v_quality_label = ctk.CTkLabel(self.options_frame, text="视频:")
        self.v_quality_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.v_quality_var = ctk.StringVar(value="自动 (Best)")
        self.v_quality_combo = ctk.CTkComboBox(self.options_frame, variable=self.v_quality_var, 
                                               values=["自动 (Best)"], corner_radius=6, width=140)
        self.v_quality_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        # 音频质量
        self.a_quality_label = ctk.CTkLabel(self.options_frame, text="音频:")
        self.a_quality_label.grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.a_quality_var = ctk.StringVar(value="自动 (Best)")
        self.a_quality_combo = ctk.CTkComboBox(self.options_frame, variable=self.a_quality_var, 
                                               values=["自动 (Best)"], corner_radius=6, width=140)
        self.a_quality_combo.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        # 格式
        self.format_label = ctk.CTkLabel(self.options_frame, text="格式:")
        self.format_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.format_var = ctk.StringVar(value="MP4")
        self.format_combo = ctk.CTkComboBox(self.options_frame, variable=self.format_var,
                                            values=["MP4", "MKV", "AVI", "WMV", "MOV", "MP3"], corner_radius=6, width=140)
        self.format_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # 路径选择
        self.path_label = ctk.CTkLabel(self.options_frame, text="保存至:")
        self.path_label.grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.output_btn = ctk.CTkButton(self.options_frame, text="选择目录", fg_color="transparent", 
                                        border_width=1, text_color=("gray10", "#DCE4EE"), corner_radius=6, command=self.choose_output_dir, width=140)
        self.output_btn.grid(row=1, column=3, padx=5, pady=5, sticky="w")

        # Cookie 选择
        self.cookie_label = ctk.CTkLabel(self.options_frame, text="Cookies:")
        self.cookie_label.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        
        self.cookie_frame = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        self.cookie_frame.grid(row=2, column=1, columnspan=3, padx=5, pady=(0, 10), sticky="ew")
        self.cookie_frame.grid_columnconfigure(0, weight=1)

        self.cookie_var = ctk.StringVar(value="未选择 (可选)")
        self.cookie_menu = ctk.CTkOptionMenu(self.cookie_frame, variable=self.cookie_var,
                                             values=["未选择 (可选)"], corner_radius=6, command=self.on_cookie_select)
        self.cookie_menu.grid(row=0, column=0, sticky="ew")

        self.cookie_import_btn = ctk.CTkButton(self.cookie_frame, text="导入 Cookie", width=90, corner_radius=6, command=self.import_cookie_file)
        self.cookie_import_btn.grid(row=0, column=1, padx=(5, 0))

        # --- 下载按钮区 ---
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.action_frame.grid_columnconfigure(1, weight=0)
        
        self.download_btn = ctk.CTkButton(self.action_frame, text="开 始 下 载", font=ctk.CTkFont(size=14, weight="bold"), 
                                          height=35, corner_radius=6, command=self.on_download)
        self.download_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.cancel_btn = ctk.CTkButton(self.action_frame, text="取消", font=ctk.CTkFont(size=14, weight="bold"), 
                                        width=80, height=35, corner_radius=6, fg_color="#E74C3C", hover_color="#C0392B", 
                                        state="disabled", command=self.on_cancel)
        self.cancel_btn.grid(row=0, column=1, sticky="e")

        # --- 进度与日志区 ---
        self.log_frame = ctk.CTkFrame(self, corner_radius=10)
        self.log_frame.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(2, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.log_frame, corner_radius=6)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(self.log_frame, text="准备就绪", font=ctk.CTkFont(size=11))
        self.status_label.grid(row=1, column=0, pady=(0, 5))

        self.log_box = ctk.CTkTextbox(self.log_frame, corner_radius=6, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.log_box.configure(state="disabled")

    def choose_output_dir(self):
        dir_path = filedialog.askdirectory(initialdir=self.output_dir)
        if dir_path:
            self.output_dir = dir_path
            self.output_btn.configure(text=f"📁 {self.output_dir}")

    def update_cookie_list(self):
        if not os.path.exists(self.cookie_dir):
            os.makedirs(self.cookie_dir)
            
        cookies = ["未选择 (可选)"]
        for f in os.listdir(self.cookie_dir):
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
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline()
            if 'Netscape' not in first_line and not first_line.startswith('#'):
                self.update_log(f"⚠️ 警告: {choice} 可能不是有效的 Netscape Cookie 格式文件。")
        except OSError:
            self.update_log(f"⚠️ 警告: 无法读取 Cookie 文件 {choice}。")
            
        self.cookie_file = path

    def import_cookie_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if file_path:
            if not os.path.exists(self.cookie_dir):
                os.makedirs(self.cookie_dir)
                
            filename = os.path.basename(file_path)
            dest_path = os.path.join(self.cookie_dir, filename)
            
            if not os.path.abspath(dest_path).startswith(os.path.abspath(self.cookie_dir)):
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

    def update_log(self, msg):
        """ 线程安全的日志更新 """
        def task():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, task)

    def update_progress(self, percent, speed, eta):
        """ 线程安全的进度条更新 """
        def task():
            self.progress_bar.set(percent)
            self.status_label.configure(text=f"{percent*100:.1f}% | 速度: {speed} | 剩余: {eta}")
        self.after(0, task)

    def on_cancel(self):
        self.update_log("正在取消下载，请稍候...")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text="正在中止并清理文件...")
        self.downloader.cancel_download()

    def on_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            self.update_log("错误: 请输入有效的 URL。")
            return

        self.fetch_btn.configure(state="disabled")
        self.title_label.configure(text="正在解析中，请稍候...", text_color="white")
        self.update_log(f"开始解析: {url}")

        def fetch_task():
            res = self.downloader.fetch_info(url, self.cookie_file)
            def update_ui():
                if res['status'] == 'success':
                    self.title_label.configure(text=f"📌 {res['title']}", text_color="#2CC985")
                    self.update_log(f"解析成功: {res['title']}")
                    
                    # 动态填充下拉框
                    self.v_opts_map = {"自动 (Best)": "best", "无 (仅音频)": "none"}
                    self.a_opts_map = {"自动 (Best)": "best", "无 (仅视频)": "none"}
                    
                    v_vals = ["自动 (Best)", "无 (仅音频)"]
                    for vo in res.get('video_opts', []):
                        v_vals.append(vo['desc'])
                        self.v_opts_map[vo['desc']] = vo['id']
                        
                    a_vals = ["自动 (Best)", "无 (仅视频)"]
                    for ao in res.get('audio_opts', []):
                        a_vals.append(ao['desc'])
                        self.a_opts_map[ao['desc']] = ao['id']
                        
                    self.v_quality_combo.configure(values=v_vals)
                    self.a_quality_combo.configure(values=a_vals)
                    self.v_quality_var.set("自动 (Best)")
                    self.a_quality_var.set("自动 (Best)")
                    
                else:
                    self.title_label.configure(text="解析失败", text_color="#FF4A4A")
                    self.update_log(f"解析失败: {res.get('message')}")
                self.fetch_btn.configure(state="normal")
            self.after(0, update_ui)

        threading.Thread(target=fetch_task, daemon=True).start()

    def on_download(self):
        if self._is_downloading:
            return
            
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
        v_id = self.v_opts_map.get(v_desc, "best")
        a_id = self.a_opts_map.get(a_desc, "best")
        format_type = self.format_var.get().lower()

        self._is_downloading = True
        self.download_btn.configure(state="disabled", text="下 载 中 ...")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0)
        self.status_label.configure(text="初始化下载...")

        def download_task():
            self.update_log(f"\n--- 开始下载任务 ---")
            self.update_log(f"URL: {url}")
            self.update_log(f"视频选项: {v_desc}")
            self.update_log(f"音频选项: {a_desc}")
            self.update_log(f"输出格式: {format_type}")
            self.update_log(f"保存至: {self.output_dir}")

            res = self.downloader.download(
                url=url,
                output_path=self.output_dir,
                video_format_id=v_id,
                audio_format_id=a_id,
                format_type=format_type,
                cookiefile=self.cookie_file
            )

            def update_ui():
                self._is_downloading = False
                self.download_btn.configure(state="normal", text="开 始 下 载")
                self.cancel_btn.configure(state="disabled")
                if res['status'] == 'success':
                    self.status_label.configure(text="✅ 下载完成！")
                    self.update_log("--- 任务圆满完成 ---")
                elif res['status'] == 'cancelled':
                    self.status_label.configure(text="⏸️ 已取消")
                    self.progress_bar.set(0)
                    self.update_log("下载已取消")
                else:
                    self.status_label.configure(text="❌ 下载出错")
                    self.update_log(f"错误信息: {res.get('message')}")
            self.after(0, update_ui)

        threading.Thread(target=download_task, daemon=True).start()
