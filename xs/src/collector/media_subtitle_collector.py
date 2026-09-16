"""公开媒体字幕采集：yt-dlp只发现公开字幕，不下载视频、不使用登录态或绕过 DRM。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterator, List, Mapping, Sequence

from .base_collector import BaseCollector, RawRecord, TRUST_L1, TRUST_L1_DERIVED
from src.utils.http_archive import archive_http_response
from src.utils.request_helper import (
    RequestHelper,
    safe_response_headers,
    sanitize_public_url,
)


SAFE_INFO_FIELDS = (
    "id", "title", "uploader", "uploader_id", "channel", "channel_id",
    "webpage_url", "original_url", "duration", "timestamp", "upload_date",
    "release_timestamp", "release_date", "series", "season", "season_number",
    "episode", "episode_number", "language", "extractor", "extractor_key",
)


class _MediaSubtitleBase(BaseCollector):
    source_type = "official_media_subtitle"

    def _validate_policy(self) -> None:
        if self.task.get("download_video", False):
            raise ValueError("媒体字幕采集器禁止下载视频；download_video 必须为 false")
        forbidden = {"cookies", "cookiefile", "cookiesfrombrowser", "username", "password"}
        configured = forbidden.intersection(self.task.get("yt_dlp", {}))
        if configured:
            raise ValueError(f"当前阶段禁止登录态/凭据选项: {', '.join(sorted(configured))}")

    @staticmethod
    def _select_tracks(
        subtitles: Mapping[str, Sequence[Mapping[str, Any]]],
        languages: Sequence[str],
        preferred_formats: Sequence[str],
        all_formats: bool,
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        available_languages = list(subtitles)
        requested = available_languages if "all" in languages else languages
        for language in requested:
            candidates = [dict(item) for item in subtitles.get(language, []) if item.get("url")]
            if not candidates:
                continue
            if all_formats:
                result.extend({**item, "language": language} for item in candidates)
                continue
            selected = None
            for extension in preferred_formats:
                selected = next((item for item in candidates if item.get("ext") == extension), None)
                if selected:
                    break
            selected = selected or candidates[-1]
            result.append({**selected, "language": language})
        return result

    @staticmethod
    def _safe_metadata(info: Mapping[str, Any]) -> Dict[str, Any]:
        metadata = {key: info.get(key) for key in SAFE_INFO_FIELDS if info.get(key) is not None}
        for key in ("webpage_url", "original_url"):
            if key in metadata:
                metadata[key] = sanitize_public_url(str(metadata[key]))
        return metadata

    def collect(self) -> RawRecord:
        return next(self.collect_many())

    def collect_many(self) -> Iterator[RawRecord]:
        self._validate_policy()
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise RuntimeError("字幕采集需要安装 requirements-l1.txt 中的 yt-dlp") from exc

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": bool(self.task.get("noplaylist", True)),
            "extract_flat": False,
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(self.task["url"], download=False)
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp 未返回媒体元数据")

        media = self.task.get("media", {})
        include_automatic = bool(media.get("include_automatic_captions", False))
        if self.trust_level == TRUST_L1 and include_automatic:
            raise ValueError("自动字幕不能作为 L1；请使用 L1-derived任务并固定 trust_level=11")
        subtitle_map: Dict[str, Any] = dict(info.get("subtitles") or {})
        if include_automatic:
            for language, tracks in (info.get("automatic_captions") or {}).items():
                subtitle_map.setdefault(language, []).extend(tracks)

        languages = list(media.get("languages", ["all"]))
        preferred = list(media.get("preferred_formats", ["vtt", "srt", "ttml", "json3"] ))
        tracks = self._select_tracks(
            subtitle_map, languages, preferred, bool(media.get("download_all_formats", False))
        )
        if not tracks:
            raise RuntimeError("没有找到符合配置的公开字幕轨道")

        safe_metadata = self._safe_metadata(info)
        metadata_text = json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":"))
        yield self.make_record(
            url=sanitize_public_url(str(info.get("webpage_url") or self.task["url"])),
            raw_content=metadata_text,
            source_type="media_extractor_metadata",
            extra_meta={
                "media_type": "application/json",
                "content_encoding": "utf-8",
                "content_length_bytes": len(metadata_text.encode("utf-8")),
                "content_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
                "acquisition_method": "yt_dlp_public_metadata",
                "derived_snapshot": True,
                "note": "yt-dlp提取的公开媒体元数据快照，不是平台原始API响应",
            },
        )

        http = self.task.get("http", {})
        helper = RequestHelper(
            timeout=float(http.get("timeout", 30)), retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 0)), headers=http.get("headers"),
        )
        for index, track in enumerate(tracks, start=1):
            track_headers = {
                name: value for name, value in dict(track.get("http_headers") or {}).items()
                if name.lower() not in {"authorization", "cookie", "proxy-authorization"}
            }
            response = helper.get(track["url"], headers=track_headers)
            response.url = sanitize_public_url(response.url)
            content = response.content
            encoding = response.encoding or "utf-8"
            try:
                raw_content = content.decode(encoding, errors="strict")
                content_encoding = encoding
            except (LookupError, UnicodeDecodeError):
                import base64
                raw_content = base64.b64encode(content).decode("ascii")
                content_encoding = "base64"
            archive_meta = archive_http_response(self.project_root, self.task, response)
            yield self.make_record(
                url=response.url,
                raw_content=raw_content,
                extra_meta={
                    "media_id": safe_metadata.get("id"),
                    "media_title": safe_metadata.get("title"),
                    "uploader": safe_metadata.get("uploader") or safe_metadata.get("channel"),
                    "subtitle_language": track["language"],
                    "subtitle_format": track.get("ext"),
                    "subtitle_track_index": index,
                    "subtitle_origin": media.get("subtitle_origin", "unknown"),
                    "automatic_caption": include_automatic,
                    "http_status": response.status_code,
                    "response_headers": safe_response_headers(response),
                    "media_type": response.headers.get("Content-Type", "text/plain"),
                    "content_encoding": content_encoding,
                    "content_length_bytes": len(content),
                    "content_sha256": hashlib.sha256(content).hexdigest(),
                    "acquisition_method": "yt_dlp_subtitle_download",
                    **archive_meta,
                },
            )


class OfficialMediaSubtitleL1Collector(_MediaSubtitleBase):
    trust_level = TRUST_L1

    def _validate_policy(self) -> None:
        super()._validate_policy()
        media = self.task.get("media", {})
        if media.get("official_channel_asserted") is not True:
            raise ValueError("L1媒体字幕任务必须显式设置 official_channel_asserted: true")
        if media.get("subtitle_origin") != "official":
            raise ValueError("L1媒体字幕任务的 subtitle_origin 必须为 official")


class DerivedMediaSubtitleCollector(_MediaSubtitleBase):
    trust_level = TRUST_L1_DERIVED
    source_type = "derived_transcription"

    def make_record(self, **kwargs: Any) -> RawRecord:
        extra_meta = kwargs.setdefault("extra_meta", {})
        extra_meta["note"] = "第三方转录副本，必须L1原件交叉验证"
        return super().make_record(**kwargs)
