"""Store consolidated model entity candidates separately from confirmed entities."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS model_entity_candidates(
  candidate_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  proposal_window_count INTEGER NOT NULL,
  proposal_work_count INTEGER NOT NULL,
  corpus_evidence_units INTEGER NOT NULL,
  corpus_work_count INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status='candidate'),
  method TEXT NOT NULL,
  UNIQUE(name,entity_type)
);
CREATE TABLE IF NOT EXISTS model_entity_candidate_windows(
  candidate_id TEXT NOT NULL REFERENCES model_entity_candidates(candidate_id) ON DELETE CASCADE,
  window_id TEXT NOT NULL REFERENCES context_windows(window_id),
  PRIMARY KEY(candidate_id,window_id)
);
CREATE INDEX IF NOT EXISTS idx_model_entity_name ON model_entity_candidates(name);
"""


def store_model_entities(database: Path, shortlist: Path) -> dict:
    payload = json.loads(shortlist.read_text(encoding="utf-8"))
    rows = payload.get("accepted", [])
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM model_entity_candidate_windows")
        connection.execute("DELETE FROM model_entity_candidates")
        missing_windows = 0
        for row in rows:
            candidate_id = "model-entity-candidate-" + hashlib.sha256(
                f"{row['entity_type']}\0{row['name']}".encode("utf-8")
            ).hexdigest()[:32]
            connection.execute(
                "INSERT INTO model_entity_candidates VALUES(?,?,?,?,?,?,?,?,?)",
                (candidate_id, row["name"], row["entity_type"], row["proposal_window_count"],
                 row["proposal_work_count"], row["corpus_evidence_units"], row["corpus_work_count"],
                 "candidate", row["method"]),
            )
            for window_id in row["window_ids"]:
                exists = connection.execute("SELECT 1 FROM context_windows WHERE window_id=?", (window_id,)).fetchone()
                if not exists:
                    missing_windows += 1
                    continue
                connection.execute("INSERT INTO model_entity_candidate_windows VALUES(?,?)", (candidate_id, window_id))
        connection.commit()
        stored = connection.execute("SELECT COUNT(*) FROM model_entity_candidates").fetchone()[0]
        links = connection.execute("SELECT COUNT(*) FROM model_entity_candidate_windows").fetchone()[0]
        return {"stored": stored, "window_links": links, "missing_windows": missing_windows}
    finally:
        connection.close()
