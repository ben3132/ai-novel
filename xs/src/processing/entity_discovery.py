"""Discover conservative entity-name candidates from explicit possessive clauses."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path


PREDICATES = "武魂|魂力|魂环|魂骨|身份|老师|父亲|母亲|妻子|丈夫|宗门|学院|神位"
PATTERN = re.compile(rf"(?:^|[。！？；：，、\n\r“‘])(?P<name>[\u4e00-\u9fff]{{2,4}})的(?P<predicate>{PREDICATES})(?:就|乃|则)?(?:是|为)")
BAD_NAME_PARTS = ("什么", "这个", "那个", "自己", "他们", "她们", "我们", "你们", "真正", "唯一", "现在", "原本")
BAD_PREFIXES = ("如果", "就算", "无论", "可是", "但", "而", "那么", "所以", "因为", "对于", "至于")
BAD_SUFFIXES = ("你", "我", "他", "她", "它", "对手", "本人", "大家", "众人")


def discover(database: Path, output: Path, minimum_evidence: int = 2) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    known = {row[0] for row in connection.execute("SELECT alias FROM entity_aliases")}
    found: dict[str, dict] = defaultdict(lambda: {"evidence": set(), "works": set(), "predicates": set(), "samples": []})
    try:
        rows = connection.execute(
            """SELECT u.unit_id,u.text,sw.work_id,c.chapter_id
               FROM text_units u JOIN source_works sw ON sw.source_id=u.source_id
               JOIN chapters c ON c.source_id=u.source_id AND c.chapter_index=u.chapter_index
               WHERE u.unit_type='paragraph' ORDER BY u.source_id,u.raw_start"""
        )
        for row in rows:
            for match in PATTERN.finditer(row["text"]):
                name = match.group("name")
                if (
                    name in known
                    or any(part in name for part in BAD_NAME_PARTS)
                    or name.startswith(BAD_PREFIXES)
                    or name.endswith(BAD_SUFFIXES)
                ):
                    continue
                item = found[name]
                item["evidence"].add(row["unit_id"])
                item["works"].add(row["work_id"])
                item["predicates"].add(match.group("predicate"))
                if len(item["samples"]) < 3:
                    item["samples"].append({
                        "unit_id": row["unit_id"], "chapter_id": row["chapter_id"],
                        "work_id": row["work_id"], "evidence_text": match.group(0)[1:] if match.group(0)[0] in "。！？；：，、\n\r“‘" else match.group(0),
                    })
        records = []
        for name, item in found.items():
            if len(item["evidence"]) < minimum_evidence:
                continue
            candidate_id = "entity-discovery-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
            records.append({
                "discovery_id": candidate_id,
                "name": name,
                "entity_type": "person_candidate",
                "evidence_count": len(item["evidence"]),
                "work_count": len(item["works"]),
                "work_ids": sorted(item["works"]),
                "predicate_hints": sorted(item["predicates"]),
                "evidence_samples": item["samples"],
                "status": "candidate",
                "review_reason": "not_in_configured_entity_dictionary",
                "method": "possessive_clause_discovery_v1",
            })
        records.sort(key=lambda row: (-row["evidence_count"], row["name"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {"output": str(output), "candidates": len(records), "minimum_evidence": minimum_evidence}
    finally:
        connection.close()
