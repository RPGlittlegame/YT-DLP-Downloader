import os
import yt_dlp
import threading
import re

_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')

class MyLogger:
    """
    用于拦截 yt-dlp 日志输出的自定义日志记录器
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def debug(self, msg):
        if msg.startswith('[debug] '):
            return # 忽略 debug 级别的调试信息，避免日志过多
        if self.log_callback:
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
        self._cancel_event = threading.Event()
        self._current_filenames = set()

    def get_base_options(self):
        """
        获取 yt-dlp 基础配置选项
        """
        opts = {
            'logger': MyLogger(self.log_callback),
            'progress_hooks': [self._progress_hook],
            'noprogress': True, # 禁用默认控制台进度条
            'quiet': False,
            'socket_timeout': 30,
        }
        if self.ffmpeg_location and os.path.exists(self.ffmpeg_location):
            opts['ffmpeg_location'] = self.ffmpeg_location
        return opts

    def _progress_hook(self, d):
        """
        处理 yt-dlp 进度回调
        """
        if 'filename' in d and d['filename']:
            self._current_filenames.add(d['filename'])
            
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")

        if d['status'] == 'downloading':
            try:
                downloaded = d.get('downloaded_bytes', 0) or 0
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0) or 1
                percent = min(downloaded / total, 1.0)
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                
                if self.progress_callback:
                    self.progress_callback(percent, speed, eta)
            except (ValueError, TypeError, ZeroDivisionError):
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
        opts['noplaylist'] = True # 若URL包含播放列表，只解析第一个视频
        if cookiefile and os.path.exists(cookiefile):
            opts['cookiefile'] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if info.get('_type') == 'playlist':
                    return {'status': 'error', 'message': '检测到播放列表链接。请使用单个视频 URL。'}
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
                    'audio_opts': audio_opts
                }
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

    def download(self, url, output_path, video_format_id='best', audio_format_id='best', format_type='mp4', cookiefile=None):
        """
        执行视频下载
        """
        self._cancel_event.clear()
        self._current_filenames.clear()
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
            audio_format = format_type if format_type in ['mp3', 'm4a', 'wav', 'flac', 'opus'] else 'mp3'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': '192' if audio_format == 'mp3' else '0',
            }]

        # 配置 Cookie
        if cookiefile and os.path.exists(cookiefile):
            opts['cookiefile'] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                ydl.download([url])
                return {'status': 'success'}
            except Exception as e:
                msg = str(e)
                if isinstance(e, yt_dlp.utils.DownloadCancelled) or self._cancel_event.is_set() or "Download cancelled" in msg:
                    self._cleanup_partial_files()
                    return {'status': 'cancelled', 'message': '用户已取消下载'}
                return {'status': 'error', 'message': msg}

    def _cleanup_partial_files(self):
        """清理下载一半产生的残留文件"""
        for f in self._current_filenames:
            # yt-dlp 可能会以不同的后缀存储临时文件
            for ext in ['', '.part', '.ytdl']:
                path = f + ext
                # 如果 f 本身带有 .part 后缀，不重复拼接
                if path.endswith('.part.part'):
                    continue
                    
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        if self.log_callback:
                            self.log_callback(f"🧹 已清理残留文件: {os.path.basename(path)}")
                    except Exception:
                        pass # 忽略删除失败的错误

    def cancel_download(self):
        """
        取消下载
        """
        self._cancel_event.set()
