"""ETL 主运行器：存量 Markdown 稿件 → LLM 结构化提取 → 入库 → 批量 embedding。

核心机制：
  - 章节号幂等预检（advisory lock + EXISTS）：并发/重跑不产生重复章节（计划 3.3）
  - 每 BATCH_SIZE(默认10) 章一个大事务 + 章级 savepoint；单章失败仅回滚自身（计划 3.2）
  - 批次事务 COMMIT 后统一生成 embedding，按复合主键 (id, created_at) 精确回填（计划 3.6）
  - etl_state.json 原子落盘；--resume / --reprocess-chapter N / --mock（离线降级）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import Settings, get_settings
from .db import close_pool, connection
from .embed import (
    backfill_chapters_embedding,
    backfill_single_key_embedding,
)
from .enrich import enrich_batch
from .extract import LLMClientError, extract_chapter
from .partition import ensure_partition
from .state import ETLState, ErrorLogger, FileLock
from .schemas import ChapterExtraction, PlotThread, WorldSetting

logger = logging.getLogger("nms.etl")

_FILE_RE = re.compile(r"^chapter_(\d+)\.md$")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# 角色 current_state 为空时使用的兜底 jsonb
_EMPTY_STATE = "{}"


# ---------------------------------------------------------------------------
# 领域结构
# ---------------------------------------------------------------------------
@dataclass
class ChapterJob:
    number: int
    path: Path


@dataclass
class TimePlan:
    """由稿件最大章号推导的确定性时间分布（供幂等重跑，见决策 D′）。

    ts(num) = base − (max_num − num) × step
    """

    max_num: int
    base: datetime
    step_min: float

    def ts(self, number: int) -> datetime:
        return self.base - timedelta(minutes=self.step_min * (self.max_num - number))

    def event_ts(self, chapter_ts: datetime, idx: int, total: int) -> datetime:
        """事件时间 = 章时间 + 片内均布偏移（不越下章起点）。"""
        if total <= 0:
            return chapter_ts
        frac = (idx + 1) / (total + 1)
        return chapter_ts + timedelta(minutes=self.step_min * frac)


def make_time_plan(settings: Settings, max_num: int) -> TimePlan:
    base = settings.parse_time_base()
    span_min = settings.ETL_TIME_SPAN_DAYS * 1440.0
    if max_num <= 1:
        step = span_min if span_min > 0 else 10.0
    elif span_min <= 0:
        step = 0.0
    else:
        step = span_min / max_num
    return TimePlan(max_num=max_num, base=base, step_min=step)


@dataclass
class PendingEmbeds:
    """本批次需回填 embedding 的行。chapters 用复合键，其余用单键。"""

    chapters: list[tuple[int, datetime, str]] = field(default_factory=list)
    characters: list[tuple[int, str]] = field(default_factory=list)
    world_settings: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ChapterResult:
    number: int
    ok: bool
    action: str  # inserted | skipped | backfilled | failed
    error: str = ""
    error_fields: str = ""


def chapter_embed_text(title: str, summary: str, content: str) -> str:
    """章节的 embedding 文本（插入与纯回填两条路径必须一致，保证可复现）。"""
    budget_chars = get_settings().MAX_CONTEXT_TOKENS * 2
    body = (content or "").strip()
    if len(body) > budget_chars:
        body = body[:budget_chars]
    return f"{title}\n{summary}\n{body}"


# ---------------------------------------------------------------------------
# 文件发现
# ---------------------------------------------------------------------------
def discover_chapters(directory: Path) -> list[ChapterJob]:
    jobs: list[ChapterJob] = []
    for p in sorted(directory.glob("chapter_*.md")):
        m = _FILE_RE.match(p.name)
        if m:
            jobs.append(ChapterJob(number=int(m.group(1)), path=p))
    jobs.sort(key=lambda j: j.number)
    return jobs


def read_markdown(path: Path) -> tuple[str, str]:
    """读取 .md → (title, content)。首个 # 标题作为 title。"""
    text = path.read_text(encoding="utf-8-sig")
    m = _HEADING_RE.search(text)
    if m:
        return m.group(1).strip(), text[m.end():].strip()
    return path.stem, text.strip()


