"""联网补全（enrich）：世界设定低置信度核对。

规则（对应规格）：提取 world_settings 时，若 confidence_score < 0.7
且 category 命中 地理/历史/文化，调用搜索 API 补全，source 标记为 'enriched'。

⚠️ 本模块为示例占位：默认对接 Tavily Search API（结构完整），
未配置 SEARCH_API_KEY 或调用失败时原样返回（不中断 ETL）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request

from .config import get_settings
from .schemas import ENRICH_CATEGORY_KEYWORDS, WorldSetting

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7
ENRICHED_SOURCE = "enriched"
ENRICHED_CONFIDENCE = 0.85  # 补全后的人工外推置信度


def needs_enrichment(ws: WorldSetting) -> bool:
    """是否满足补全条件：低置信度 且 类别命中 地理/历史/文化。"""
    if ws.confidence_score >= CONFIDENCE_THRESHOLD:
        return False
    return any(kw in (ws.category or "") for kw in ENRICH_CATEGORY_KEYWORDS)


async def enrich_world_setting(ws: WorldSetting) -> WorldSetting:
    """尝试联网补全单条设定；失败/未配置则返回原对象。

    成功补全后：value 取补全文本，source='enriched'，confidence_score=0.85。
    """
    if not needs_enrichment(ws):
        return ws
    s = get_settings()
    if not s.SEARCH_API_KEY or not s.SEARCH_API_BASE_URL:
        logger.info("未配置 SEARCH_API_KEY，跳过补全: %s/%s", ws.category, ws.key)
        return ws

    query = f"{ws.category} {ws.key} {ws.value}"
    try:
        # urlopen 为阻塞调用，丢到线程池避免卡死 ETL 事件循环
        enriched_value = await asyncio.to_thread(
            _call_search_api, s.SEARCH_API_BASE_URL, s.SEARCH_API_KEY, query
        )
    except Exception as exc:  # 网络失败不中断 ETL
        logger.warning("联网补全失败(%s/%s): %s", ws.category, ws.key, exc)
        return ws

    if not enriched_value:
        return ws
    return ws.model_copy(
        update={
            "value": enriched_value,
            "source": ENRICHED_SOURCE,
            "confidence_score": ENRICHED_CONFIDENCE,
        }
    )


async def enrich_batch(settings_list: list[WorldSetting]) -> list[WorldSetting]:
    """批量补全（顺序执行，占位可换并发）。"""
    out: list[WorldSetting] = []
    for ws in settings_list:
        out.append(await enrich_world_setting(ws))
    return out


async def _call_search_api(base_url: str, api_key: str, query: str) -> str | None:
    """调用搜索 API（示例实现：Tavily 风格 POST /search）。

    返回拼装的摘要文本；返回 None 表示无可用结果。
    """
    payload = json.dumps(
        {"api_key": api_key, "query": query, "search_depth": "basic", "max_results": 3}
    ).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 占位实现
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or []
    snippets = [r.get("content", "").strip() for r in results if r.get("content")]
    if not snippets:
        return None
    return "\n".join(snippets[:3])[:1000]
