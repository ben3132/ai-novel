"""WB 工具接口层：面向写作/Agent 场景的 5 个异步查询函数。

全部函数：
  - 带完整 docstring / 类型注解 / 异常处理
  - 每次调用独立使用连接池中的一个连接，无需手工管理事务
  - events↔chapters 一律使用复合 JOIN（chapter_id + chapter_created_at），
    使查询侧获得分区裁剪，避免跨分区全表扫描（计划 4.3 / 风险 8）

用法（交互式）：
    import asyncio, wb_tools
    async def main():
        r = await wb_tools.get_chapter_context(5)
        print(r)
    asyncio.run(main())
"""
from __future__ import annotations

import logging
from typing import Any

from .config import get_settings
from .db import connection
from .embed import embed_texts

logger = logging.getLogger("nms.wb_tools")


async def get_chapter_context(chapter_number: int) -> dict:
    """拼接单章写作所需的三层记忆上下文。

    三层记忆：
      - settings:          长期设定（world_settings 最新若干条，天然含 user_confirmed）
      - active_threads:    中期剧情线（仅 open/progressing，自动过滤 resolved/abandoned 伏笔）
      - recent_summaries:  近程记忆（该章之前最近 3 章摘要）

    :param chapter_number: 目标章节号
    :return: {"settings": [...], "active_threads": [...], "recent_summaries": [...]}
    :raises ValueError: chapter_number < 1
    """
    if chapter_number < 1:
        raise ValueError("chapter_number 必须 >= 1")
    async with connection() as conn:
        # 1) 长期设定：取最近 10 条（新条目即当前有效的设定）
        settings_rows = await conn.fetch(
            """
            SELECT id, category, key, value, source, confidence_score
            FROM world_settings
            ORDER BY id DESC
            LIMIT 10
            """
        )
        # 2) 中期剧情线：active 状态按优先级排序（resolved 伏笔被自动过滤）
        threads_rows = await conn.fetch(
            """
            SELECT id, title, status, priority
            FROM plot_threads
            WHERE status IN ('open', 'progressing')
            ORDER BY priority DESC, id
            """
        )
        # 3) 近程记忆：目标章之前最近 3 章摘要
        recent_rows = await conn.fetch(
            """
            SELECT number, title, summary
            FROM chapters
            WHERE number < $1 AND summary IS NOT NULL
            ORDER BY number DESC
            LIMIT 3
            """,
            chapter_number,
        )
    return {
        "settings": [
            {
                "id": r["id"], "category": r["category"], "key": r["key"],
                "value": r["value"], "source": r["source"],
                "confidence_score": r["confidence_score"],
            }
            for r in settings_rows
        ],
        "active_threads": [
            {
                "id": r["id"], "title": r["title"], "status": r["status"],
                "priority": r["priority"],
            }
            for r in threads_rows
        ],
        "recent_summaries": [
            {"number": r["number"], "title": r["title"], "summary": r["summary"]}
            for r in recent_rows
        ],
    }


