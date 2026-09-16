"""Rule-based semantic triage for grounded facts; this never approves canon facts."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


UNCERTAINTY = ("可能", "或许", "似乎", "大概", "应该", "据说", "听说", "传说", "猜测", "恐怕")
TEMPORAL = ("现在", "当时", "曾经", "目前", "已经", "原本", "原来", "后来", "此时", "暂时", "刚刚")
REPORTING = ("说道", "说：", "道：", "问道", "回答", "告诉", "认为", "听见")


def _inside_chinese_quote(text: str, start: int) -> bool:
    opens = text[:start].count("“") + text[:start].count("‘")
    closes = text[:start].count("”") + text[:start].count("’")
    return opens > closes


def triage(database: Path, input_path: Path, output_path: Path) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    counts = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with input_path.open("r", encoding="utf-8") as source, output_path.open("w", encoding="utf-8", newline="\n") as target:
            for line in source:
                if not line.strip():
                    continue
                fact = json.loads(line)
                window = connection.execute(
                    "SELECT text FROM context_windows WHERE window_id=?", (fact["window_id"],)
                ).fetchone()
                if window is None:
                    bucket = "invalid_missing_window"
                    context_type = "unknown"
                    flags = ["window_not_found"]
                else:
                    text = window["text"]
                    start = fact["evidence_window_start"]
                    end = fact["evidence_window_end"]
                    nearby = text[max(0, start - 80):min(len(text), end + 80)]
                    quoted = _inside_chinese_quote(text, start)
                    uncertain = [word for word in UNCERTAINTY if word in nearby]
                    temporal = [word for word in TEMPORAL if word in nearby]
                    reporting = [word for word in REPORTING if word in nearby]
                    flags = []
                    if quoted:
                        flags.append("inside_quotation")
                    if uncertain:
                        flags.append("uncertainty_nearby")
                    if temporal:
                        flags.append("temporal_scope_nearby")
                    if reporting:
                        flags.append("reporting_context_nearby")
                    context_type = "dialogue_or_quotation" if quoted else "narrative_text"
                    if quoted or reporting:
                        bucket = "review_speaker_claim"
                    elif uncertain:
                        bucket = "review_uncertain_statement"
                    elif temporal:
                        bucket = "review_temporal_fact"
                    else:
                        bucket = "review_narrative_candidate"
                record = {
                    "fact_id": fact.get("fact_id"),
                    "work_id": fact.get("work_id"),
                    "chapter_id": fact.get("chapter_id"),
                    "window_id": fact.get("window_id"),
                    "context_type": context_type,
                    "review_bucket": bucket,
                    "flags": flags,
                    "canon_status": "candidate",
                    "semantic_review_status": "pending_review",
                    "method": "semantic_triage_rules_v1",
                }
                counts[bucket] += 1
                target.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {"input": sum(counts.values()), "output": str(output_path), "buckets": dict(counts)}
    finally:
        connection.close()
