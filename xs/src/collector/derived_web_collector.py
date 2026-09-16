"""第三方转录/搬运网页原始 HTML 采集器（L1-derived，强制 trust_level=11）。"""

import hashlib

from .base_collector import BaseCollector, RawRecord, TRUST_L1_DERIVED
from src.utils.request_helper import RequestHelper, safe_response_headers, response_text_and_encoding
from src.utils.http_archive import archive_http_response
from src.utils.robots_policy import assert_robots_allowed


class DerivedWebCollector(BaseCollector):
    # 安全边界：此值硬编码，不允许配置覆盖；第三方内容绝不可成为 L1 证据原件。
    trust_level = TRUST_L1_DERIVED
    source_type = "derived_transcription"

    def collect(self) -> RawRecord:
        http = self.task.get("http", {})
        helper = RequestHelper(
            timeout=float(http.get("timeout", 20)),
            retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 1.0)),
            headers=http.get("headers"),
        )
        assert_robots_allowed(
            helper,
            self.task["url"],
            self.task.get("robots_user_agent", "IP-Source-L1-Collector"),
            self.task.get("robots_on_error", "deny"),
        )
        response = helper.get(self.task["url"])
        archive_meta = archive_http_response(self.project_root, self.task, response)
        raw_content, storage_encoding = response_text_and_encoding(response)
        return self.make_record(
            url=response.url,
            raw_content=raw_content,
            extra_meta={
                "status_code": response.status_code,
                "response_headers": safe_response_headers(response),
                "encoding": response.encoding,
                "content_length_bytes": len(response.content),
                "content_sha256": hashlib.sha256(response.content).hexdigest(),
                "media_type": response.headers.get("Content-Type", ""),
                "content_encoding": storage_encoding,
                "transport_reported_encoding": response.encoding,
                "acquisition_method": "http_get",
                "note": "第三方转录副本，必须L1原件交叉验证",
                **archive_meta,
            },
        )