# ---------------------------------------------------------------------------
# 幂等预检 / 清库
# ---------------------------------------------------------------------------
async def _chapter_exists(conn: Any, number: int) -> tuple[bool, int | None, datetime | None]:
    row = await conn.fetchrow(
        "SELECT id, created_at FROM chapters WHERE number = $1 ORDER BY created_at LIMIT 1",
        number,
    )
    if row is None:
        return False, None, None
    return True, row["id"], row["created_at"]


async def _purge_chapter(conn: Any, number: int) -> None:
    """清空某章节号在 events/chapters 中的数据（--reprocess 与批次补偿回滚共用）。"""
    await conn.execute(
        """
        DELETE FROM events ev USING chapters c
        WHERE ev.chapter_id = c.id AND ev.chapter_created_at = c.created_at
          AND c.number = $1
        """,
        number,
    )
    # 清理剧情线中指向已删事件的悬空引用
    await conn.execute(
        """
        UPDATE plot_threads pt
        SET related_events = COALESCE(
            (SELECT jsonb_agg(elem ORDER BY ord)
             FROM jsonb_array_elements(pt.related_events) WITH ORDINALITY AS t(elem, ord)
             WHERE NOT EXISTS (
                 SELECT 1 FROM events ev JOIN chapters c
                   ON ev.chapter_id = c.id AND ev.chapter_created_at = c.created_at
                 WHERE c.number = $1 AND ev.id = (elem->>'event_id')::bigint)),
            '[]'::jsonb)
        WHERE jsonb_array_length(pt.related_events) > 0
        """,
        number,
    )
    # 角色首次登场章节被清 → first_appear 置 NULL（重跑时经 COALESCE 自愈回新章节 id）
    await conn.execute(
        """
        UPDATE characters ch
        SET first_appear_chapter_id = NULL
        WHERE ch.first_appear_chapter_id IN (
            SELECT id FROM chapters WHERE number = $1)
        """,
        number,
    )
    await conn.execute("DELETE FROM chapters WHERE number = $1", number)


