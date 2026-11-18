from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from core.dependency_manager import dependency_manager

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_PLAYLIST_ITEM_RE = re.compile(
    r"\[download\]\s+Downloading\s+(?:item|video)\s+(\d+)\s+of\s+(\d+)"
)
_DEST_FILE_RE = re.compile(r"^\[download\]\s+Destination:\s+(.+)$")


class YTDlpDownloader:
    """封装系统 yt-dlp 可执行文件的核心下载逻辑（subprocess 调度）"""

    def __init__(
        self,
        ffmpeg_location=None,
        ytdlp_location=None,
        log_callback=None,
        progress_callback=None,
        playlist_item_callback=None,
    ):
        self.ffmpeg_location = ffmpeg_location
        self.ytdlp_location = (
            ytdlp_location
            if ytdlp_location is not None
            else dependency_manager.detect_ytdlp().get("path")
        )
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.playlist_item_callback = playlist_item_callback

        self._cancel_event = threading.Event()
        self._current_process: subprocess.Popen | None = None
        self._current_filenames: set[str] = set()

    @staticmethod
    def _creation_flags() -> int:
        return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def _has_valid_ytdlp(self) -> bool:
        return bool(self.ytdlp_location and os.path.isfile(self.ytdlp_location))

    def format_error_message(self, err: BaseException | str) -> str:
        """将 yt-dlp 产生的异常或输出信息解析为用户友好的提示信息"""
        msg = str(err)
        clean_msg = _ANSI_ESCAPE.sub("", msg).strip()
        lower_msg = clean_msg.lower()

        if "yt-dlp" in lower_msg and (
            "not found" in lower_msg
            or "missing" in lower_msg
            or "no such file" in lower_msg
            or "未检测" in clean_msg
        ):
            return (
                "yt-dlp 引擎缺失或无法执行。\n"
                "💡 建议：请点击右上方【⚙️ 依赖配置】，一键安装 yt-dlp 到系统目录或手动指定路径。"
            )
        if "please update yt-dlp" in lower_msg or "update yt-dlp" in lower_msg:
            return (
                "当前 yt-dlp 版本过旧，网站解析规则可能已变更。\n"
                "💡 建议：请在右上角【⚙️ 依赖配置】中点击重新安装更新，或终端运行 brew upgrade yt-dlp。"
            )
        if "HTTP Error 403" in clean_msg or "Forbidden" in clean_msg:
            return (
                "请求被服务器拒绝 (HTTP 403 Forbidden)。\n"
                "💡 建议：该网站可能有反爬或防盗链限制，请尝试在上方配置对应的 Cookie 文件后再试。"
            )
        if (
            "Sign in to confirm you’re not a bot" in clean_msg
            or "Sign in to confirm you're not a bot" in clean_msg
            or "Sign in to confirm your age" in clean_msg
            or "login" in lower_msg
        ):
            return (
                "需要登录验证 (年龄限制 / 人机验证 / 会员专享)。\n"
                "💡 建议：请在浏览器中登录该网站，导出 cookies.txt 放入 cookies/ 目录并选用后重试。"
            )
        if (
            "This video is not available" in clean_msg
            or "Video unavailable" in clean_msg
        ):
            return (
                "视频不可用。\n"
                "💡 建议：视频可能已被作者删除、设为私享或在当前地区受限 (Geo-restricted)。"
            )
        if "Unsupported URL" in clean_msg:
            return "不支持的链接格式。\n💡 建议：请检查输入的 URL 是否完整且正确。"
        if "ffmpeg" in lower_msg and (
            "not found" in lower_msg
            or "missing" in lower_msg
            or "not installed" in lower_msg
        ):
            return (
                "FFmpeg 缺失或无法执行。\n"
                "💡 建议：点击右上方【⚙️ 依赖配置】，一键安装 FFmpeg 到系统目录或手动指定路径。"
            )
        if (
            "timed out" in lower_msg
            or "connection reset" in lower_msg
            or "network" in lower_msg
        ):
            return "网络连接超时或中断。\n💡 建议：请检查网络连接或代理设置后重试。"

        error_lines = [
            line.strip() for line in clean_msg.splitlines() if "ERROR:" in line
        ]
        if error_lines:
            return "\n".join(error_lines)
        return clean_msg[:300] if len(clean_msg) > 300 else clean_msg

    @staticmethod
    def _parse_single_json(stdout: str) -> dict | None:
        text = stdout.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
        return None

    def fetch_info(self, url, cookiefile=None):
        """调用系统 yt-dlp 提取视频或播放列表信息，不进行下载"""
        if not self._has_valid_ytdlp():
            return {
                "status": "error",
                "message": "未检测到 yt-dlp 解析引擎。\n💡 建议：请点击右上角【⚙️ 依赖配置】一键安装到系统目录或手动指定路径。",
            }

        assert self.ytdlp_location is not None
        cmd = [
            self.ytdlp_location,
            "--dump-single-json",
            "--flat-playlist",
            "--no-warnings",
            "--color",
            "no_color",
            "--socket-timeout",
            "30",
        ]
        if self.ffmpeg_location and os.path.exists(self.ffmpeg_location):
            cmd.extend(["--ffmpeg-location", self.ffmpeg_location])
        if cookiefile and os.path.exists(cookiefile):
            cmd.extend(["--cookies", cookiefile])
        cmd.append(url)

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=self._creation_flags(),
            )
            if res.returncode != 0:
                err_output = res.stderr.strip() or res.stdout.strip() or f"yt-dlp 返回码 {res.returncode}"
                return {"status": "error", "message": self.format_error_message(err_output)}

            info = self._parse_single_json(res.stdout)
            if not info:
                return {
                    "status": "error",
                    "message": "未能获取到有效的视频或播放列表元数据。",
                }

            # --- 处理播放列表情况 ---
            if info.get("_type") == "playlist" or "entries" in info:
                raw_entries = info.get("entries") or []
                entries = [entry for entry in raw_entries if entry]
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

            video_opts = sorted(video_opts, key=lambda x: x["height"], reverse=True)
            audio_opts = sorted(audio_opts, key=lambda x: x["abr"], reverse=True)

            # --- 提取字幕信息 ---
            subtitle_opts = []
            manual_subs = info.get("subtitles") or {}
            auto_subs = info.get("automatic_captions") or {}

            for lang, sub_list in manual_subs.items():
                name = lang
                if sub_list and isinstance(sub_list, list) and sub_list[0].get("name"):
                    name = sub_list[0]["name"]
                subtitle_opts.append(
                    {"lang": lang, "desc": f"{name} ({lang})", "auto": False}
                )

            for lang, sub_list in auto_subs.items():
                if lang in manual_subs:
                    continue
                name = lang
                if sub_list and isinstance(sub_list, list) and sub_list[0].get("name"):
                    name = sub_list[0]["name"]
                subtitle_opts.append(
                    {"lang": lang, "desc": f"{name} [{lang}] (自动)", "auto": True}
                )

            subtitle_opts.sort(key=lambda x: (x["auto"], x["lang"]))

            return {
                "status": "success",
                "is_playlist": False,
                "title": title,
                "video_opts": video_opts,
                "audio_opts": audio_opts,
                "subtitle_opts": subtitle_opts,
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": "解析视频信息超时。\n💡 建议：请检查网络连接或代理设置后重试。",
            }
        except Exception as e:
            return {"status": "error", "message": self.format_error_message(e)}

    @staticmethod
    def _parse_num(val: str) -> float | None:
        cleaned = val.strip()
        if not cleaned or cleaned in ("NA", "None", "N/A"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _handle_progress_line(self, payload: str):
        parts = payload.split("|", 5)
        if len(parts) < 6:
            return
        dl_str, tot_str, est_str, speed_str, eta_str, filename = parts

        filename = filename.strip()
        if filename and filename not in ("NA", "None"):
            self._current_filenames.add(filename)

        downloaded = self._parse_num(dl_str) or 0.0
        total = self._parse_num(tot_str) or self._parse_num(est_str) or 1.0
        percent = min(max(downloaded / total, 0.0), 1.0) if total > 0 else 0.0

        speed = speed_str.strip()
        if not speed or speed in ("NA", "None"):
            speed = "N/A"
        eta = eta_str.strip()
        if not eta or eta in ("NA", "None"):
            eta = "N/A"

        if self.progress_callback:
            self.progress_callback(percent, speed, eta)

    def _terminate_process(self, proc: subprocess.Popen):
        if proc.poll() is not None:
            return
        with contextlib.suppress(Exception):
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                proc.kill()

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
        subtitle_auto: bool | None = None,
        is_playlist=False,
        playlist_items=None,
        cleanup_on_cancel=False,
    ):
        """通过系统 yt-dlp 子进程执行下载，支持断点续传、字幕下载与取消控制"""
        if not self._has_valid_ytdlp():
            return {
                "status": "error",
                "message": "未检测到 yt-dlp 下载引擎。\n💡 建议：请点击右上角【⚙️ 依赖配置】一键安装到系统目录或手动指定路径。",
            }

        assert self.ytdlp_location is not None
        self._cancel_event.clear()
        self._current_filenames.clear()

        cmd = [
            self.ytdlp_location,
            "--newline",
            "--color",
            "no_color",
            "--socket-timeout",
            "30",
            "--continue",
            "--progress-template",
            "download:[YDD_PROG]%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress.filename)s",
        ]

        if self.ffmpeg_location and os.path.exists(self.ffmpeg_location):
            cmd.extend(["--ffmpeg-location", self.ffmpeg_location])

        # 存储路径与播放列表参数
        if is_playlist:
            outtmpl = os.path.join(
                output_path,
                "%(playlist_title|Playlist)s",
                "%(playlist_index&{:03d} - |)s%(title)s.%(ext)s",
            )
            cmd.append("--yes-playlist")
            if playlist_items:
                cmd.extend(["--playlist-items", str(playlist_items)])
        else:
            outtmpl = os.path.join(output_path, "%(title)s.%(ext)s")
            cmd.append("--no-playlist")

        cmd.extend(["-o", outtmpl])

        # 构造 format 字符串与纯音频提取判断
        v_id = video_format_id
        a_id = audio_format_id
        audio_only_formats = {"mp3", "m4a", "wav", "flac", "opus"}
        fmt_lower = (format_type or "mp4").lower()
        is_audio_only = (v_id == "none") or (fmt_lower in audio_only_formats)

        if is_audio_only:
            fmt_expr = "bestaudio/best" if a_id in ("best", "none", "") else a_id
        elif a_id == "none":
            fmt_expr = v_id
        else:
            if v_id == "best" and a_id == "best":
                fmt_expr = "bestvideo+bestaudio/best"
            elif v_id == "best":
                fmt_expr = f"bestvideo+{a_id}/best"
            elif a_id == "best":
                fmt_expr = f"{v_id}+bestaudio/best"
            else:
                fmt_expr = f"{v_id}+{a_id}"

        cmd.extend(["-f", fmt_expr])

        # 合并格式或纯音频提取
        if not is_audio_only:
            cmd.extend(["--merge-output-format", fmt_lower])
        else:
            audio_format = fmt_lower if fmt_lower in audio_only_formats else "mp3"
            cmd.extend(
                [
                    "-x",
                    "--audio-format",
                    audio_format,
                    "--audio-quality",
                    "192K" if audio_format == "mp3" else "0",
                ]
            )

        # 字幕配置（精确区分手动字幕与自动生成字幕）
        if subtitle_lang and subtitle_lang != "none":
            if subtitle_auto is True:
                cmd.append("--write-auto-subs")
            elif subtitle_auto is False:
                cmd.append("--write-subs")
            else:
                cmd.extend(["--write-subs", "--write-auto-subs"])

            cmd.extend(
                [
                    "--sub-langs",
                    str(subtitle_lang),
                    "--sub-format",
                    "srt/vtt/best",
                ]
            )
            if subtitle_embed and not is_audio_only:
                cmd.append("--embed-subs")

        if cookiefile and os.path.exists(cookiefile):
            cmd.extend(["--cookies", cookiefile])

        cmd.append(url)

        output_tail: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self._creation_flags(),
            )
            self._current_process = proc

            if proc.stdout:
                for raw_line in proc.stdout:
                    if self._cancel_event.is_set():
                        self._terminate_process(proc)
                        break

                    line = _ANSI_ESCAPE.sub("", raw_line).rstrip("\r\n")
                    if not line:
                        continue

                    if line.startswith("[YDD_PROG]"):
                        self._handle_progress_line(line[len("[YDD_PROG]") :])
                        continue

                    # 记录输出尾部以备错误提取
                    output_tail.append(line)
                    if len(output_tail) > 80:
                        output_tail.pop(0)

                    # 捕获目标文件名，便于取消后清理临时文件
                    dest_match = _DEST_FILE_RE.match(line)
                    if dest_match:
                        self._current_filenames.add(dest_match.group(1).strip())

                    # 捕获合集切集事件
                    item_match = _PLAYLIST_ITEM_RE.search(line)
                    if item_match and self.playlist_item_callback:
                        idx = int(item_match.group(1))
                        total = int(item_match.group(2))
                        self.playlist_item_callback(idx, total, f"第 {idx} 项")

                    if self.log_callback:
                        self.log_callback(line)

            retcode = proc.wait()

            if self._cancel_event.is_set():
                if cleanup_on_cancel:
                    self._cleanup_partial_files(base_dir=output_path)
                elif self.log_callback:
                    self.log_callback(
                        "⏸️ 下载已暂停/取消。保留未完成的 .part 临时文件，支持下次继续下载。"
                    )
                return {"status": "cancelled", "message": "用户已取消下载"}

            if retcode == 0:
                if self.progress_callback:
                    self.progress_callback(1.0, "Done", "0s")
                return {"status": "success"}

            err_text = "\n".join(output_tail) or f"yt-dlp 进程退出码: {retcode}"
            return {"status": "error", "message": self.format_error_message(err_text)}

        except Exception as err:
            if self._cancel_event.is_set():
                if cleanup_on_cancel:
                    self._cleanup_partial_files(base_dir=output_path)
                elif self.log_callback:
                    self.log_callback(
                        "⏸️ 下载已暂停/取消。保留未完成的 .part 临时文件，支持下次继续下载。"
                    )
                return {"status": "cancelled", "message": "用户已取消下载"}
            return {"status": "error", "message": self.format_error_message(err)}
        finally:
            self._current_process = None

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
        """清理下载一半产生的残留文件（如取消且用户选择彻底清理时）"""
        for f in list(self._current_filenames):
            for ext in ["", ".part", ".ytdl"]:
                path = f + ext
                if path.endswith(".part.part"):
                    continue

                if os.path.exists(path):
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
        """取消当前正在进行的下载任务并立即终止子进程"""
        self._cancel_event.set()
        proc = self._current_process
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
