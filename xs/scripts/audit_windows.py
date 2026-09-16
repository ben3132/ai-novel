"""流式审计 ContextWindow JSONL。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def audit(path: Path, max_chars: int) -> dict:
    lengths = []
    unit_counts = []
    trust_levels = set()
    source_ids = set()
    window_ids = set()
    errors = 0
    duplicate_ids = 0
    expected_sequence = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                window = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                continue
            text = window.get("text", "")
            lengths.append(len(text))
            unit_counts.append(len(window.get("unit_ids", [])))
            trust_levels.add(window.get("trust_level"))
            source_ids.add(window.get("source_id"))
            window_id = window.get("window_id")
            if window_id in window_ids:
                duplicate_ids += 1
            window_ids.add(window_id)
            if window.get("sequence_no") != expected_sequence:
                errors += 1
            expected_sequence += 1
            if not text or len(text) > max_chars:
                errors += 1
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != window.get("content_sha256"):
                errors += 1
            spans = window.get("unit_spans", [])
            if [span.get("unit_id") for span in spans] != window.get("unit_ids"):
                errors += 1
            previous_end = -1
            for span in spans:
                start, end = span.get("window_start"), span.get("window_end")
                if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                    errors += 1
                    continue
                if end > len(text) or start <= previous_end:
                    errors += 1
                previous_end = end
    lengths.sort()
    total = len(lengths)
    return {
        "file": str(path),
        "windows": total,
        "source_count": len(source_ids),
        "trust_levels": sorted(trust_levels),
        "length": {
            "min": lengths[0] if lengths else 0,
            "median": lengths[total // 2] if lengths else 0,
            "p90": lengths[int((total - 1) * 0.9)] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
            "mean": round(sum(lengths) / total, 2) if total else 0,
        },
        "mean_units_per_window": round(sum(unit_counts) / total, 2) if total else 0,
        "duplicate_window_ids": duplicate_ids,
        "validation_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审计上下文窗口 JSONL")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--max-chars", type=int, default=1600)
    args = parser.parse_args()
    failed = False
    for path in args.paths:
        result = audit(path.resolve(), args.max_chars)
        print(json.dumps(result, ensure_ascii=False))
        failed = failed or result["validation_errors"] > 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
