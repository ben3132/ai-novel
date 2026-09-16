"""分区工具：幂等创建月分区并同步建 HNSW 索引（与 init.sql 中的函数配套）。

ETL 每章入库前必须调用 :func:`ensure_partition`，保证"有分区必有 HNSW 索引"。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

# init.sql 定义的存储函数：CREATE TABLE IF NOT EXISTS ... PARTITION OF ...
# 并在同一函数内为子表建 HNSW（m=16, ef_construction=64）。幂等。
_SQL_ENSURE_PARTITION = "SELECT ensure_month_partition($1::text, $2::timestamptz)"

# 分区子表与索引的命名规范（与 init.sql 保持一致）
PARTITION_PREFIX = {  # parent 表名 → 分区前缀（实际即表名本身）
    "chapters": "chapters",
    "events": "events",
}


async def ensure_partition(conn: asyncpg.Connection, parent: str, ts: datetime) -> str:
    """确保 parent 表存在 ts 所在月份的【分区子表 + HNSW 索引】，返回子表名。"""
    if parent not in PARTITION_PREFIX:
        raise ValueError(f"不支持的分区父表: {parent!r}，仅支持 chapters/events")
    child: str = await conn.fetchval(_SQL_ENSURE_PARTITION, parent, ts)
    if not child:
        raise RuntimeError(f"ensure_month_partition 未返回子表名: parent={parent} ts={ts}")
    return child


async def ensure_partitions_many(
    conn: asyncpg.Connection, parent: str, timestamps: list[datetime]
) -> set[str]:
    """对一组时间戳去重后批量建分区，返回涉及的全部子表名。"""
    seen: set[str] = set()
    for ts in timestamps:
        seen.add(await ensure_partition(conn, parent, ts))
    return seen
