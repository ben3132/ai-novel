"""Conservative rule extractor for explicit, directly quoted fact candidates."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from .evidence_validator import validate_evidence


PREDICATES = ("武魂", "魂力", "魂环", "魂骨", "身份", "老师", "父亲", "母亲", "妻子", "丈夫", "宗门", "学院", "神位")
OBJECT_STOP = "。！？；\n\r，,：:”“\"‘’()（）"
INTERROGATIVES = ("什么", "谁", "哪", "多少", "几级", "为何", "怎么")
WEAK_OBJECTS = {"他", "她", "它", "他们", "她们", "它们", "这个", "那个", "这", "那"}


def _id(parts: list[str]) -> str:
    return "fact-candidate-" + hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]


def extract_explicit_facts(database: Path, output: Path, limit: int | None = None) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    aliases = connection.execute(
        """SELECT a.alias,e.canonical_name,e.entity_type
           FROM entity_aliases a JOIN entity_dictionary e ON e.entity_id=a.entity_id
           WHERE length(a.alias)>=2 ORDER BY length(a.alias) DESC"""
    ).fetchall()
    alias_map = {row["alias"]: dict(row) for row in aliases}
    subject_pattern = "|".join(re.escape(name) for name in alias_map)
    predicate_pattern = "|".join(map(re.escape, PREDICATES))
    pattern = re.compile(
        rf"(?P<subject>{subject_pattern})的(?P<predicate>{predicate_pattern})(?:就|乃|则)?(?:是|为)(?P<object>[^{re.escape(OBJECT_STOP)}]{{1,40}})"
    )
    counts = Counter()
    seen = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("w", encoding="utf-8", newline="\n") as target:
            units = connection.execute(
                """SELECT u.unit_id,u.text,u.source_id,sw.work_id,c.chapter_id,s.trust_level
                   FROM text_units u
                   JOIN source_works sw ON sw.source_id=u.source_id
                   JOIN chapters c ON c.source_id=u.source_id AND c.chapter_index=u.chapter_index
                   JOIN sources s ON s.source_id=u.source_id
                   WHERE u.unit_type='paragraph' ORDER BY u.source_id,u.raw_start"""
            )
            for unit in units:
                for match in pattern.finditer(unit["text"]):
                    counts["pattern_matches"] += 1
                    object_text = match.group("object").strip()
                    next_character = unit["text"][match.end():match.end() + 1]
                    if (
                        not object_text
                        or any(word in object_text for word in INTERROGATIVES)
                        or object_text in WEAK_OBJECTS
                        or next_character in {"?", "？"}
                    ):
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
                    start = location["window_start"] + match.start()
                    end = location["window_start"] + match.end()
                    identity = [unit["unit_id"], str(match.start()), str(match.end()), match.group("predicate")]
                    fact_id = _id(identity)
                    if fact_id in seen:
                        continue
                    seen.add(fact_id)
                    alias = alias_map[match.group("subject")]
                    fact_type = "relationship" if match.group("predicate") in {"老师", "父亲", "母亲", "妻子", "丈夫", "宗门", "学院"} else "attribute"
                    payload = {
                        "fact_id": fact_id,
                        "subject": match.group("subject"),
                        "predicate": match.group("predicate"),
                        "object": object_text,
                        "fact_type": fact_type,
                        "work_id": unit["work_id"],
                        "chapter_id": unit["chapter_id"],
                        "window_id": location["window_id"],
                        "evidence_text": match.group(0),
                        "evidence_window_start": start,
                        "evidence_window_end": end,
                        "evidence_unit_ids": [unit["unit_id"]],
                        "polarity": "positive",
                        "certainty": "reported",
                        "qualifiers": {
                            "canonical_subject_candidate": alias["canonical_name"],
                            "entity_type": alias["entity_type"],
                            "semantic_review_required": True,
                            "speaker_or_narrator_unresolved": True,
                        },
                        "trust_level": unit["trust_level"],
                        "extraction_method": "explicit_possessive_copula_v1",
                        "status": "candidate",
                    }
                    validation = validate_evidence(database, payload)
                    validation_data = validation.model_dump() if hasattr(validation, "model_dump") else validation.dict()
                    payload["grounding_validation"] = validation_data
                    if validation.grounding_status != "grounded":
                        counts["rejected"] += 1
                        continue
                    target.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts["grounded"] += 1
                    if limit is not None and counts["grounded"] >= limit:
                        return {"output": str(output), **counts}
        return {"output": str(output), **counts}
    finally:
        connection.close()
