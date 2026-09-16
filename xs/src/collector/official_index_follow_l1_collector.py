"""官方 JSON 索引跟随采集器：仅用索引中的 ID 发现详情 URL，原样保存所有响应。"""

from __future__ import annotations

import hashlib
import json
from typing import Iterator

import requests

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.utils.http_archive import archive_http_response
from src.utils.request_helper import RequestHelper, response_text_and_encoding, safe_response_headers
from src.utils.robots_policy import assert_robots_allowed


class OfficialIndexFollowL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "official_api_response"

    def collect(self) -> RawRecord:
        return next(self.collect_many())

    def collect_many(self) -> Iterator[RawRecord]:
        http = self.task.get("http", {})
        helper = RequestHelper(
            timeout=float(http.get("timeout", 20)),
            retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 0.6)),
            headers=http.get("headers"),
        )
        indexes = self.task.get("indexes", [])
        if not indexes:
            raise ValueError("indexes 不能为空")
        max_items = int(self.task.get("max_items", 1000))
        seen_urls: set[str] = set()

        for index in indexes:
            index_url = index["url"]
            assert_robots_allowed(
                helper, index_url,
                self.task.get("robots_user_agent", "IPSourceResearchBot"),
                self.task.get("robots_on_error", "deny"),
            )
            response = helper.get(index_url)
            raw, encoding = response_text_and_encoding(response)
            yield self._record(response, raw, encoding, "official_api_response", {
                "acquisition_method": "official_json_index",
                "index_kind": index.get("kind"),
            })
            payload = json.loads(raw)
            items = payload.get("data", {}).get("list", [])
            template = index["detail_url_template"]
            for item in items[:max_items]:
                item_id = str(item["id"])
                detail_url = template.format(id=item_id)
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                try:
                    detail = helper.get(detail_url)
                except requests.HTTPError as exc:
                    detail = exc.response
                    if detail is None or detail.status_code not in {404, 410}:
                        raise
                detail_raw, detail_encoding = response_text_and_encoding(detail)
                yield self._record(detail, detail_raw, detail_encoding, "official_web_html", {
                    "acquisition_method": (
                        "official_index_follow_missing"
                        if detail.status_code in {404, 410}
                        else "official_index_follow"
                    ),
                    "index_kind": index.get("kind"),
                    "discovered_item_id": item_id,
                    "discovered_title": item.get("title"),
                    "discovered_from": index_url,
                })

    def _record(self, response, raw: str, encoding: str, source_type: str, meta: dict) -> RawRecord:
        archive_meta = archive_http_response(self.project_root, self.task, response)
        return self.make_record(
            url=response.url,
            raw_content=raw,
            source_type=source_type,
            extra_meta={
                "http_status": response.status_code,
                "response_headers": safe_response_headers(response),
                "media_type": response.headers.get("Content-Type", ""),
                "content_encoding": encoding,
                "transport_reported_encoding": response.encoding,
                "content_length_bytes": len(response.content),
                "content_sha256": hashlib.sha256(response.content).hexdigest(),
                **meta,
                **archive_meta,
            },
        )
