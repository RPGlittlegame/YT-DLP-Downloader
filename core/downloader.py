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
        提取视频信息（如标题及所有可用格式），不进行下载
        """
        opts = self.get_base_options()
        opts['extract_flat'] = 'in_playlist' # 快速提取，但对于单个视频会提取详细信息
        if cookiefile and os.path.exists(cookiefile):
            opts['cookiefile'] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title')
                
                formats = info.get('formats', [])
                video_opts = []
                audio_opts = []
                
                for f in formats:
                    f_id = f.get('format_id')
                    ext = f.get('ext', 'unknown')
                    vcodec = f.get('vcodec', 'none')
                    acodec = f.get('acodec', 'none')
                    
                    if vcodec != 'none':
                        height = f.get('height') or 0
                        fps = f.get('fps')
                        fps_str = f" {fps}fps" if fps else ""
                        v_str = f"{height}p{fps_str} - {ext} ({vcodec})"
                        video_opts.append({'id': f_id, 'desc': v_str, 'height': height})
                        
                    if acodec != 'none':
                        abr = f.get('abr') or 0
                        abr_str = f"{abr}k" if abr else "unknown"
                        a_str = f"{abr_str} - {ext} ({acodec})"
                        audio_opts.append({'id': f_id, 'desc': a_str, 'abr': abr})
                        
                # 排序：视频按分辨率降序，音频按比特率降序
                video_opts = sorted(video_opts, key=lambda x: x['height'], reverse=True)
                audio_opts = sorted(audio_opts, key=lambda x: x['abr'], reverse=True)
                
                return {
                    'status': 'success', 
                    'title': title, 
                    'video_opts': video_opts,
                    'audio_opts': audio_opts,
                    'info': info
                }
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

    def download(self, url, output_path, video_format_id='best', audio_format_id='best', format_type='mp4', cookiefile=None):
        """
        执行视频下载
        """
        self._is_cancelled = False
        opts = self.get_base_options()

        # 配置存储路径
        outtmpl = os.path.join(output_path, '%(title)s.%(ext)s')
        opts['outtmpl'] = outtmpl

        # 构造 format 字符串
        v_id = video_format_id
        a_id = audio_format_id
        
        if v_id == 'none' and a_id == 'none':
            opts['format'] = 'bestvideo+bestaudio/best'
        elif v_id == 'none':
            opts['format'] = a_id
            opts['extract_audio'] = True
        elif a_id == 'none':
            opts['format'] = v_id
        else:
            if v_id == 'best' and a_id == 'best':
                opts['format'] = 'bestvideo+bestaudio/best'
            elif v_id == 'best':
                opts['format'] = f'bestvideo+{a_id}/best'
            elif a_id == 'best':
                opts['format'] = f'{v_id}+bestaudio/best'
            else:
                opts['format'] = f'{v_id}+{a_id}'
        
        # 配置合并格式或后处理 (如果是纯音频则单独处理)
        if v_id != 'none':
            opts['merge_output_format'] = format_type
        else:
            # 纯音频下载，考虑将音频提取/转换为选定的音频格式
            # 用户在UI的“格式”中如果选了MP3，我们就转成MP3，否则保持原样或转换为其他支持格式
            if format_type in ['mp3', 'm4a', 'wav', 'flac']:
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format_type,
                    'preferredquality': '192' if format_type == 'mp3' else '0',
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
