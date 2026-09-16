"""官方媒体播放列表元数据采集；不下载视频、字幕或缩略图。"""

from __future__ import annotations

import hashlib
import json

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.utils.request_helper import sanitize_public_url


class OfficialMediaPlaylistL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "media_extractor_metadata"

    def collect(self) -> RawRecord:
        if self.task.get("download_video", False):
            raise ValueError("播放列表采集器禁止下载视频")
        media = self.task.get("media", {})
        if media.get("official_channel_asserted") is not True:
            raise ValueError("必须显式确认来源为官方频道")
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise RuntimeError("需要安装 yt-dlp") from exc
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": int(media.get("max_entries", 1000)),
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(self.task["url"], download=False)
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp 未返回播放列表元数据")
        entries = []
        for item in info.get("entries") or []:
            if not isinstance(item, dict):
                continue
            entries.append({
                key: item.get(key) for key in (
                    "id", "title", "url", "webpage_url", "duration", "channel",
                    "channel_id", "uploader", "uploader_id", "timestamp", "upload_date"
                ) if item.get(key) is not None
            })
        payload = {
            "id": info.get("id"),
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "channel_id": info.get("channel_id") or info.get("uploader_id"),
            "webpage_url": sanitize_public_url(str(info.get("webpage_url") or self.task["url"])),
            "entry_count": len(entries),
            "entries": entries,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        encoded = raw.encode("utf-8")
        return self.make_record(
            url=payload["webpage_url"],
            raw_content=raw,
            extra_meta={
                "media_type": "application/json",
                "content_encoding": "utf-8",
                "content_length_bytes": len(encoded),
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "playlist_entry_count": len(entries),
                "acquisition_method": "yt_dlp_public_playlist_metadata",
                "derived_snapshot": True,
                "note": "公开官方频道播放列表元数据快照；未下载视频、字幕或缩略图",
            },
        )
