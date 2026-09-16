"""官方 API 原始响应采集器：支持认证与分页，每个 HTTP 响应独立成一条记录。"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlencode

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.api import ApiClient
from src.utils.request_helper import (
    RequestHelper, redirect_chain, safe_response_headers, response_text_and_encoding,
)
from src.utils.http_cache import NotModifiedError, validator_store
from src.utils.http_archive import archive_http_response


class OfficialApiL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "official_api_response"

    def _helper(self) -> RequestHelper:
        http = self.task.get("http", {})
        return RequestHelper(
            timeout=float(http.get("timeout", 20)), retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 0)), headers=http.get("headers"),
            max_redirects=int(http.get("max_redirects", 10)),
        )

    def _request(
        self,
        helper: RequestHelper,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ):
        http = self.task.get("http", {})
        method = str(self.task.get("method", "GET")).upper()
        if method not in {"GET", "POST"}:
            raise ValueError("official_api_l1 当前只允许 GET 或 POST")
        store = validator_store(self.project_root, self.task)
        cache_url = url
        if params:
            cache_url = f"{url}{'&' if '?' in url else '?'}{urlencode(params, doseq=True)}"
        conditional = (
            store.request_headers(self.task["source_key"], cache_url)
            if method == "GET" and not self.task.get("force_refresh") else {}
        )
        kwargs: Dict[str, Any] = {"params": params or {}, "headers": conditional}
        if method == "POST":
            if "json_body" in self.task:
                kwargs["json"] = self.task["json_body"]
            elif "form_body" in self.task:
                kwargs["data"] = self.task["form_body"]
        response = ApiClient(helper, http.get("auth")).request(method, url, **kwargs)
        if response.status_code == 304:
            raise NotModifiedError(f"未变化: {cache_url}")
        if method == "GET":
            store.update(self.task["source_key"], cache_url, response)
        return response

    def _record(self, response, page_index: int) -> RawRecord:
        archive_meta = archive_http_response(self.project_root, self.task, response)
        raw_content, storage_encoding = response_text_and_encoding(response)
        return self.make_record(
            url=response.url,
            raw_content=raw_content,
            extra_meta={
                "http_method": response.request.method,
                "http_status": response.status_code,
                "response_headers": safe_response_headers(response),
                "redirect_chain": redirect_chain(response),
                "media_type": response.headers.get("Content-Type", ""),
                "content_encoding": storage_encoding,
                "transport_reported_encoding": response.encoding,
                "content_length_bytes": len(response.content),
                "content_sha256": hashlib.sha256(response.content).hexdigest(),
                "acquisition_method": "http_api",
                "page_index": page_index,
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "rate_limit_remaining": response.headers.get("X-Rate-Limit-Remaining"),
                "rate_limit_reset": response.headers.get("X-Rate-Limit-Reset"),
                **archive_meta,
            },
        )

    def collect(self) -> RawRecord:
        helper = self._helper()
        response = self._request(helper, self.task["url"], self.task.get("params"))
        return self._record(response, 1)

    def collect_many(self) -> Iterator[RawRecord]:
        helper = self._helper()
        pagination = self.task.get("pagination")
        if not pagination:
            yield self._record(self._request(helper, self.task["url"], self.task.get("params")), 1)
            return

        mode = pagination.get("mode")
        max_pages = int(pagination.get("max_pages", 1))
        if max_pages < 1:
            raise ValueError("pagination.max_pages 必须大于 0")
        if mode == "page_param":
            param_name = pagination.get("param", "page")
            start = int(pagination.get("start", 1))
            step = int(pagination.get("step", 1))
            for index in range(max_pages):
                params = {**self.task.get("params", {}), param_name: start + index * step}
                yield self._record(self._request(helper, self.task["url"], params), index + 1)
            return
        if mode == "link_header":
            next_url: Optional[str] = self.task["url"]
            params = self.task.get("params")
            for index in range(max_pages):
                if not next_url:
                    break
                response = self._request(helper, next_url, params)
                yield self._record(response, index + 1)
                next_url = response.links.get("next", {}).get("url")
                params = None
            return
        raise ValueError("pagination.mode 只能是 page_param 或 link_header")
