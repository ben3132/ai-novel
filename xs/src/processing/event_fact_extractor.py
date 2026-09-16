"""Extract conservative entity-trigger-object event candidates with exact evidence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from .evidence_validator import validate_evidence


TRIGGERS = {
    "acquire": ("获得", "得到", "获取", "吸收", "继承", "觉醒", "领悟", "学会"),
    "change": ("突破", "晋升", "提升", "进化", "蜕变", "恢复", "失去"),
    "conflict": ("击败", "战胜", "杀死", "击杀", "重创", "封印"),
    "life_state": ("出生", "死亡", "牺牲", "复活", "转生", "重生"),
    "relationship": ("结识", "拜师", "收徒", "成婚", "加入", "离开", "背叛"),
}
OBJECT_STOP = "。！？；\n\r，,：:”“\"‘’()（）"
INTERROGATIVES = ("什么", "谁", "哪", "多少", "为何", "怎么")
WEAK_OBJECTS = {"他", "她", "它", "他们", "她们", "它们", "这", "那", "这个", "那个"}


def _fact_id(unit_id: str, start: int, end: int, trigger: str) -> str:
    raw = f"{unit_id}\0{start}\0{end}\0{trigger}".encode("utf-8")
    return "event-candidate-" + hashlib.sha256(raw).hexdigest()[:32]


def extract_event_facts(
    database: Path, output: Path, limit: int | None = None, per_work_limit: int | None = None
) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    aliases = connection.execute(
        """SELECT a.alias,e.canonical_name,e.entity_type
           FROM entity_aliases a JOIN entity_dictionary e ON e.entity_id=a.entity_id
           WHERE length(a.alias)>=2 ORDER BY length(a.alias) DESC"""
    ).fetchall()
    alias_map = {row["alias"]: dict(row) for row in aliases}
    trigger_type = {trigger: kind for kind, triggers in TRIGGERS.items() for trigger in triggers}
    alias_pattern = "|".join(re.escape(alias) for alias in alias_map)
    trigger_pattern = "|".join(re.escape(trigger) for trigger in sorted(trigger_type, key=len, reverse=True))
    pattern = re.compile(
        rf"(?P<subject>{alias_pattern})(?P<link>[^{re.escape(OBJECT_STOP)}]{{0,12}}?)(?P<trigger>{trigger_pattern})(?P<object>[^{re.escape(OBJECT_STOP)}]{{1,30}})"
    )
    counts = Counter()
    work_counts = Counter()
    seen = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        rows = connection.execute(
            """SELECT u.unit_id,u.text,sw.work_id,c.chapter_id,s.trust_level
               FROM text_units u JOIN source_works sw ON sw.source_id=u.source_id
               JOIN chapters c ON c.source_id=u.source_id AND c.chapter_index=u.chapter_index
               JOIN sources s ON s.source_id=u.source_id
               WHERE u.unit_type='paragraph' ORDER BY u.source_id,u.raw_start"""
        )
        with output.open("w", encoding="utf-8", newline="\n") as target:
            for unit in rows:
                for match in pattern.finditer(unit["text"]):
                    if per_work_limit and work_counts[unit["work_id"]] >= per_work_limit:
                        break
                    counts["pattern_matches"] += 1
                    object_text = match.group("object").strip()
                    next_character = unit["text"][match.end():match.end() + 1]
                    if (not object_text or object_text in WEAK_OBJECTS
                            or any(word in object_text for word in INTERROGATIVES)
                            or next_character in {"?", "？"}):
                        counts["semantic_filter_rejected"] += 1
                        continue
                    location = connection.execute(
                        """SELECT wu.window_id,wu.window_start,cw.text
                           FROM window_units wu JOIN context_windows cw ON cw.window_id=wu.window_id
                           WHERE wu.unit_id=? AND wu.window_start+? >= 0
                             AND wu.window_start+? <= length(cw.text)
                           ORDER BY cw.sequence_no LIMIT 1""",
                        (unit["unit_id"], match.start(), match.end()),
                    ).fetchone()
                    if location is None:
                        counts["without_window"] += 1
                        continue
                    trigger = match.group("trigger")
                    fact_id = _fact_id(unit["unit_id"], match.start(), match.end(), trigger)
                    if fact_id in seen:
                        continue
                    seen.add(fact_id)
                    alias = alias_map[match.group("subject")]
                    payload = {
                        "fact_id": fact_id, "subject": match.group("subject"),
                        "predicate": trigger, "object": object_text,
                        "fact_type": "state_change" if trigger_type[trigger] == "change" else "event",
                        "work_id": unit["work_id"], "chapter_id": unit["chapter_id"],
                        "window_id": location["window_id"], "evidence_text": match.group(0),
                        "evidence_window_start": location["window_start"] + match.start(),
                        "evidence_window_end": location["window_start"] + match.end(),
                        "evidence_unit_ids": [unit["unit_id"]], "polarity": "positive",
                        "certainty": "reported",
                        "qualifiers": {
                            "event_category": trigger_type[trigger],
                            "canonical_subject_candidate": alias["canonical_name"],
                            "entity_type": alias["entity_type"],
                            "semantic_review_required": True,
                            "agent_role_unresolved": True,
                        },
                        "trust_level": unit["trust_level"],
                        "extraction_method": "entity_trigger_object_v1", "status": "candidate",
                    }
                    validation = validate_evidence(database, payload)
                    validation_data = validation.model_dump() if hasattr(validation, "model_dump") else validation.dict()
                    payload["grounding_validation"] = validation_data
                    if validation.grounding_status != "grounded":
                        counts["rejected"] += 1
                        continue
                    target.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts["grounded"] += 1
                    work_counts[unit["work_id"]] += 1
                    if limit and counts["grounded"] >= limit:
                        return {"output": str(output), **counts, "by_work": dict(work_counts)}
        return {"output": str(output), **counts, "by_work": dict(work_counts)}
    finally:
        connection.close()