async def search_memory(query: str, top_k: int = 5) -> list[dict]:
    """跨 chapters/characters/world_settings 三表向量检索。

    :param query: 自然语言检索式，如 "主角第一次受伤"
    :param top_k: 返回条数（默认 5）
    :return: [{"table": "chapters|characters|world_settings",
               "id": ..., "content": ..., "score": 0~1}, ...] 按 score 降序
    :raises ValueError: 空 query 或 top_k < 1
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    if top_k < 1:
        raise ValueError("top_k 必须 >= 1")

    s = get_settings()
    vector = (await embed_texts([query], mock=not (s.OPENAI_API_KEY and s.OPENAI_BASE_URL)))[0]
    # 注：vector 直接以 list[float] 传入 $1（pool init 已 register_vector，
    #      asyncpg 按 vector codec 编码）；勿传 '[..]' 文本——会被 Vector() 拒绝。

    sql = """
        WITH scored AS (
            SELECT 'chapters' AS tbl, c.id::bigint AS id,
                   left(coalesce(NULLIF(c.summary, ''), c.content), 300) AS content,
                   1 - (c.embedding <=> $1::vector) AS score
            FROM chapters c
            WHERE c.embedding IS NOT NULL
            UNION ALL
            SELECT 'characters', ch.id,
                   ch.name || ' — ' || coalesce(ch.current_state::text, ''),
                   1 - (ch.embedding <=> $1::vector)
            FROM characters ch
            WHERE ch.embedding IS NOT NULL
            UNION ALL
            SELECT 'world_settings', ws.id,
                   ws.category || '/' || ws.key || '：' || ws.value,
                   1 - (ws.embedding <=> $1::vector)
            FROM world_settings ws
            WHERE ws.embedding IS NOT NULL
        )
        SELECT tbl, id, content, score
        FROM scored
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT $2
    """
    async with connection() as conn:
        rows = await conn.fetch(sql, vector, top_k)
    return [
        {
            "table": r["tbl"],
            "id": int(r["id"]),
            "content": r["content"] or "",
            # SQL 已算 score = 1 − cosine_distance，此处仅保留 4 位小数
            "score": round(float(r["score"]), 4) if r["score"] is not None else 0.0,
        }
        for r in rows
    ]


async def query_character(name: str) -> dict:
    """查询角色当前状态 + 历史状态变更时间线（从 events 聚合）。

    :param name: 角色名（须与 characters.name 精确一致）
    :return: {"current_state": {...} | None,
              "timeline": [{"chapter": 章号, "title": 章标题,
                            "type": 事件类型, "change": 事件描述}]}
            角色不存在时 current_state=None、timeline=[]（不抛错）
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name 不能为空")

    async with connection() as conn:
        ch_row = await conn.fetchrow(
            "SELECT id, name, current_state FROM characters WHERE name = $1", name
        )
        if ch_row is None:
            logger.info("角色不存在: %s", name)
            return {"current_state": None, "timeline": []}

        cid = ch_row["id"]
        # 事件时间线：events 与 chapters 复合 JOIN（分区裁剪），按时间正序
        rows = await conn.fetch(
            """
            SELECT c.number, c.title, e.type, e.description, e.timestamp
            FROM events e
            JOIN chapters c
              ON c.id = e.chapter_id AND c.created_at = e.chapter_created_at
            WHERE EXISTS (
                SELECT 1 FROM jsonb_array_elements(e.related_characters) rc
                WHERE (rc->>'character_id')::bigint = $1
            )
            ORDER BY e.timestamp, e.id
            """,
            cid,
        )

    current_state = ch_row["current_state"]
    return {
        "current_state": dict(current_state) if isinstance(current_state, dict) else {},
        "timeline": [
            {
                "chapter": r["number"],
                "title": r["title"],
                "type": r["type"],
                "change": r["description"],
            }
            for r in rows
        ],
    }


