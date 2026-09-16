"""从规则候选密集窗口构建跨作品平衡的事实抽取评测集。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def build(database: Path, per_work: int) -> list[dict]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    samples = []
    works = connection.execute("SELECT work_id,title FROM works ORDER BY sequence_no").fetchall()
    for work in works:
        rows = connection.execute(
            """SELECT rc.first_window_id AS window_id,rc.chapter_id,
                      COUNT(*) AS candidate_count,COUNT(DISTINCT rc.canonical_name) AS distinct_terms
               FROM rule_candidates rc WHERE rc.work_id=?
               GROUP BY rc.first_window_id,rc.chapter_id
               ORDER BY distinct_terms DESC,candidate_count DESC LIMIT ?""",
            (work["work_id"], per_work),
        ).fetchall()
        for row in rows:
            window = connection.execute(
                "SELECT text,chapter_title,source_id FROM context_windows WHERE window_id=?",
                (row["window_id"],),
            ).fetchone()
            terms = connection.execute(
                """SELECT candidate_type,canonical_name,COUNT(*) AS n
                   FROM rule_candidates rc JOIN window_units wu ON wu.unit_id=rc.unit_id
                   WHERE wu.window_id=? GROUP BY candidate_type,canonical_name
                   ORDER BY n DESC,canonical_name LIMIT 30""",
                (row["window_id"],),
            ).fetchall()
            sample_id = "eval-" + hashlib.sha256(row["window_id"].encode("utf-8")).hexdigest()[:24]
            samples.append({
                "sample_id": sample_id,
                "work_id": work["work_id"],
                "work_title": work["title"],
                "source_id": window["source_id"],
                "chapter_id": row["chapter_id"],
                "chapter_title": window["chapter_title"],
                "window_id": row["window_id"],
                "text": window["text"],
                "rule_candidate_count": row["candidate_count"],
                "candidate_terms": [dict(term) for term in terms],
                "gold_facts": [],
                "review_status": "unreviewed",
            })
    connection.close()
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="构建事实抽取人工评测集")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-work", type=int, default=13)
    args = parser.parse_args()
    samples = build(args.database.resolve(), args.per_work)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"output": str(args.output), "samples": len(samples)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
