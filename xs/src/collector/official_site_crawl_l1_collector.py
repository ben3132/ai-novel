"""官方静态站点限定域爬取：只发现链接并保存每页原始 HTML，不提取正文。"""

from __future__ import annotations

import hashlib
from collections import deque
from html.parser import HTMLParser
from typing import Iterator, List, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.utils.http_archive import archive_http_response
from src.utils.request_helper import RequestHelper, safe_response_headers, response_text_and_encoding
from src.utils.robots_policy import assert_robots_allowed


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


class OfficialSiteCrawlL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "official_web_html"

    def _helper(self) -> RequestHelper:
        http = self.task.get("http", {})
        return RequestHelper(
            timeout=float(http.get("timeout", 20)), retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 1.0)), headers=http.get("headers"),
            max_redirects=int(http.get("max_redirects", 10)),
        )

    def _allowed(self, url: str, domains: Set[str], prefixes: Tuple[str, ...]) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in domains:
            return False
        return not prefixes or any(parsed.path.startswith(prefix) for prefix in prefixes)

    def _record(self, response, depth: int, discovered_from: str | None) -> RawRecord:
        content = response.content
        raw_content, storage_encoding = response_text_and_encoding(response)
        archive_meta = archive_http_response(self.project_root, self.task, response)
        return self.make_record(
            url=response.url,
            raw_content=raw_content,
            extra_meta={
                "http_status": response.status_code,
                "response_headers": safe_response_headers(response),
                "media_type": response.headers.get("Content-Type", ""),
                "content_encoding": storage_encoding,
                "transport_reported_encoding": response.encoding,
                "content_length_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "acquisition_method": "limited_domain_crawl",
                "crawl_depth": depth,
                "discovered_from": discovered_from,
                **archive_meta,
            },
        )

    def collect(self) -> RawRecord:
        return next(self.collect_many())

    def collect_many(self) -> Iterator[RawRecord]:
        seed = self.task["url"]
        crawl = self.task.get("crawl", {})
        max_pages = int(crawl.get("max_pages", 20))
        max_depth = int(crawl.get("max_depth", 2))
        if max_pages < 1 or max_depth < 0:
            raise ValueError("crawl.max_pages 必须大于0，max_depth不得小于0")
        seed_host = urlparse(seed).hostname
        domains = set(crawl.get("allowed_domains", [seed_host]))
        if not seed_host or seed_host not in domains:
            raise ValueError("seed URL域名必须包含在 crawl.allowed_domains")
        prefixes = tuple(crawl.get("allowed_path_prefixes", []))
        user_agent = crawl.get("robots_user_agent", "IP-Source-L1-Collector")
        helper = self._helper()
        assert_robots_allowed(
            helper, seed, user_agent, self.task.get("robots_on_error", "deny")
        )

        queue = deque([(urldefrag(seed).url, 0, None)])
        visited: Set[str] = set()
        while queue and len(visited) < max_pages:
            url, depth, parent = queue.popleft()
            if url in visited or not self._allowed(url, domains, prefixes):
                continue
            assert_robots_allowed(
                helper, url, user_agent, self.task.get("robots_on_error", "deny")
            )
            response = helper.get(url)
            final_host = urlparse(response.url).hostname
            if final_host not in domains:
                raise RuntimeError(f"重定向越出允许域名: {response.url}")
            visited.add(url)
            yield self._record(response, depth, parent)
            if depth >= max_depth or "html" not in response.headers.get("Content-Type", "").lower():
                continue
            parser = _LinkParser()
            navigation_text, navigation_encoding = response_text_and_encoding(response)
            if navigation_encoding == "base64":
                continue
            parser.feed(navigation_text)
            for href in parser.links:
                candidate = urldefrag(urljoin(response.url, href)).url
                if candidate not in visited and self._allowed(candidate, domains, prefixes):
                    queue.append((candidate, depth + 1, response.url))
