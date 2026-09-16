"""第三方转录/搬运文档采集器；trust_level 永久固定为 11。"""

from __future__ import annotations

import base64
import hashlib

from .base_collector import BaseCollector, RawRecord, TRUST_L1_DERIVED
from src.utils.http_archive import archive_http_response
from src.utils.http_cache import NotModifiedError, validator_store
from src.utils.request_helper import RequestHelper, safe_response_headers
from src.utils.robots_policy import assert_robots_allowed


DERIVED_DOCUMENT_NOTE = "第三方文档副本，必须与L1原件交叉验证"


class DerivedDocumentCollector(BaseCollector):
    trust_level = TRUST_L1_DERIVED
    source_type = "derived_transcription"

    def collect(self) -> RawRecord:
        http = self.task.get("http", {})
        helper = RequestHelper(
            timeout=float(http.get("timeout", 60)),
            retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 1.0)),
            headers=http.get("headers"),
        )
        requested_url = self.task["url"]
        assert_robots_allowed(
            helper, requested_url,
            self.task.get("robots_user_agent", "IP-Source-Collector"),
            self.task.get("robots_on_error", "deny"),
        )
        store = validator_store(self.project_root, self.task)
        conditional = {} if self.task.get("force_refresh") else store.request_headers(
            self.task["source_key"], requested_url
        )
        response = helper.get(requested_url, headers=conditional)
        if response.status_code == 304:
            raise NotModifiedError(f"未变化: {requested_url}")
        store.update(self.task["source_key"], requested_url, response)
        archive_meta = archive_http_response(self.project_root, self.task, response)
        content = response.content
        max_bytes = int(self.task.get("max_bytes", 100 * 1024 * 1024))
        if len(content) > max_bytes:
            raise ValueError(f"文件大小 {len(content)} 超过任务上限 {max_bytes} 字节")
        return self.make_record(
            url=response.url,
            raw_content=base64.b64encode(content).decode("ascii"),
            extra_meta={
                "http_status": response.status_code,
                "response_headers": safe_response_headers(response),
                "media_type": response.headers.get("Content-Type", "application/octet-stream"),
                "content_encoding": "base64",
                "content_length_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "acquisition_method": "http_get",
                "note": DERIVED_DOCUMENT_NOTE,
                **archive_meta,
            },
        )
