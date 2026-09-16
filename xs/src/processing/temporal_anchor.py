"""Locate explicit temporal/stage anchors near fact candidates without timeline inference."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Sequence


CN_NUM = r"零〇一二三四五六七八九十百千万两\d"
PATTERNS = {
    "relative_time": re.compile(rf"(?:[{CN_NUM}]{{1,8}}(?:年|月|天|日|小时|分钟)(?:前|后)|次日|翌日|随后|后来|此前|之后|当时|此时|现在|目前|曾经|原本|刚刚)"),
    "age": re.compile(rf"[{CN_NUM}]{{1,5}}岁"),
    "level": re.compile(rf"[{CN_NUM}]{{1,6}}级"),
    "sequence": re.compile(rf"第[{CN_NUM}]{{1,6}}次"),
}


def extract_temporal_anchors(database: Path, inputs: Sequence[Path], output: Path, radius: int = 80) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    counts = Counter()
    seen = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("w", encoding="utf-8", newline="\n") as target:
            for input_path in inputs:
                for line in input_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    fact = json.loads(line)
                    window = connection.execute("SELECT text FROM context_windows WHERE window_id=?", (fact["window_id"],)).fetchone()
                    if window is None:
                        counts["missing_window"] += 1
                        continue
                    left = max(0, fact["evidence_window_start"] - radius)
                    right = min(len(window["text"]), fact["evidence_window_end"] + radius)
                    nearby = window["text"][left:right]
                    fact_has_anchor = False
                    for anchor_type, pattern in PATTERNS.items():
                        for match in pattern.finditer(nearby):
                            start, end = left + match.start(), left + match.end()
                            identity = f"{fact['fact_id']}\0{anchor_type}\0{start}\0{end}"
                            anchor_id = "anchor-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
                            if anchor_id in seen:
                                continue
                            seen.add(anchor_id)
                            target.write(json.dumps({
                                "anchor_id": anchor_id, "fact_id": fact["fact_id"],
                                "work_id": fact["work_id"], "chapter_id": fact["chapter_id"],
                                "window_id": fact["window_id"], "anchor_type": anchor_type,
                                "anchor_text": match.group(0), "window_start": start, "window_end": end,
                                "relation_to_fact": "nearby_unresolved", "status": "candidate",
                                "method": "explicit_temporal_anchor_v1",
                            }, ensure_ascii=False, separators=(",", ":")) + "\n")
                            counts[anchor_type] += 1
                            fact_has_anchor = True
                    counts["facts_with_anchor" if fact_has_anchor else "facts_without_anchor"] += 1
        return {"output": str(output), **counts}
    finally:
        connection.close()
