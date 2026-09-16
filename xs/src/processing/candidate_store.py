"""把窗口候选映射到最小证据单元，并去除窗口重叠造成的重复。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_candidates(
  candidate_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  work_id TEXT NOT NULL REFERENCES works(work_id),
  chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id),
  unit_id TEXT NOT NULL REFERENCES text_units(unit_id),
  candidate_type TEXT NOT NULL,
  label TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  mention_text TEXT NOT NULL,
  unit_start INTEGER NOT NULL,
  unit_end INTEGER NOT NULL,
  trust_level INTEGER NOT NULL,
  status TEXT NOT NULL,
  occurrence_count INTEGER NOT NULL,
  first_window_id TEXT NOT NULL,
  method TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_entity ON rule_candidates(candidate_type,canonical_name);
CREATE INDEX IF NOT EXISTS idx_candidates_unit ON rule_candidates(unit_id,unit_start);
CREATE INDEX IF NOT EXISTS idx_candidates_work ON rule_candidates(work_id,chapter_id);
"""


UPSERT = """INSERT INTO rule_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(candidate_id) DO UPDATE SET occurrence_count=rule_candidates.occurrence_count+1"""


def _records(paths: Sequence[Path]) -> Iterable[dict]:
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def map_candidates(database: Path, candidate_paths: Sequence[Path]) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    counts = {"input": 0, "mapped": 0, "unmapped": 0, "invalid_evidence": 0}
    cached_window = None
    cached_spans = []
    batch = []
    try:
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM rule_candidates")
        for candidate in _records(candidate_paths):
            counts["input"] += 1
            window_id = candidate["window_id"]
            if window_id != cached_window:
                cached_window = window_id
                cached_spans = connection.execute(
                    """SELECT wu.unit_id,wu.window_start,wu.window_end,u.text,
                              sw.work_id,c.chapter_id
                       FROM window_units wu
                       JOIN text_units u ON u.unit_id=wu.unit_id
                       JOIN source_works sw ON sw.source_id=u.source_id
                       JOIN chapters c ON c.source_id=u.source_id AND c.chapter_index=u.chapter_index
                       WHERE wu.window_id=? ORDER BY wu.ordinal""",
                    (window_id,),
                ).fetchall()
            start, end = candidate["window_start"], candidate["window_end"]
            span = next((row for row in cached_spans if start >= row["window_start"] and end <= row["window_end"]), None)
            if span is None:
                counts["unmapped"] += 1
                continue
            unit_start = start - span["window_start"]
            unit_end = end - span["window_start"]
            if span["text"][unit_start:unit_end] != candidate["mention_text"]:
                counts["invalid_evidence"] += 1
                continue
            identity = "\0".join(map(str, (
                span["unit_id"], candidate["candidate_type"], candidate["label"],
                candidate["canonical_name"], unit_start, unit_end,
            ))).encode("utf-8")
            mapped_id = "evidence-candidate-" + hashlib.sha256(identity).hexdigest()[:32]
            batch.append((
                mapped_id, candidate["source_id"], span["work_id"], span["chapter_id"],
                span["unit_id"], candidate["candidate_type"], candidate["label"],
                candidate["canonical_name"], candidate["mention_text"], unit_start, unit_end,
                candidate["trust_level"], "candidate", 1, window_id, candidate["method"],
            ))
            counts["mapped"] += 1
            if len(batch) >= 2000:
                connection.executemany(UPSERT, batch)
                batch.clear()
        if batch:
            connection.executemany(UPSERT, batch)
        connection.commit()
        counts["unique"] = connection.execute("SELECT COUNT(*) FROM rule_candidates").fetchone()[0]
        counts["overlap_duplicates_removed"] = counts["mapped"] - counts["unique"]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"候选外键校验失败: {len(foreign_keys)}")
        return counts
    finally:
        connection.close()