# ---------------------------------------------------------------------------
# 单章入库
# ---------------------------------------------------------------------------
async def _process_new_chapter(
    conn: Any,
    job: ChapterJob,
    ext: ChapterExtraction,
    created_at: datetime,
    time_plan: TimePlan,
    pending: PendingEmbeds,
    content: str,
) -> None:
    """完整入库一章（调用方处于事务 + savepoint 内）。"""
    await ensure_partition(conn, "chapters", created_at)

    # 1) chapters
    row = await conn.fetchrow(
        """
        INSERT INTO chapters (number, title, content, summary, created_at)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        job.number, ext.title, content, ext.summary, created_at,
    )
    cid: int = row["id"]
    pending.chapters.append(
        (cid, created_at, chapter_embed_text(ext.title, ext.summary, content))
    )

    # 2) characters：先统一 UPSERT（含事件仅提及的角色），name → id
    char_ids: dict[str, int] = await _upsert_characters(conn, ext, cid, pending)

    # 3) world_settings：enrich（低置信度 地理/历史/文化 联网补全）后 UPSERT
    enriched = await enrich_batch(ext.world_settings)
    for ws in enriched:
        wid = await _upsert_world_setting(conn, ws)
        pending.world_settings.append((wid, f"{ws.category} {ws.key} {ws.value}"))

    # 4) events：逐条按事件时间戳建分区（章末事件可能跨月，不能只按章时间预建）
    event_ids: list[int] = []
    for idx, ev in enumerate(ext.events):
        ev_ts = time_plan.event_ts(created_at, idx, len(ext.events))
        await ensure_partition(conn, "events", ev_ts)
        refs = [
            {"character_id": char_ids[rc.name], "role": rc.role or ""}
            for rc in ev.related_characters
            if rc.name in char_ids
        ]
        ev_row = await conn.fetchrow(
            """
            INSERT INTO events
                (chapter_id, chapter_created_at, type, description,
                 related_characters, timestamp)
            VALUES ($1, $2, $3::event_type, $4, $5::jsonb, $6)
            RETURNING id
            """,
            cid, created_at, ev.type, ev.description,
            json.dumps(refs, ensure_ascii=False),
            ev_ts,
        )
        event_ids.append(ev_row["id"])

    # 5) plot_threads：title UPSERT + 事件引用解析回填
    await _upsert_plot_threads(conn, ext.plot_threads, event_ids)


async def _upsert_characters(
    conn: Any, ext: ChapterExtraction, cid: int, pending: PendingEmbeds
) -> dict[str, int]:
    """UPSERT 本章全部角色（含 events 中提及的），返回 name → id。"""
    char_ids: dict[str, int] = {}

    # 主角色：更新 current_state（最新快照）；first_appear 仅在首次插入时写入
    for ch in ext.characters:
        state = json.dumps(ch.current_state or {}, ensure_ascii=False)
        if not (state and state != _EMPTY_STATE):
            state = _EMPTY_STATE
        c_row = await conn.fetchrow(
            """
            INSERT INTO characters (name, current_state, first_appear_chapter_id)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT (name) DO UPDATE
                SET current_state = EXCLUDED.current_state,
                    -- first_appear 仅在空（旧登场章被清）时回填，保持首次登场语义
                    first_appear_chapter_id = COALESCE(
                        characters.first_appear_chapter_id,
                        EXCLUDED.first_appear_chapter_id)
                -- 注意：不可加 WHERE——值相同时 DO UPDATE 被跳过将不返回行，
                -- fetchrow 得 None（同值重跑/批间残留即触发）。embedding 置空由
                -- update_embedding() 触发器内部按 IS DISTINCT 判断，值未变不会清。
            RETURNING id
            """,
            ch.name, state, cid,
        )
        char_ids[ch.name] = c_row["id"]

    # 事件仅提及的角色：确保存在（不覆盖已有状态）
    for ev in ext.events:
        for rc in ev.related_characters:
            if rc.name in char_ids:
                continue
            got = await conn.fetchval(
                """
                INSERT INTO characters (name, first_appear_chapter_id)
                VALUES ($1, $2)
                ON CONFLICT (name) DO NOTHING
                RETURNING id
                """,
                rc.name, cid,
            )
            if got is None:
                got = await conn.fetchval(
                    "SELECT id FROM characters WHERE name = $1", rc.name
                )
            char_ids[rc.name] = got

    # 角色 embedding 文本（UPSERT 触发了 update_embedding 置空，本批统一回填）
    for name, cid_c in char_ids.items():
        state_text = await conn.fetchval(
            "SELECT current_state::text FROM characters WHERE id = $1", cid_c
        ) or ""
        pending.characters.append((cid_c, f"{name} {state_text}"))
    return char_ids


async def _upsert_world_setting(conn: Any, ws: WorldSetting) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO world_settings (category, key, value, source, confidence_score)
        VALUES ($1, $2, $3, $4::ws_source, $5)
        ON CONFLICT (category, key) DO UPDATE
            SET value = EXCLUDED.value, source = EXCLUDED.source,
                confidence_score = EXCLUDED.confidence_score
            -- 不加 WHERE：同值重跑时 DO UPDATE 若被跳过将不返回行（row=None）。
            -- embedding 置空交由 update_embedding() 触发器按 IS DISTINCT 判断。
        RETURNING id
        """,
        ws.category, ws.key, ws.value, ws.source, ws.confidence_score,
    )
    return row["id"]


async def _upsert_plot_threads(
    conn: Any, threads: list[PlotThread], event_ids: list[int]
) -> None:
    """剧情线按 title UPSERT；related_events 追加本章真实事件引用。"""
    for t in threads:
        refs = [
            {"event_id": event_ids[er.event_index], "relation": er.relation}
            for er in t.events
            if 0 <= er.event_index < len(event_ids)
        ]
        await conn.execute(
            """
            INSERT INTO plot_threads (title, status, priority, related_events)
            VALUES ($1, $2::thread_status, $3, $4::jsonb)
            ON CONFLICT (title) DO UPDATE
                SET status = EXCLUDED.status, priority = EXCLUDED.priority,
                    related_events = plot_threads.related_events || EXCLUDED.related_events
            """,
            t.title, t.status, t.priority, json.dumps(refs, ensure_ascii=False),
        )


