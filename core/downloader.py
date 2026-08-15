from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class MyLogger:
    """用于拦截 yt-dlp 日志输出的自定义日志记录器"""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return  # 忽略 debug 级别的调试信息，避免日志过多
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
    """封装 yt-dlp 的核心下载逻辑"""

    def __init__(
        self,
        ffmpeg_location=None,
        log_callback=None,
        progress_callback=None,
        playlist_item_callback=None,
    ):
        self.ffmpeg_location = ffmpeg_location
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.playlist_item_callback = playlist_item_callback
        # 记录当前下载的进度状态与取消事件
        self._cancel_event = threading.Event()
        self._current_filenames = set()

    def format_error_message(self, err: BaseException | str) -> str:
        """将 yt-dlp 产生的异常信息解析为用户友好的提示信息"""
        msg = str(err)
        # 去除 ANSI 终端颜色控制码
        clean_msg = _ANSI_ESCAPE.sub("", msg).strip()

        # 常见错误特征匹配与分类引导
        if "HTTP Error 403" in clean_msg or "Forbidden" in clean_msg:
            return (
                "请求被服务器拒绝 (HTTP 403 Forbidden)。\n"
                "💡 建议：该网站可能有反爬或防盗链限制，请尝试在上方配置对应的 Cookie 文件后再试。"
            )
        elif (
            "Sign in to confirm you’re not a bot" in clean_msg
            or "Sign in to confirm your age" in clean_msg
            or "login" in clean_msg.lower()
        ):
            return (
                "需要登录验证 (年龄限制 / 人机验证 / 会员专享)。\n"
                "💡 建议：请在浏览器中登录该网站，导出 cookies.txt 放入 cookies/ 目录并选用后重试。"
            )
        elif (
            clean_msg.find("This video is not available") != -1
            or clean_msg.find("Video unavailable") != -1
        ):
            return (
                "视频不可用。\n"
                "💡 建议：视频可能已被作者删除、设为私享或在当前地区受限 (Geo-restricted)。"
            )
        elif "Unsupported URL" in clean_msg:
            return "不支持的链接格式。\n💡 建议：请检查输入的 URL 是否完整且正确。"
        elif "ffmpeg" in clean_msg.lower() and (
            "not found" in clean_msg.lower() or "missing" in clean_msg.lower()
        ):
            return (
                "FFmpeg 缺失或无法执行。\n"
                "💡 建议：点击右上方 FFmpeg 状态胶囊，根据指引自动安装或手动配置 FFmpeg。"
            )
        elif (
            "timed out" in clean_msg.lower()
            or "connection reset" in clean_msg.lower()
            or "network" in clean_msg.lower()
        ):
            return "网络连接超时或中断。\n💡 建议：请检查网络连接或代理设置后重试。"

        # 默认返回提取后的简洁错误信息
        # 如果包含 ERROR: 前缀，提取主要错误行
        error_lines = [
            line.strip() for line in clean_msg.splitlines() if "ERROR:" in line
        ]
        if error_lines:
            return "\n".join(error_lines)
        return clean_msg[:300] if len(clean_msg) > 300 else clean_msg

    def get_base_options(self):
        """获取 yt-dlp 基础配置选项"""
        opts = {
            "logger": MyLogger(self.log_callback),
            "progress_hooks": [self._progress_hook],
            "noprogress": True,  # 禁用默认控制台进度条
            "quiet": False,
            "socket_timeout": 30,
            # 断点续传支持：默认保留 .part 文件并允许继续下载
            "continuedl": True,
        }
        if self.ffmpeg_location and os.path.exists(self.ffmpeg_location):
            opts["ffmpeg_location"] = self.ffmpeg_location
        return opts

    def _progress_hook(self, d):
        """处理 yt-dlp 进度回调"""
        if "filename" in d and d["filename"]:
            self._current_filenames.add(d["filename"])

        if self._cancel_event.is_set():
            raise DownloadCancelled("Download cancelled by user.")

        if d["status"] == "downloading":
            try:
                downloaded = d.get("downloaded_bytes", 0) or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0) or 1
                percent = min(downloaded / total, 1.0)
                speed = d.get("_speed_str", "N/A")
                eta = d.get("_eta_str", "N/A")

                if self.progress_callback:
                    self.progress_callback(percent, speed, eta)
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        elif d["status"] == "finished":
            if self.progress_callback:
                self.progress_callback(1.0, "Done", "0s")
            if self.log_callback:
                self.log_callback("Download complete, now post-processing...")
        elif d["status"] == "error" and self.log_callback:
            self.log_callback("Error occurred during download.")

    def fetch_info(self, url, cookiefile=None):
        """提取视频或播放列表信息（如标题、所有可用格式、字幕或播放列表条目），不进行下载"""
        opts = self.get_base_options()
        opts["extract_flat"] = "in_playlist"  # 快速探测是否为播放列表
        if cookiefile and os.path.exists(cookiefile):
            opts["cookiefile"] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return {
                        "status": "error",
                        "message": "未能获取到任何视频或播放列表信息。",
                    }

                # --- 处理播放列表情况 ---
                if info.get("_type") == "playlist" or "entries" in info:
                    raw_entries = info.get("entries")
                    entries = []
                    if raw_entries:
                        for entry in raw_entries:
                            if entry:
                                entries.append(entry)
                    items = []
                    for idx, entry in enumerate(entries, 1):
                        e_title = entry.get("title") or f"视频 {idx}"
                        e_url = (
                            entry.get("url")
                            or entry.get("webpage_url")
                            or entry.get("id")
                        )
                        e_dur = entry.get("duration")
                        dur_str = (
                            f"{int(e_dur // 60):02d}:{int(e_dur % 60):02d}"
                            if e_dur
                            else ""
                        )
                        items.append(
                            {
                                "index": idx,
                                "id": entry.get("id", str(idx)),
                                "title": e_title,
                                "url": e_url,
                                "duration_str": dur_str,
                            }
                        )

                    return {
                        "status": "success",
                        "is_playlist": True,
                        "title": info.get("title", "播放列表"),
                        "playlist_count": len(items),
                        "items": items,
                        "video_opts": [{"id": "best", "desc": "自动最高画质 (Best)"}],
                        "audio_opts": [{"id": "best", "desc": "自动最高音质 (Best)"}],
                        "subtitle_opts": [],
                    }

                # --- 单个视频解析流程 ---
                title = info.get("title", "Unknown Title")
                formats = info.get("formats") or []
                video_opts = []
                audio_opts = []

                for f in formats:
                    f_id = f.get("format_id")
                    ext = f.get("ext", "unknown")
                    vcodec = f.get("vcodec", "none")
                    acodec = f.get("acodec", "none")
                    # 获取文件大小（优先精确值，否则取估算值）
                    filesize = f.get("filesize") or f.get("filesize_approx")

                    if vcodec != "none":
                        height = f.get("height") or 0
                        fps = f.get("fps")
                        fps_str = f" {fps}fps" if fps else ""
                        v_str = f"{height}p{fps_str} - {ext} ({vcodec})"
                        video_opts.append(
                            {
                                "id": f_id,
                                "desc": v_str,
                                "height": height,
                                "filesize": filesize,
                            }
                        )

                    if acodec != "none":
                        abr = f.get("abr") or 0
                        abr_str = f"{abr}k" if abr else "unknown"
                        a_str = f"{abr_str} - {ext} ({acodec})"
                        audio_opts.append(
                            {
                                "id": f_id,
                                "desc": a_str,
                                "abr": abr,
                                "filesize": filesize,
                            }
                        )

                # 排序：视频按分辨率降序，音频按比特率降序
                video_opts = sorted(video_opts, key=lambda x: x["height"], reverse=True)
                audio_opts = sorted(audio_opts, key=lambda x: x["abr"], reverse=True)

                # --- 提取字幕信息 ---
                subtitle_opts = []
                manual_subs = info.get("subtitles", {})
                auto_subs = info.get("automatic_captions", {})

                for lang, sub_list in manual_subs.items():
                    # 尝试获取语言名称（部分格式携带 name 字段）
                    name = lang
                    if (
                        sub_list
                        and isinstance(sub_list, list)
                        and sub_list[0].get("name")
                    ):
                        name = sub_list[0]["name"]
                    subtitle_opts.append(
                        {
                            "lang": lang,
                            "desc": f"{name} ({lang})",
                            "auto": False,
                        }
                    )

                for lang, sub_list in auto_subs.items():
                    if lang in manual_subs:
                        continue  # 手动字幕优先，跳过同语言的自动字幕
                    name = lang
                    if (
                        sub_list
                        and isinstance(sub_list, list)
                        and sub_list[0].get("name")
                    ):
                        name = sub_list[0]["name"]
                    subtitle_opts.append(
                        {
                            "lang": lang,
                            "desc": f"{name} [{lang}] (自动)",
                            "auto": True,
                        }
                    )

                # 排序：手动字幕优先，然后按语言代码字母顺序
                subtitle_opts.sort(key=lambda x: (x["auto"], x["lang"]))

                return {
                    "status": "success",
                    "is_playlist": False,
                    "title": title,
                    "video_opts": video_opts,
                    "audio_opts": audio_opts,
                    "subtitle_opts": subtitle_opts,
                }
            except Exception as e:
                friendly_msg = self.format_error_message(e)
                return {"status": "error", "message": friendly_msg}

    def download(
        self,
        url,
        output_path,
        video_format_id="best",
        audio_format_id="best",
        format_type="mp4",
        cookiefile=None,
        subtitle_lang=None,
        subtitle_embed=True,
        is_playlist=False,
        playlist_items=None,
        cleanup_on_cancel=False,
    ):
        """执行视频或播放列表下载，支持断点续传、字幕下载与取消控制

        :param cleanup_on_cancel: 取消时是否彻底删除未完成的 .part 临时文件。为 False
        时保留 .part 文件以便后续断点续传
        """
        self._cancel_event.clear()
        self._current_filenames.clear()
        opts = self.get_base_options()

        # 配置存储路径与模板
        if is_playlist:
            # 播放列表组织为专属文件夹或前缀编号
            outtmpl = os.path.join(
                output_path,
                "%(playlist_title|Playlist)s",
                "%(playlist_index&{:03d} - |)s%(title)s.%(ext)s",
            )
            if playlist_items:
                # 支持选择指定的集数范围（例如 '1,3-5,8'）
                opts["playlist_items"] = str(playlist_items)
            opts["noplaylist"] = False
        else:
            outtmpl = os.path.join(output_path, "%(title)s.%(ext)s")
            opts["noplaylist"] = True

        opts["outtmpl"] = outtmpl

        # 构造 format 字符串
        v_id = video_format_id
        a_id = audio_format_id

        if v_id == "none" and a_id == "none":
            opts["format"] = "bestvideo+bestaudio/best"
        elif v_id == "none":
            opts["format"] = a_id
            opts["extract_audio"] = True
        elif a_id == "none":
            opts["format"] = v_id
        else:
            if v_id == "best" and a_id == "best":
                opts["format"] = "bestvideo+bestaudio/best"
            elif v_id == "best":
                opts["format"] = f"bestvideo+{a_id}/best"
            elif a_id == "best":
                opts["format"] = f"{v_id}+bestaudio/best"
            else:
                opts["format"] = f"{v_id}+{a_id}"

        # 配置合并格式或后处理 (如果是纯音频则单独处理)
        if v_id != "none":
            opts["merge_output_format"] = format_type
        else:
            # 纯音频下载，提取/转换为选定的音频格式
            audio_format = (
                format_type
                if format_type in ["mp3", "m4a", "wav", "flac", "opus"]
                else "mp3"
            )
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "192" if audio_format == "mp3" else "0",
                }
            ]

        # --- 配置字幕 ---
        if subtitle_lang and subtitle_lang != "none":
            opts["writesubtitles"] = True
            opts["subtitleslangs"] = [subtitle_lang]
            opts["subtitlesformat"] = "srt/vtt"
            if subtitle_embed and v_id != "none":
                # 嵌入字幕到视频文件中
                opts["embedsubtitles"] = True
                pp_list = opts.get("postprocessors", [])
                pp_list.append({"key": "FFmpegEmbedSubtitle"})
                opts["postprocessors"] = pp_list

        # 配置 Cookie
        if cookiefile and os.path.exists(cookiefile):
            opts["cookiefile"] = cookiefile

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            try:
                ydl.download([url])
                return {"status": "success"}
            except DownloadCancelled:
                if cleanup_on_cancel:
                    self._cleanup_partial_files(base_dir=output_path)
                elif self.log_callback:
                    self.log_callback(
                        "⏸️ 下载已暂停/取消。保留未完成的 .part 临时文件，支持下次继续下载。"
                    )
                return {"status": "cancelled", "message": "用户已取消下载"}
            except BaseException as err:
                msg = str(err)
                if self._cancel_event.is_set():
                    if cleanup_on_cancel:
                        self._cleanup_partial_files(base_dir=output_path)
                    elif self.log_callback:
                        self.log_callback(
                            "⏸️ 下载已暂停/取消。保留未完成的 .part 临时文件，支持下次继续下载。"
                        )
                    return {"status": "cancelled", "message": "用户已取消下载"}
                if "Download cancelled" in msg:
                    if cleanup_on_cancel:
                        self._cleanup_partial_files(base_dir=output_path)
                    elif self.log_callback:
                        self.log_callback(
                            "⏸️ 下载已暂停/取消。保留未完成的 .part 临时文件，支持下次继续下载。"
                        )
                    return {"status": "cancelled", "message": "用户已取消下载"}
                friendly_msg = self.format_error_message(err)
                return {"status": "error", "message": friendly_msg}

    @staticmethod
    def _is_path_safe(target_path: str, base_dir: str) -> bool:
        """检查 target_path 是否安全地包含在 base_dir 目录之内，防御路径遍历攻击"""
        try:
            target = Path(target_path).resolve()
            base = Path(base_dir).resolve()
            target.relative_to(base)
            return True
        except (ValueError, Exception):
            return False

    def _cleanup_partial_files(self, base_dir: str | None = None):
        """清理下载一半产生的残留文件（如取消且用户选择彻底清理时）

        :param base_dir: 限制清理的文件所在的基础输出目录，进行路径安全约束
        """
        for f in list(self._current_filenames):
            for ext in ["", ".part", ".ytdl"]:
                path = f + ext
                if path.endswith(".part.part"):
                    continue

                if os.path.exists(path):
                    # 路径遍历安全防御：若提供了 base_dir，必须确保目标文件在 base_dir 内部
                    if base_dir and not self._is_path_safe(path, base_dir):
                        if self.log_callback:
                            self.log_callback(
                                f"⚠️ 警告: 跳过非安全目录内的清理项: {path}"
                            )
                        continue

                    try:
                        os.remove(path)
                        if self.log_callback:
                            self.log_callback(
                                f"🧹 已清理残留文件: {os.path.basename(path)}"
                            )
                    except Exception:
                        pass

    def cancel_download(self):
        """取消当前正在进行的下载任务"""
        self._cancel_event.set()
