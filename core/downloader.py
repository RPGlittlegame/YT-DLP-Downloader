import os
import yt_dlp
import threading

class MyLogger:
    """
    用于拦截 yt-dlp 日志输出的自定义日志记录器
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def debug(self, msg):
        if msg.startswith('[debug] '):
            pass # 忽略 debug 级别的调试信息，避免日志过多
        elif self.log_callback:
            self.log_callback(msg)

    def info(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def warning(self, msg):
        if self.log_callback:
            self.log_callback(f"WARNING: {msg}")

    def error(self, msg):
        if self.log_callback:
            self.log_callback(f"ERROR: {msg}")

class YTDlpDownloader:
    """
    封装 yt-dlp 的核心下载逻辑
    """
    def __init__(self, ffmpeg_location=None, log_callback=None, progress_callback=None):
        self.ffmpeg_location = ffmpeg_location
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        # 记录当前下载的进度状态
        self._is_cancelled = False

    def get_base_options(self):
        """
        获取 yt-dlp 基础配置选项
        """
        opts = {
            'logger': MyLogger(self.log_callback),
            'progress_hooks': [self._progress_hook],
            'noprogress': True, # 禁用默认控制台进度条
            'quiet': False,
        }
        if self.ffmpeg_location and os.path.exists(self.ffmpeg_location):
            opts['ffmpeg_location'] = self.ffmpeg_location
        return opts

    def _progress_hook(self, d):
        """
        处理 yt-dlp 进度回调
        """
        if self._is_cancelled:
            raise Exception("Download cancelled by user.")

        if d['status'] == 'downloading':
            try:
                # 尝试解析进度百分比
                percent_str = d.get('_percent_str', '0%').strip('\x1b[0;94m').strip('\x1b[0m').replace('%', '')
                percent = float(percent_str) / 100.0
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                
                if self.progress_callback:
                    self.progress_callback(percent, speed, eta)
            except Exception:
                pass
        elif d['status'] == 'finished':
            if self.progress_callback:
                self.progress_callback(1.0, "Done", "0s")
            if self.log_callback:
                self.log_callback("Download complete, now post-processing...")
        elif d['status'] == 'error':
            if self.log_callback:
                self.log_callback("Error occurred during download.")

    def fetch_info(self, url, cookiefile=None):
        """
        提取视频信息（如标题），不进行下载
        """
        opts = self.get_base_options()
        opts['extract_flat'] = 'in_playlist' # 快速提取
        if cookiefile and os.path.exists(cookiefile):
            opts['cookiefile'] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title')
                return {'status': 'success', 'title': title, 'info': info}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

    def download(self, url, output_path, quality='best', format_type='mp4', cookiefile=None):
        """
        执行视频下载
        """
        self._is_cancelled = False
        opts = self.get_base_options()

        # 配置存储路径
        outtmpl = os.path.join(output_path, '%(title)s.%(ext)s')
        opts['outtmpl'] = outtmpl

        # 配置质量与格式
        if quality == 'best':
            opts['format'] = 'bestvideo+bestaudio/best'
        elif quality == '1080p':
            opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        elif quality == '720p':
            opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
        elif quality == 'audio_only':
            opts['format'] = 'bestaudio/best'
            opts['extract_audio'] = True
        
        # 配置合并格式 (如果是纯音频则单独处理)
        if quality != 'audio_only':
            opts['merge_output_format'] = format_type
        else:
            if format_type == 'mp3':
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

        # 配置 Cookie
        if cookiefile and os.path.exists(cookiefile):
            opts['cookiefile'] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                ydl.download([url])
                return {'status': 'success'}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

    def cancel_download(self):
        """
        取消下载
        """
        self._is_cancelled = True