# ---------------------------------------------------------------------------
# 批次处理：单事务 + 章级 savepoint → COMMIT → 统一 embedding 回填
# ---------------------------------------------------------------------------
def _dedupe_single(rows: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """按 id 去重（保留最后一次的 embedding 文本），防同批多次 upsert 同一行导致 rowcount 误判。"""
    out: dict[int, str] = {}
    for rid, text in rows:
        out[rid] = text
    return list(out.items())


def _dedupe_chapters(
    rows: list[tuple[int, datetime, str]]
) -> list[tuple[int, datetime, str]]:
    out: dict[tuple[int, datetime], str] = {}
    for rid, ts, text in rows:
        out[(rid, ts)] = text
    return [(k[0], k[1], v) for k, v in out.items()]


async def _run_batch(
    conn: Any,
    jobs: list[ChapterJob],
    state: ETLState,
    settings: Settings,
    mock: bool,
    error_log: ErrorLogger,
    time_plan: TimePlan,
) -> list[ChapterResult]:
    results: list[ChapterResult] = []
    pending = PendingEmbeds()
    await conn.execute("BEGIN")
    try:
        for job in jobs:
            sp = f"sp_{job.number}"
            await conn.execute(f"SAVEPOINT {sp}")
            try:
                res = await _process_one_chapter(
                    conn, job, state, settings, mock, error_log, time_plan, pending
                )
                results.append(res)
                if res.ok:
                    await conn.execute(f"RELEASE SAVEPOINT {sp}")
                else:
                    # 失败：回滚本 savepoint 后立即释放，批次其余章节不受影响
                    await conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    await conn.execute(f"RELEASE SAVEPOINT {sp}")
            except Exception as exc:  # noqa: BLE001 防御：单章任何异常都不得拖垮批次
                logger.exception("章节 %d 意外异常", job.number)
                await conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                await conn.execute(f"RELEASE SAVEPOINT {sp}")
                error_log.log(job.number, "", "", f"章节处理异常: {exc}")
                results.append(ChapterResult(job.number, False, "failed", str(exc)))
        await conn.execute("COMMIT")
    except BaseException:
        await conn.execute("ROLLBACK")
        raise

    # —— COMMIT 后统一 embedding 生成 + 精确回填（先按主键去重，防 rowcount 误判）——
    try:
        await backfill_chapters_embedding(
            conn, _dedupe_chapters(pending.chapters), mock=mock
        )
        await backfill_single_key_embedding(
            conn, "characters", _dedupe_single(pending.characters), mock=mock
        )
        await backfill_single_key_embedding(
            conn, "world_settings", _dedupe_single(pending.world_settings), mock=mock
        )
    except Exception as exc:  # noqa: BLE001 embedding 回填失败 → 整批补偿回滚，下轮重做
        logger.exception("本批 embedding 回填失败，整批标记失败以便重做")
        for res in results:
            if res.action in ("inserted", "backfilled"):
                res.ok, res.action, res.error = False, "failed", str(exc)
        error_log.log(None, "", "", f"批次 embedding 回填失败，补偿回滚本批: {exc}")
        for res in results:
            if res.action == "failed":
                try:
                    await _purge_chapter(conn, res.number)
                except Exception as purge_exc:  # noqa: BLE001
                    logger.exception("补偿回滚章节 %d 失败", res.number)
                    error_log.log(res.number, "", "", f"补偿回滚失败: {purge_exc}")
    return results


async def _process_one_chapter(
    conn: Any,
    job: ChapterJob,
    state: ETLState,
    settings: Settings,
    mock: bool,
    error_log: ErrorLogger,
    time_plan: TimePlan,
    pending: PendingEmbeds,
) -> ChapterResult:
    """单章：幂等预检 → 已存在(done)跳过 / embedding 缺失则纯回填 / 否则完整入库。"""
    # 幂等预检（计划 3.3）：advisory lock 按章号串行化并发 ETL，锁与预检同一事务
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('nms_chapters'), $1::int)", job.number
    )
    exists, _cid, _created = await _chapter_exists(conn, job.number)
    if exists:
        has_emb = await conn.fetchval(
            "SELECT embedding IS NOT NULL FROM chapters WHERE number = $1 LIMIT 1",
            job.number,
        )
        if has_emb:
            return ChapterResult(job.number, True, "skipped")
        # 行在但 embedding 空（上次提交后崩溃 / 文本被更新触发置空）→ 只补 embedding
        row = await conn.fetchrow(
            "SELECT id, created_at, title, summary, content "
            "FROM chapters WHERE number = $1 LIMIT 1",
            job.number,
        )
        if row is None:
            return ChapterResult(job.number, False, "failed", "章节行预检后消失")
        pending.chapters.append(
            (row["id"], row["created_at"], chapter_embed_text(row["title"] or f"第{job.number}章", row["summary"] or "", row["content"] or ""))
        )
        return ChapterResult(job.number, True, "backfilled")

    # —— 不存在 → 读取 + LLM 提取（失败写 etl_errors.log，不中断批次）——
    title, content = read_markdown(job.path)
    try:
        ext = await extract_chapter(job.number, title, content, mock=mock)
    except ValidationError as exc:
        fields = ",".join(
            e["loc"] and ".".join(map(str, e["loc"])) or "?" for e in exc.errors()
        )
        error_log.log(job.number, fields, content[:500], f"Pydantic校验失败: {exc}")
        return ChapterResult(job.number, False, "failed", str(exc), fields)
    except LLMClientError as exc:
        error_log.log(job.number, "", "", f"LLM 调用失败: {exc}")
        return ChapterResult(job.number, False, "failed", str(exc))

    if ext.chapter_number != job.number:  # 强对齐文件名章号
        ext = ext.model_copy(update={"chapter_number": job.number})

    created_at = time_plan.ts(job.number)
    await _process_new_chapter(conn, job, ext, created_at, time_plan, pending, content)
    return ChapterResult(job.number, True, "inserted")


