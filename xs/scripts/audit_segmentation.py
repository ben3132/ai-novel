"""流式审计 processed TextUnit JSONL，不修改任何数据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


NOISE_RE = re.compile(
    r"(?i)https?://|www\.|笔趣阁|请记住本站|手机用户请|本书来自|下载站|"
    r"加入书签|方便下次阅读|最新网址|无弹窗"
)


def audit(path: Path, max_chars: int) -> dict:
    counts = Counter()
    lengths: list[int] = []
    trust_levels = set()
    source_ids = set()
    seen_ids = set()
    seen_content_hashes = set()
    expected_sequence: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            counts["units"] += 1
            try:
                unit = json.loads(line)
            except json.JSONDecodeError:
                counts["invalid_json"] += 1
                continue
            text = unit.get("text", "")
            length = len(text)
            lengths.append(length)
            source_id = unit.get("source_id")
            source_ids.add(source_id)
            trust_levels.add(unit.get("trust_level"))
            if not text:
                counts["empty"] += 1
            if length < 20:
                counts["under_20"] += 1
            if length < 80:
                counts["under_80"] += 1
            if length > max_chars:
                counts["over_limit"] += 1
            if NOISE_RE.search(text):
                counts["suspected_noise"] += 1
            if unit.get("unit_type") == "chapter":
                counts["chapter_units"] += 1
            unit_id = unit.get("unit_id")
            if unit_id in seen_ids:
                counts["duplicate_unit_ids"] += 1
            seen_ids.add(unit_id)
            content_hash = unit.get("content_sha256")
            actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if content_hash != actual_hash:
                counts["invalid_hash"] += 1
            if content_hash in seen_content_hashes:
                counts["duplicate_content"] += 1
            seen_content_hashes.add(content_hash)
            if unit.get("text_end") - unit.get("text_start") != length:
                counts["invalid_derived_range"] += 1
            sequence = unit.get("sequence_no")
            expected = expected_sequence.get(source_id, 0)
            if sequence != expected:
                counts["sequence_gaps"] += 1
            expected_sequence[source_id] = sequence + 1
            if unit.get("raw_start") is None or unit.get("raw_end") is None:
                counts["missing_raw_range"] += 1
            elif unit["raw_start"] < 0 or unit["raw_end"] < unit["raw_start"]:
                counts["invalid_raw_range"] += 1
    lengths.sort()
    total = counts["units"]
    return {
        "file": str(path),
        "units": total,
        "source_count": len(source_ids),
        "trust_levels": sorted(trust_levels),
        "chapter_units": counts["chapter_units"],
        "length": {
            "min": lengths[0] if lengths else 0,
            "median": lengths[total // 2] if lengths else 0,
            "p90": lengths[int((total - 1) * 0.9)] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
            "mean": round(sum(lengths) / total, 2) if total else 0,
        },
        "under_20": counts["under_20"],
        "under_80": counts["under_80"],
        "suspected_noise": counts["suspected_noise"],
        "duplicate_content": counts["duplicate_content"],
        "validation_errors": sum(
            counts[name]
            for name in (
                "invalid_json", "empty", "over_limit", "duplicate_unit_ids",
                "invalid_hash", "invalid_derived_range", "sequence_gaps",
                "missing_raw_range", "invalid_raw_range",
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审计分片 JSONL")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--max-chars", type=int, default=1200)
    args = parser.parse_args()
    failed = False
    for path in args.paths:
        result = audit(path.resolve(), args.max_chars)
        print(json.dumps(result, ensure_ascii=False))
        failed = failed or result["validation_errors"] > 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
