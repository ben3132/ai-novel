"""MediaWiki API 参考 Wiki（L2）原始采集器。

通过站点公开的 MediaWiki API（/api.php, action=parse）获取词条渲染正文 HTML，
逐词条一条原始记录；适用于 Fandom 等有引用规范的参考 Wiki。

- 与 official_api_l1_collector 一致，走站点公开 API 端点时不做 robots.txt 双重限制
  （API 即站点服务条款公开提供的数据接口；HTML 页面级抓取请用 l2_web/l3_web）。
- 网络代理等可经 task.http.proxies 配置（按需传入 RequestHelper）。
- source_type 沿用 reference_web_page；trust_level 由子类硬编码，禁止配置抬级。
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from typing import Dict, Any, Iterator

from .base_collector import BaseCollector, RawRecord, TRUST_L2
from src.utils.request_helper import RequestHelper

_WRAP_HTML = """<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8"><title>{title}</title></head><body>{body}</body></html>"""


def _wrap_html(body_html: str, title: str) -> str:
    t = re.sub(r"[^A-Za-z0-9 _-]", "", title)
    return _WRAP_HTML.format(title=t, body=body_html)


class _ReferenceWikiApiCollector(BaseCollector):
    """媒体Wiki API 参考词条采集基类。任务字段：

    mediawiki:
      api: "https://<host>/api.php"      # 必填
      pages: ["Title A", "Title B"]      # pages 与 category 二选一
      category: "Category:Transcripts"   # 可选：从分类拉全部成员标题（分页遍历）
      title_prefix: "Transcript:"        # 可选：分类模式下按前缀过滤标题
    http: 可选，透传 RequestHelper 的 timeout/retries/headers/proxies
    """

    source_type = "reference_web_page"

    def _helper(self) -> RequestHelper:
        http = self.task.get("http", {})
        return RequestHelper(
            timeout=float(http.get("timeout", 20)),
            retries=int(http.get("retries", 3)),
            backoff_factor=float(http.get("backoff_factor", 0.8)),
            delay_seconds=float(http.get("delay_seconds", 1.0)),
            headers=http.get("headers"),
        )

    def _category_titles(self, helper: RequestHelper, api: str, category: str,
                         title_prefix: str | None = None) -> list[str]:
        """categorymembers 分页拉取分类成员标题（仅页面 ns=0）。"""
        proxies = self.task.get("http", {}).get("proxies") or self.task.get("proxies")
        titles: list[str] = []
        cont: str | None = None
        cat = category if category.startswith("Category:") else f"Category:{category}"
        for _page in range(40):  # 40*500=20000 上限保护
            params: Dict[str, Any] = {"action": "query", "list": "categorymembers",
                                      "cmtitle": cat, "cmlimit": "500", "cmnamespace": 0,
                                      "format": "json", "formatversion": 2}
            if cont:
                params["cmcontinue"] = cont
            resp = helper.request("GET", api, params=params, proxies=proxies, timeout=30)
            data = resp.json()
            members = data.get("query", {}).get("categorymembers", [])
            titles.extend(m.get("title", "") for m in members)
            cont = data.get("continue", {}).get("cmcontinue")
            if not cont:
                break
        if title_prefix:
            titles = [t for t in titles if t.startswith(title_prefix)]
        return titles

    def _fetch_page(self, helper: RequestHelper, api: str, title: str) -> str | None:
        proxies = self.task.get("http", {}).get("proxies") or self.task.get("proxies")
        params = {"action": "parse", "page": title, "prop": "text",
                  "format": "json", "formatversion": 2}
        for attempt in range(3):
            try:
                response = helper.request("GET", api, params=params, proxies=proxies,
                                          timeout=25)
                parsed = response.json().get("parse")
                if parsed and parsed.get("text"):
                    return parsed["text"]
                print(f"  [warn] {title}: parse 返回空", file=sys.stderr)
                return None
            except Exception as exc:  # noqa: BLE001 - 网络/解析错误均重试
                if attempt == 2:
                    print(f"  [FAIL] {title}: {type(exc).__name__} {str(exc)[:140]}", file=sys.stderr)
                    return None
                time.sleep(1.5 * (attempt + 1))
        return None

    def collect(self) -> RawRecord:
        # 词条采集是批量语义（一 task 多页一文件）；单条接口不适用。
        raise NotImplementedError(
            "reference_wiki_api_l2 为多词条批量采集器，请使用 collect_many（run_l1_collect 默认路径）"
        )

    def collect_many(self) -> Iterator[RawRecord]:
        mw = self.task.get("mediawiki", {})
        api = mw.get("api", "")
        pages: list[str] = list(mw.get("pages", []))
        category = mw.get("category")
        if category:
            fetched = self._category_titles(self._helper(), api, category,
                                            mw.get("title_prefix"))
            print(f"  [category] {category}: {len(fetched)} titles")
            pages.extend(t for t in fetched if t not in pages)
        if not api or not pages:
            raise ValueError("mediawiki.api 与 (mediawiki.pages | mediawiki.category) 必须提供")
        helper = self._helper()
        ok = 0
        for title in pages:
            body = self._fetch_page(helper, api, title)
            if body is None:
                continue
            page_url = api.replace("/api.php", "") + "/wiki/" + title.replace(" ", "_")
            full = _wrap_html(body, title)
            record = self.make_record(
                url=page_url,
                raw_content=full,
                extra_meta={
                    "content_length_bytes": len(full.encode("utf-8")),
                    "content_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
                    "media_type": "text/html",
                    "content_encoding": "utf-8",
                    "acquisition_method": "mediawiki_api_parse",
                    "api_endpoint": api,
                    "page_title": title,
                    "note": "参考 Wiki MediaWiki API 词条正文；L2 社区整理，关键结论须回查原作",
                },
            )
            yield record
            ok += 1
            time.sleep(float(self.task.get("http", {}).get("delay_seconds", 1.0)))
        if ok == 0:
            raise RuntimeError(f"采集器未获取到任何词条正文 (api={api})")


class ReferenceWikiApiL2Collector(_ReferenceWikiApiCollector):
    """L2：有引用规范的参考 Wiki（如 Fandom）经公开 MediaWiki API 采集。"""

    trust_level = TRUST_L2


class ReferenceTranscriptApiCollector(_ReferenceWikiApiCollector):
    """trust 11：社区转录的台词/剧本页（如 Fandom Category:Transcripts）。

    本质是第三方对播出内容的逐句转录（derived transcription），
    定级 11 而非 L2；设定类结论仍须 L1/L2 佐证后引用。
    """

    source_type = "derived_transcription"
    trust_level = 11
