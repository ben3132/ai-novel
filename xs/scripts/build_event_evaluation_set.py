"""Build a work-balanced review set from grounded event candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build balanced event fact evaluation JSONL")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-work", type=int, default=10)
    args = parser.parse_args()
    by_work = defaultdict(list)
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_work[row["work_id"]].append(row)
    selected = []
    for work_id in sorted(by_work):
        rows = sorted(by_work[work_id], key=lambda row: (row["qualifiers"]["event_category"], row["fact_id"]))
        categories = defaultdict(list)
        for row in rows:
            categories[row["qualifiers"]["event_category"]].append(row)
        ordered = []
        while any(categories.values()):
            for category in sorted(categories):
                if categories[category]:
                    ordered.append(categories[category].pop(0))
        for row in ordered[:args.per_work]:
            selected.append({
                "sample_id": "event-eval-" + hashlib.sha256(row["fact_id"].encode()).hexdigest()[:24],
                "fact_candidate": {key: value for key, value in row.items() if key != "grounding_validation"},
                "grounding_status": row["grounding_validation"]["grounding_status"],
                "gold_decision": None,
                "gold_subject": None,
                "gold_predicate": None,
                "gold_object": None,
                "gold_context_type": None,
                "review_notes": "",
                "review_status": "unreviewed",
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"output": str(args.output), "samples": len(selected), "works": len(by_work)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
