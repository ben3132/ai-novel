"""官方 JavaScript 页面采集器：捕获允许域内网络响应与渲染 DOM，不做正文提取。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Set
from urllib.parse import urlparse

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.utils.http_archive import archive_http_response
from src.utils.request_helper import RequestHelper, safe_response_headers, sanitize_public_url
from src.utils.robots_policy import assert_robots_allowed


class DynamicWebL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "browser_network_response"

    def _allowed(self, url: str, domains: Set[str]) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.hostname in domains

    def _check_robots(self, url: str, user_agent: str) -> None:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        http = self.task.get("http", {})
        helper = RequestHelper(
            timeout=float(http.get("timeout", 20)), retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            headers=http.get("headers"),
        )
        assert_robots_allowed(
            helper, url, user_agent, self.task.get("robots_on_error", "deny")
        )

    @staticmethod
    def _response_adapter(item: Dict[str, Any]) -> Any:
        return SimpleNamespace(
            status=item["status"],
            status_code=item["status"],
            reason=item.get("status_text", ""),
            url=sanitize_public_url(item["url"]),
            content=item["body"],
            headers=item["headers"],
            encoding=None,
            history=[],
            raw=None,
            request=SimpleNamespace(method=item["method"]),
        )

    def _network_record(self, item: Dict[str, Any], index: int) -> RawRecord:
        adapter = self._response_adapter(item)
        archive_meta = archive_http_response(self.project_root, self.task, adapter)
        content = item["body"]
        # HTTP文本按响应 charset 解码；未知或二进制响应使用 Base64，保持逐字节可逆。
        content_type = item["headers"].get("content-type", "")
        is_text = any(token in content_type.lower() for token in ("text/", "json", "xml", "javascript"))
        if is_text:
            encoding = "utf-8"
            marker = "charset="
            if marker in content_type.lower():
                encoding = content_type.lower().split(marker, 1)[1].split(";", 1)[0].strip()
            try:
                raw_content = content.decode(encoding, errors="strict")
                content_encoding = encoding
            except (LookupError, UnicodeDecodeError):
                import base64
                raw_content = base64.b64encode(content).decode("ascii")
                content_encoding = "base64"
        else:
            import base64
            raw_content = base64.b64encode(content).decode("ascii")
            content_encoding = "base64"
        return self.make_record(
            url=sanitize_public_url(item["url"]),
            raw_content=raw_content,
            extra_meta={
                "browser_resource_type": item["resource_type"],
                "http_method": item["method"],
                "http_status": item["status"],
                "response_headers": safe_response_headers(adapter),
                "media_type": content_type,
                "content_encoding": content_encoding,
                "content_length_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "acquisition_method": "playwright_network_capture",
                "browser_response_index": index,
                **archive_meta,
            },
        )

    def collect(self) -> RawRecord:
        return next(self.collect_many())

    def collect_many(self) -> Iterator[RawRecord]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("动态页面采集需要安装 playwright 和 Chromium") from exc

        url = self.task["url"]
        browser_config = self.task.get("browser", {})
        domains = set(browser_config.get("allowed_domains", [urlparse(url).hostname]))
        if urlparse(url).hostname not in domains:
            raise ValueError("入口 URL域名必须包含在 browser.allowed_domains")
        user_agent = browser_config.get("user_agent", "IP-Source-L1-Collector")
        self._check_robots(url, user_agent)
        capture_types = set(browser_config.get("capture_resource_types", ["document", "xhr", "fetch"] ))
        max_responses = int(browser_config.get("max_responses", 100))
        timeout_ms = int(browser_config.get("timeout_ms", 30000))
        wait_after_ms = int(browser_config.get("wait_after_ms", 2000))
        captured: List[Dict[str, Any]] = []

        with sync_playwright() as playwright:
            launch_options: Dict[str, Any] = {"headless": True}
            if browser_config.get("channel"):
                launch_options["channel"] = browser_config["channel"]
            if browser_config.get("executable_path"):
                launch_options["executable_path"] = browser_config["executable_path"]
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()

            def on_response(response) -> None:
                if len(captured) >= max_responses:
                    return
                request = response.request
                if request.resource_type not in capture_types or not self._allowed(response.url, domains):
                    return
                try:
                    body = response.body()
                except Exception:
                    return
                captured.append({
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "headers": dict(response.headers),
                    "body": body,
                    "method": request.method,
                    "resource_type": request.resource_type,
                })

            page.on("response", on_response)
            page.goto(url, wait_until=browser_config.get("wait_until", "networkidle"), timeout=timeout_ms)
            if wait_after_ms > 0:
                page.wait_for_timeout(wait_after_ms)
            rendered_url = page.url
            rendered_dom = page.content()
            browser.close()

        for index, item in enumerate(captured, start=1):
            yield self._network_record(item, index)

        # DOM 是浏览器执行脚本后的派生快照，因此单独标型，绝不冒充原始 HTTP 响应。
        dom_bytes = rendered_dom.encode("utf-8")
        yield self.make_record(
                url=rendered_url,
                raw_content=rendered_dom,
                source_type="browser_rendered_dom",
                extra_meta={
                    "media_type": "text/html; charset=utf-8",
                    "content_encoding": "utf-8",
                    "content_length_bytes": len(dom_bytes),
                    "content_sha256": hashlib.sha256(dom_bytes).hexdigest(),
                    "acquisition_method": "playwright_rendered_dom",
                    "derived_snapshot": True,
                    "note": "浏览器执行脚本后的DOM快照，不是原始HTTP响应",
                },
            )
