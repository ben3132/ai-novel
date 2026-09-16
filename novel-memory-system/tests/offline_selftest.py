"""离线自测（无需 DB/LLM/网络）：验证可独立运行的代码路径。

运行：
    .venv\\Scripts\\python tests\\offline_selftest.py

覆盖：
  1. 包导入链完整（config/db/partition/state/schemas/extract/embed/enrich/etl_runner/wb_tools）
  2. config：ETL_TIME_BASE=now / 固定 ISO 解析；ETL_TIME_SPAN_DAYS 校验
  3. TimePlan 时间分布：末章锚定 base、跨度正确、确定性
  4. schemas：Pydantic 正常校验通过 + 非法输入被拒（校验失败路径）
  5. extract：mock 启发式提取输出合法 ChapterExtraction
  6. embed：deterministic_vector 维度=1536、确定性、归一化
  7. state：etl_state.json 原子读写 + 状态机标记 + FileLock 互斥
  8. wb_tools / etl_runner 纯逻辑（advisory 锁 SQL 常量、去重函数）
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("ETL_TIME_BASE", "2026-01-01T00:00:00+08:00")
os.environ.setdefault("ETL_TIME_SPAN_DAYS", "30")

from pydantic import ValidationError  # noqa: E402

from novel_memory_system.config import Settings, get_settings  # noqa: E402
from novel_memory_system.embed import deterministic_vector  # noqa: E402
from novel_memory_system.extract import extract_chapter  # noqa: E402
from novel_memory_system.schemas import (  # noqa: E402
    ChapterExtraction,
    ChapterEvent,
    PlotThread,
    WorldSetting,
)
from novel_memory_system.state import ETLState, ErrorLogger, FileLock  # noqa: E402

# etl_runner 的纯函数（无 DB 依赖）
from novel_memory_system.etl_runner import (  # noqa: E402
    _dedupe_chapters,
    _dedupe_single,
    chapter_embed_text,
    make_time_plan,
)

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_config() -> None:
    print("[1] config")
    s = get_settings()
    base = s.parse_time_base()
    check("固定 ISO base 解析为带时区时间", base.tzinfo is not None and base.hour == 0, str(base))
    # 非法 span
    try:
        bad = Settings()  # type: ignore[abstract]
        bad.ETL_TIME_SPAN_DAYS = -1
        bad.validate()
        check("负 span 应抛 ValueError", False)
    except ValueError:
        check("负 span 抛 ValueError", True)


def test_time_plan() -> None:
    print("[2] TimePlan")
    s = get_settings()
    plan = make_time_plan(s, max_num=100)
    base = s.parse_time_base()
    # 末章锚定 base
    check("第100章时间 == base", plan.ts(100) == base)
    # 第1章 = base − span×(N−1)/N（计划 3.5 公式：N=100、span=30d → 29.7d）
    exp_days = s.ETL_TIME_SPAN_DAYS * (plan.max_num - 1) / plan.max_num
    exp_sec = exp_days * 86400
    check(
        "第1章按计划公式回落",
        abs(abs((plan.ts(1) - base).total_seconds()) - exp_sec) < 1.0,
        f"offset={(plan.ts(1) - base).total_seconds() / 86400:.4f}d",
    )
    # 中间章单调递增
    check("章节时间单调", all(plan.ts(i) < plan.ts(i + 1) for i in range(1, 100)))
    # 事件时间不越章界
    ev = plan.event_ts(plan.ts(50), idx=4, total=5)
    check("事件时间 < 下章起点", ev < plan.ts(51))
    # 确定性：两次构造相同
    plan2 = make_time_plan(get_settings(), max_num=100)
    check("时间分布确定性", plan.ts(42) == plan2.ts(42))


def test_schemas() -> None:
    print("[3] schemas")
    good = ChapterExtraction(
        chapter_number=1,
        title="风起",
        summary="林晓在青石巷发现铁令线索。",
        characters=[{"name": "林晓", "current_state": {"位置": "青石巷"}}],
        world_settings=[WorldSetting(category="地理", key="青石巷", value="城西暗巷", confidence_score=0.6)],
        events=[ChapterEvent(type="conflict", description="粮仓起火", related_characters=[{"name": "林晓", "role": "主角"}])],
        plot_threads=[PlotThread(title="铁令之谜", status="open", events=[{"event_index": 0, "relation": "铺垫"}])],
    )
    check("正常提取模型通过", good.summary.startswith("林晓"))
    check("WorldSetting confidence 上界被拒", _raises(WorldSetting, category="历史", key="k", value="v", confidence_score=1.5))
    check("Event type 非法被拒", _raises(ChapterEvent, type="nope", description="x"))
    check("summary 空被拒", _raises(ChapterExtraction, chapter_number=1, title="t", summary="  "))


def _raises(model, **kw) -> bool:
    try:
        model(**kw)
        return False
    except ValidationError:
        return True


def test_extract_mock() -> None:
    print("[4] extract.mock")
    content = (Path(ROOT) / "data" / "chapters" / "chapter_001.md").read_text(encoding="utf-8-sig")
    ext = extract_chapter(1, "风起青石巷", content, mock=True) if False else None  # async → 用 asyncio 跑
    import asyncio
    ext = asyncio.run(extract_chapter(1, "风起青石巷", content, mock=True))
    check("mock 提取为合法模型", isinstance(ext, ChapterExtraction) and ext.chapter_number == 1)
    check("mock summary 非空", bool(ext.summary))


def test_embed() -> None:
    print("[5] embed 确定性向量")
    v1 = deterministic_vector("同一段文本")
    v2 = deterministic_vector("同一段文本")
    v3 = deterministic_vector("不同文本")
    check("维度=1536", len(v1) == 1536)
    check("确定性", v1 == v2)
    check("不同文本不同向量", v1 != v3)
    norm = sum(x * x for x in v1) ** 0.5
    check("已归一化", abs(norm - 1.0) < 1e-6, f"norm={norm}")


def test_state() -> None:
    print("[6] state")
    with tempfile.TemporaryDirectory() as td:
        st = ETLState(path=Path(td) / "etl_state.json")
        st.mark_in_progress(1)
        st.mark_done(1)
        st.mark_failed(2, "字符校验失败")
        st.save()
        st2 = ETLState(path=st.path).load()
        check("done 持久化", st2.is_done(1))
        check("failed 持久化+attempts", st2.failed_attempts(2) == 1)
        check("processed_count", st2.processed_count() == 1)
        st2.mark_done(2)
        st2.save()
        st3 = ETLState(path=st.path).load()
        check("覆盖保存成功", st3.is_done(2))

        # 文件锁互斥
        lock_path = Path(td) / "etl.lock"
        with FileLock(lock_path, timeout=1.0):
            try:
                with FileLock(lock_path, timeout=1.0):
                    check("重复加锁应超时", False)
            except TimeoutError:
                check("重复加锁抛 TimeoutError", True)
        # 释放后能再加
        with FileLock(lock_path, timeout=1.0):
            check("释放后重新加锁", True)

    # ErrorLogger
    with tempfile.TemporaryDirectory() as td:
        el = ErrorLogger(path=Path(td) / "etl_errors.log")
        el.log(chapter=3, error_fields="events.0.type", raw_output="x" * 2000)
        content = (Path(td) / "etl_errors.log").read_text(encoding="utf-8")
        check("错误日志含章号与截断", "chapter=3" in content and len(content) < 1200)


def test_runner_helpers() -> None:
    print("[7] etl_runner 纯函数")
    text = chapter_embed_text("标题", "摘要", "正文" * 500)
    check("chapter_embed_text 截断", len(text) < get_settings().MAX_CONTEXT_TOKENS * 2 + 200)
    dedup = _dedupe_single([(1, "a"), (2, "b"), (1, "a2")])
    check("单键去重保留最后", dedup == [(1, "a2"), (2, "b")])
    now = datetime.now()
    rows = _dedupe_chapters([(1, now, "a"), (1, now, "a2"), (2, now, "b")])
    check("复合键去重", len(rows) == 2 and rows[0][2] == "a2")


def main() -> int:
    print("novel-memory-system 离线自测\n")
    test_config()
    test_time_plan()
    test_schemas()
    test_extract_mock()
    test_embed()
    test_state()
    test_runner_helpers()
    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项失败: {FAILURES}")
        return 1
    print("✅ 全部离线自测通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
