"""Embedding：批量生成 + 批量回填（unnest 复合主键严格对齐）。

对齐保证（防向量静默错位，见计划 3.6）：
  1. ids/created_ats/emb_texts 由同一有序行列表构造，绝不中途重排；
  2. 传输前 assert 三数组等长（不等长时 PG 多参 unnest 行为不可依赖）；
  3. emb 以 text[] 传输 + SQL 端 ::vector 转换（规避 asyncpg 对 vector 数组编解码差异）；
  4. 列别名顺序与主键顺序一致：u(id, created_at, emb)；
  5. 回填后校验 rowcount == 期望行数，不等则抛错，杜绝静默部分回填。

离线/无 key 降级：确定性伪向量（sha256 播种），维度与 schema 一致(1536)，保证 mock 全流程可跑。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random

import asyncpg

from .config import get_settings
from .db import vec_to_text

logger = logging.getLogger(__name__)


def _llm_available() -> bool:
    s = get_settings()
    return bool(s.OPENAI_API_KEY) and s.OPENAI_BASE_URL != ""


def deterministic_vector(text: str, dim: int | None = None) -> list[float]:
    """基于文本的确定性伪向量（归一化），供 mock/离线流程使用。"""
    s = get_settings()
    dim = dim or s.EMBED_DIM
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


async def embed_texts(
    texts: list[str], *, mock: bool = False
) -> list[list[float]]:
    """批量文本 → 向量列表（保持输入顺序，绝不重排）。

    :param mock: True 强制确定性伪向量；False 时若未配置 key 也会自动降级。
    """
    if not texts:
        return []
    s = get_settings()
    if mock or not _llm_available():
        return [deterministic_vector(t) for t in texts]

    from openai import AsyncOpenAI  # 延迟导入

    client = AsyncOpenAI(api_key=s.OPENAI_API_KEY, base_url=s.OPENAI_BASE_URL)
    results: list[list[float]] = []
    # OpenAI 批量上限 2048，pgvector 无限制；保守每批 ≤ EMBED_BATCH_SIZE
    for i in range(0, len(texts), s.EMBED_BATCH_SIZE):
        batch = texts[i : i + s.EMBED_BATCH_SIZE]
        resp = await client.embeddings.create(model=s.EMBED_MODEL, input=batch)
        # response.data 顺序与输入顺序一致；仍按 data[0..] 依次取，防御性核对
        ordered = sorted(resp.data, key=lambda d: d.index)
        results.extend([list(d.embedding) for d in ordered])
    if len(results) != len(texts):  # 防御：数量不符立即暴露，避免静默错位
        raise RuntimeError(
            f"embedding 返回数量不符: 期望 {len(texts)} 实际 {len(results)}"
        )
    return results


def _truncate_tokens(text: str, budget: int = 8000) -> str:
    """占位 token 截断：有 tiktoken 则按真实 token 切，否则按字符粗估（中文≈1token/字）。"""
    s = get_settings()
    budget = min(budget, s.MAX_CONTEXT_TOKENS)
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model(s.EMBED_MODEL)
        tokens = enc.encode(text)
        if len(tokens) <= budget:
            return text
        return enc.decode(tokens[:budget])
    except Exception:
        return text[: budget * 2]  # 中文字符粗估：保守截断


# ---------------------------------------------------------------------------
# 回填（chapters：复合主键 (id, created_at)；characters/world_settings：单键 id）
# ---------------------------------------------------------------------------

_SQL_UPDATE_CHAPTERS_EMB = """
UPDATE chapters AS c
SET embedding = u.emb::vector
FROM unnest($1::bigint[], $2::timestamptz[], $3::text[]) AS u(id, created_at, emb)
WHERE c.id = u.id AND c.created_at = u.created_at
"""

_SQL_UPDATE_SINGLE_EMB = "UPDATE {table} SET embedding = u.emb::vector FROM unnest($1::bigint[], $2::text[]) AS u(id, emb) WHERE {table}.id = u.id"


async def backfill_chapters_embedding(
    conn: asyncpg.Connection,
    rows: list[tuple[int, object, str]],
    *,
    mock: bool = False,
) -> None:
    """回填章节 embedding。

    :param rows: [(id, created_at, embed_text), ...]，embed_text 在内部做 token 截断。
    """
    if not rows:
        return
    texts = [_truncate_tokens(t) for _, _, t in rows]
    vectors = await embed_texts(texts, mock=mock)
    ids = [r[0] for r in rows]
    created_ats = [r[1] for r in rows]
    emb_texts = [vec_to_text(v) for v in vectors]

    # 对齐断言 ①：同源有序 + 等长（不等长时 PG 多参 unnest 行为不可依赖）
    assert len(ids) == len(created_ats) == len(emb_texts) == len(rows), (
        "chapters embedding 回填数组长度不一致——禁止静默错位回填"
    )
    status = await conn.execute(
        _SQL_UPDATE_CHAPTERS_EMB, ids, created_ats, emb_texts
    )
    _check_rowcount(status, len(rows), "chapters")


async def backfill_single_key_embedding(
    conn: asyncpg.Connection,
    table: str,
    rows: list[tuple[int, str]],
    *,
    mock: bool = False,
) -> None:
    """回填 characters/world_settings 的 embedding（主键仅 id）。

    :param rows: [(id, embed_text), ...]
    """
    if table not in ("characters", "world_settings"):
        raise ValueError("backfill_single_key_embedding 仅支持 characters/world_settings")
    if not rows:
        return
    texts = [_truncate_tokens(t) for _, t in rows]
    vectors = await embed_texts(texts, mock=mock)
    ids = [r[0] for r in rows]
    emb_texts = [vec_to_text(v) for v in vectors]
    assert len(ids) == len(emb_texts) == len(rows), (
        f"{table} embedding 回填数组长度不一致——禁止静默错位回填"
    )
    status = await conn.execute(
        _SQL_UPDATE_SINGLE_EMB.format(table=table), ids, emb_texts
    )
    _check_rowcount(status, len(rows), table)


def _check_rowcount(status: str, expected: int, table: str) -> None:
    """解析 'UPDATE n' 结果；n != expected 时抛错（防静默部分回填）。"""
    match = status.split()
    if len(match) == 2 and match[0].upper() == "UPDATE":
        updated = int(match[1])
        if updated != expected:
            raise RuntimeError(
                f"{table} embedding 回填行数不匹配: 期望 {expected} 实际 {updated}"
            )
        return
    raise RuntimeError(f"回填 {table} embedding 失败，SQL 结果异常: {status!r}")