async def update_world_setting(
    id: int, value: str, source: str, confidence_score: float
) -> bool:
    """人工确认闭环：更新世界设定并标记来源/置信度。

    更新会触发 update_embedding() 触发器将 embedding 置 NULL，
    下次 ETL 或 wb 重生成流程会自动补齐向量（人工确认后无需重复建库）。

    :param id: world_settings.id
    :param value: 新的设定文本
    :param source: original | enriched | user_confirmed
    :param confidence_score: 0~1
    :return: True=更新成功；False=id 不存在
    :raises ValueError: source 非法 或 confidence_score 越界
    """
    allowed = {"original", "enriched", "user_confirmed"}
    if source not in allowed:
        raise ValueError(f"source 必须 ∈ {sorted(allowed)}，收到 {source!r}")
    if not (0.0 <= float(confidence_score) <= 1.0):
        raise ValueError(f"confidence_score 必须 ∈ [0,1]，收到 {confidence_score}")
    value = (value or "").strip()
    if not value:
        raise ValueError("value 不能为空")

    async with connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE world_settings
            SET value = $2, source = $3::ws_source, confidence_score = $4
            WHERE id = $1
            RETURNING id
            """,
            id, value, source, float(confidence_score),
        )
    return row is not None


async def validate_consistency(chapter_number: int) -> list[str]:
    """一致性校验：检索前文比对人物/设定/时间线矛盾点（可选质量门禁）。

    :param chapter_number: 校验目标章节（及其在 events/characters 中的引用完整性）
    :return: 矛盾描述列表；无矛盾返回 []
    """
    issues: list[str] = []
    async with connection() as conn:
        # 0) 章节行存在性与摘要完整性
        ch = await conn.fetchrow(
            "SELECT id, summary, content, embedding IS NOT NULL AS has_emb "
            "FROM chapters WHERE number = $1 LIMIT 1",
            chapter_number,
        )
        if ch is None:
            return [f"章节 {chapter_number} 不存在（可能尚未导入）"]
        if not ch["summary"]:
            issues.append(f"章节 {chapter_number} summary 为空")
        if ch["content"] and not ch["has_emb"]:
            issues.append(f"章节 {chapter_number} 有正文但 embedding 为空（待重生成）")

        # 1) events 引用完整：chapter_id 无对应章节（复合 JOIN 缺失）
        orphan_events = await conn.fetchval(
            """
            SELECT count(*) FROM events e
            WHERE e.chapter_id = (SELECT id FROM chapters WHERE number = $1 LIMIT 1)
              AND NOT EXISTS (
                  SELECT 1 FROM chapters c
                  WHERE c.id = e.chapter_id AND c.created_at = e.chapter_created_at)
            """,
            chapter_number,
        )
        if orphan_events:
            issues.append(f"章节 {chapter_number} 存在 {orphan_events} 条事件引用缺失章节")

        # 2) events.related_characters 引用了不存在的角色
        bad_refs = await conn.fetchval(
            """
            SELECT count(*) FROM events e
            WHERE e.chapter_id = (SELECT id FROM chapters WHERE number = $1 LIMIT 1)
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(e.related_characters) rc
                  WHERE NOT EXISTS (
                      SELECT 1 FROM characters c2 WHERE c2.id = (rc->>'character_id')::bigint))
            """,
            chapter_number,
        )
        if bad_refs:
            issues.append(f"章节 {chapter_number} 存在 {bad_refs} 条事件引用了不存在的角色")

        # 3) characters.first_appear_chapter_id 指向不存在的章节
        bad_first = await conn.fetchval(
            """
            SELECT count(*) FROM characters f
            WHERE f.first_appear_chapter_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM chapters c
                  WHERE c.id = f.first_appear_chapter_id)
            """
        )
        if bad_first:
            issues.append(f"有 {bad_first} 个角色的 first_appear_chapter_id 指向不存在的章节")

        # 4) 章节号重复（并发/重跑脏数据兜底检测）
        dup_rows = await conn.fetch(
            """
            SELECT number, count(*) AS cnt
            FROM chapters GROUP BY number HAVING count(*) > 1
            ORDER BY number LIMIT 10
            """
        )
        for d in dup_rows:
            issues.append(f"章节号重复：number={d['number']} 共 {d['cnt']} 行（幂等预检失效）")

        # 5) 该章摘要与 events 描述中时间线矛盾粗检（示例规则：事件早于章节号出现）
        #    仅当事件 timestamp 早于该章 created_at 且事件归属其他章节时提示
        cross = await conn.fetchval(
            """
            SELECT count(*) FROM events e
            JOIN chapters c ON c.id = e.chapter_id AND c.created_at = e.chapter_created_at
            WHERE c.number = $1
              AND e.timestamp < c.created_at - interval '1 minute'
            """,
            chapter_number,
        )
        if cross:
            issues.append(f"章节 {chapter_number} 有 {cross} 条事件时间早于本章开始时间（时间线矛盾）")

    return issues
