"""从本地处理产物生成不含小说正文的静态仪表盘数据。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


STAGES = [
    (1, "原始资料录入", "complete", "8部TXT已原样导入，其他电子书格式待做版本核对"),
    (2, "原始文本质量检查", "in_progress", "已检查编码与噪声，缺章、重复章和乱码报告待完善"),
    (3, "结构化分片", "complete", "章节、证据单元和章节内窗口已生成并通过审计"),
    (4, "证据数据库与检索", "complete", "SQLite、中文短词与全文检索均已可用"),
    (5, "斗罗领域分类体系", "in_progress", "第一版词典已建立，类型约束和版本迁移规则待完善"),
    (6, "规则候选提取", "complete", "实体、领域词、事件触发词和疑似噪声已定位"),
    (7, "人物与实体词典扩充", "in_progress", "34个实体与53个别名已形成候选词典，同名消歧与自动发现待推进"),
    (8, "本地模型预处理", "in_progress", "主题标签可用，3B模型不能独立承担事实放行"),
    (9, "原子事实抽取", "in_progress", "事实Schema与104条均衡评测样本已建立，抽取器待评测"),
    (10, "证据校验", "in_progress", "逐字偏移、证据单元与信源范围校验已实现，语义审核待推进"),
    (11, "实体归并与关系整理", "pending", "待建立规范实体、别名和关系生命周期"),
    (12, "事件与时间线", "in_progress", "568条事件/状态候选与595个时间锚点已生成，事件角色仍待审核"),
    (13, "设定生命周期", "in_progress", "等级、年龄、相对时间和顺序锚点已定位，起止范围推断待实现"),
    (14, "冲突检测", "pending", "待区分时间差、版本差和真正设定冲突"),
    (15, "信源交叉验证", "pending", "L1-derived事实必须与独立L1证据交叉核对"),
    (16, "归纳总结", "pending", "只基于验证事实动态生成人物与设定摘要"),
    (17, "二次拆解", "pending", "按人物、能力、关系和事件继续展开"),
    (18, "查询与输出接口", "in_progress", "SQLite查询已具备，证据跳转和多格式输出待实现"),
]


def database_stats(database: Path) -> tuple[dict, list[dict]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    totals = {
        "sources": connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "units": connection.execute("SELECT COUNT(*) FROM text_units").fetchone()[0],
        "windows": connection.execute("SELECT COUNT(*) FROM context_windows").fetchone()[0],
        "window_units": connection.execute("SELECT COUNT(*) FROM window_units").fetchone()[0],
        "database_bytes": database.stat().st_size,
    }
    has_candidates = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='rule_candidates'"
    ).fetchone()[0]
    totals["unique_candidates"] = (
        connection.execute("SELECT COUNT(*) FROM rule_candidates").fetchone()[0]
        if has_candidates else 0
    )
    for table, key in (("entity_dictionary", "entities"), ("entity_aliases", "entity_aliases"),
                       ("model_entity_candidates", "model_entity_candidates")):
        exists = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        totals[key] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if exists else 0
    rows = connection.execute(
        """SELECT s.source_id,s.work_title,s.trust_level,
                  (SELECT COUNT(*) FROM text_units u WHERE u.source_id=s.source_id) AS units,
                  (SELECT COUNT(DISTINCT u.chapter_index) FROM text_units u WHERE u.source_id=s.source_id) AS chapters,
                  (SELECT COUNT(*) FROM context_windows w WHERE w.source_id=s.source_id) AS windows
           FROM sources s ORDER BY s.work_title"""
    ).fetchall()
    connection.close()
    return totals, [dict(row) for row in rows]


def jsonl_counts(root: Path, field: str) -> Counter:
    counts = Counter()
    if not root.exists():
        return counts
    for path in root.glob("*.jsonl"):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    counts[json.loads(line).get(field, "unknown")] += 1
    return counts


def jsonl_size(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(bool(line.strip()) for line in handle)


def classifications(root: Path) -> dict:
    rows = []
    if root.exists():
        for path in root.glob("*.jsonl"):
            with path.open("r", encoding="utf-8") as handle:
                rows.extend(json.loads(line) for line in handle if line.strip())
    return {
        "samples": len(rows),
        "relevant": sum(bool(row.get("relevant")) for row in rows),
        "explicit_event": sum(bool(row.get("contains_explicit_event")) for row in rows),
        "extract_facts": sum(bool(row.get("should_extract_facts")) for row in rows),
        "model": rows[0].get("model") if rows else None,
    }


def evaluation_stats(path: Path) -> dict:
    if not path.exists():
        return {"samples": 0, "works": 0, "reviewed": 0}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {
        "samples": len(rows),
        "works": len({row.get("work_id") for row in rows}),
        "reviewed": sum(row.get("review_status") != "unreviewed" for row in rows),
    }


def fact_preview(facts_path: Path, triage_path: Path) -> list[dict]:
    if not facts_path.exists():
        return []
    triage = {}
    if triage_path.exists():
        triage = {
            row["fact_id"]: row
            for row in (json.loads(line) for line in triage_path.read_text(encoding="utf-8").splitlines() if line.strip())
        }
    preview = []
    for line in facts_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        review = triage.get(row["fact_id"], {})
        preview.append({
            "fact_id": row["fact_id"], "subject": row["subject"], "predicate": row["predicate"],
            "object": row["object"], "work_id": row["work_id"], "trust_level": row["trust_level"],
            "context_type": review.get("context_type", "pending"),
            "review_bucket": review.get("review_bucket", "pending_review"),
        })
    return preview


def event_stats(facts_path: Path, triage_path: Path) -> dict:
    categories = Counter()
    buckets = Counter()
    preview = []
    if facts_path.exists():
        for line in facts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            categories[row.get("qualifiers", {}).get("event_category", "unknown")] += 1
            if len(preview) < 38:
                preview.append(row)
    triage = {}
    if triage_path.exists():
        for line in triage_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                triage[row["fact_id"]] = row
                buckets[row.get("review_bucket", "pending_review")] += 1
    formatted = []
    for row in preview:
        review = triage.get(row["fact_id"], {})
        formatted.append({
            "fact_id": row["fact_id"], "subject": row["subject"], "predicate": row["predicate"],
            "object": row["object"], "work_id": row["work_id"], "trust_level": row["trust_level"],
            "context_type": review.get("context_type", "pending"),
            "review_bucket": review.get("review_bucket", "pending_review"),
        })
    return {"total": sum(categories.values()), "categories": dict(categories), "buckets": dict(buckets), "preview": formatted}


def model_entity_stats(pilot_path: Path, shortlist_path: Path) -> dict:
    windows = accepted = rejected = errors = 0
    if pilot_path.exists():
        for line in pilot_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            windows += 1
            errors += row.get("status") == "model_error"
            accepted += len(row.get("accepted", []))
            rejected += len(row.get("rejected", []))
    shortlist = 0
    names = []
    if shortlist_path.exists():
        rows = json.loads(shortlist_path.read_text(encoding="utf-8")).get("accepted", [])
        shortlist = len(rows)
        names = [row["name"] for row in rows]
    return {"windows": windows, "proposals": accepted, "filtered": rejected,
            "errors": errors, "shortlist": shortlist, "shortlist_names": names}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成静态处理结果仪表盘数据")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    processed = data_root / "data" / "ip" / "douluo" / "processed"
    totals, works = database_stats(processed / "index" / "ip_evidence.sqlite3")
    candidate_counts = jsonl_counts(processed / "candidates" / "douluo", "candidate_type")
    model_stats = classifications(processed / "classifications" / "douluo_pilot")
    fact_evaluation = evaluation_stats(processed / "evaluation" / "douluo_fact_eval_v1.jsonl")
    event_evaluation = evaluation_stats(processed / "evaluation" / "douluo_event_eval_v1.jsonl")
    evaluation = {
        "samples": fact_evaluation["samples"] + event_evaluation["samples"],
        "works": max(fact_evaluation["works"], event_evaluation["works"]),
        "reviewed": fact_evaluation["reviewed"] + event_evaluation["reviewed"],
    }
    facts_path = processed / "facts" / "douluo_explicit_fact_candidates_v1.jsonl"
    triage_path = processed / "facts" / "douluo_fact_triage_v1.jsonl"
    event_facts_path = processed / "facts" / "douluo_event_fact_candidates_v1.jsonl"
    event_triage_path = processed / "facts" / "douluo_event_fact_triage_v1.jsonl"
    events = event_stats(event_facts_path, event_triage_path)
    temporal_counts = jsonl_counts(processed / "timeline", "anchor_type")
    model_entities = model_entity_stats(
        processed / "entities" / "douluo_model_entity_pilot_v2.jsonl",
        processed / "entities" / "douluo_model_entity_shortlist_v2.json",
    )
    fact_candidates = jsonl_size(facts_path) + events["total"]
    quality_path = processed / "quality" / "douluo_quality.json"
    quality = {"missing_numbers": 0, "duplicate_numbers": 0, "duplicate_titles": 0, "tiny_chapters": 0, "replacement_characters": 0}
    if quality_path.exists():
        report = json.loads(quality_path.read_text(encoding="utf-8"))
        for work in report.get("works", []):
            for key in quality:
                value = work.get(key, 0)
                quality[key] += len(value) if isinstance(value, list) else int(value or 0)
    payload = {
        "generated_from": str(data_root),
        "totals": totals,
        "works": works,
        "candidates": dict(candidate_counts),
        "candidate_total": sum(candidate_counts.values()),
        "overlap_duplicates_removed": max(0, sum(candidate_counts.values()) - totals["unique_candidates"]),
        "model_test": model_stats,
        "evaluation": evaluation,
        "fact_candidates": fact_candidates,
        "fact_preview": fact_preview(facts_path, triage_path) + events["preview"],
        "event_stats": events,
        "temporal": {"total": sum(temporal_counts.values()), "types": dict(temporal_counts)},
        "model_entities": model_entities,
        "quality": quality,
        "stages": [
            {"number": number, "name": name, "status": status, "summary": summary}
            for number, name, status, summary in STAGES
        ],
        "trust_note": "当前8部完整TXT均为来源未核实的第三方转录副本，trust_level=11，正式设定必须与L1原件交叉验证。",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.DASHBOARD_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "works": len(works), **totals}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