# ---------------------------------------------------------------------------
# 状态落盘
# ---------------------------------------------------------------------------
def _apply_results(state: ETLState, results: list[ChapterResult]) -> None:
    for res in results:
        if res.ok:
            state.mark_done(res.number)
        else:
            state.mark_failed(res.number, res.error or res.error_fields or "unknown")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="etl.py",
        description="小说记忆 ETL：Markdown 存量稿件 → 结构化入库 + embedding",
    )
    p.add_argument("--dir", type=Path, default=None, help="稿件目录（默认 data/chapters）")
    p.add_argument("--resume", action="store_true", help="断点续传：跳过已 done 章节")
    p.add_argument("--reprocess-chapter", type=int, metavar="N",
                   help="强制重跑指定章节号（先清空该章旧数据再入库）")
    p.add_argument("--mock", action="store_true", help="离线降级：不调用 LLM/embedding API")
    p.add_argument("--log-level", default=None, help="覆盖日志级别（DEBUG/INFO/WARNING/ERROR）")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=(args.log_level or settings.LOG_LEVEL or "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(130)


async def async_main(args: argparse.Namespace) -> None:
    settings = get_settings()
    chapters_dir = args.dir or settings.CHAPTERS_DIR
    all_jobs = discover_chapters(chapters_dir)
    if not all_jobs:
        logger.warning("未发现 chapter_*.md，目录: %s", chapters_dir)
        return

    max_num = max(j.number for j in all_jobs)
    time_plan = make_time_plan(settings, max_num)
    state = ETLState().load()
    error_log = ErrorLogger()

    # 选出待处理章节：done 跳过（除非强制重跑）；失败超限跳过
    reprocess_n = args.reprocess_chapter
    todo = [
        j for j in all_jobs
        if (not state.is_done(j.number) or j.number == reprocess_n)
        and (
            j.number == reprocess_n
            or state.failed_attempts(j.number) < settings.MAX_CHAPTER_RETRIES
        )
    ]
    if reprocess_n is not None and not any(j.number == reprocess_n for j in all_jobs):
        logger.warning("--reprocess-chapter %d 不在稿件目录中，忽略", reprocess_n)
    logger.info(
        "稿件 %d 章（max 章号 %d），本次待处理 %d 章%s",
        len(all_jobs), max_num, len(todo),
        "（--resume 续传）" if args.resume else "",
    )

    with FileLock():
        async with connection() as conn:
            if reprocess_n is not None:
                state.reset_chapter(reprocess_n)
                state.save()
                await _purge_chapter(conn, reprocess_n)
                logger.info("已清空章节 %d 旧数据", reprocess_n)

            for start in range(0, len(todo), settings.BATCH_SIZE):
                batch = todo[start: start + settings.BATCH_SIZE]
                results = await _run_batch(
                    conn, batch, state, settings, args.mock, error_log, time_plan
                )
                _apply_results(state, results)
                state.save()  # 每批原子落盘（计划 3.2：崩溃后从最近非 done 续跑）
                ok_n = sum(1 for r in results if r.ok)
                logger.info(
                    "批次完成：%d/%d 成功（累计 done %d）",
                    ok_n, len(batch), state.processed_count(),
                )

    logger.info("ETL 结束：共 %d 章，已 done %d", len(all_jobs), state.processed_count())


if __name__ == "__main__":
    main()
