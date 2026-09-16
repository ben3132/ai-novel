"""L2/L3/L4 参考网页原始采集器；等级由不同类硬编码，禁止配置抬级。"""

import hashlib

from .base_collector import BaseCollector, RawRecord, TRUST_L2, TRUST_L3, TRUST_L4
from src.utils.http_archive import archive_http_response
from src.utils.request_helper import RequestHelper, response_text_and_encoding, safe_response_headers
from src.utils.robots_policy import assert_robots_allowed


class _ReferenceWebCollector(BaseCollector):
    source_type = "reference_web_page"

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
            helper, self.task["url"],
            self.task.get("robots_user_agent", "IP-Source-Collector"),
            self.task.get("robots_on_error", "deny"),
        )
        response = helper.get(self.task["url"])
        raw_content, storage_encoding = response_text_and_encoding(response)
        archive_meta = archive_http_response(self.project_root, self.task, response)
        notes = {
            2: "权威粉丝Wiki/百科整理，仅作二级参考，关键结论须回查原作",
            3: "二次整理社区内容，仅作线索，不可单独证明设定",
            4: "低可信度内容，只收录不参与设定推理",
        }
        return self.make_record(
            url=response.url,
            raw_content=raw_content,
            extra_meta={
                "status_code": response.status_code,
                "response_headers": safe_response_headers(response),
                "content_length_bytes": len(response.content),
                "content_sha256": hashlib.sha256(response.content).hexdigest(),
                "media_type": response.headers.get("Content-Type", ""),
                "content_encoding": storage_encoding,
                "transport_reported_encoding": response.encoding,
                "acquisition_method": "http_get",
                "note": notes[self.trust_level],
                **archive_meta,
            },
        )


class L2WebCollector(_ReferenceWebCollector):
    trust_level = TRUST_L2


class L3WebCollector(_ReferenceWebCollector):
    trust_level = TRUST_L3


class L4WebCollector(_ReferenceWebCollector):
    trust_level = TRUST_L4
