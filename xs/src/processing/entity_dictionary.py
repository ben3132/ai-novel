"""Build a reviewable entity/alias dictionary from grounded mention candidates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_dictionary(
  entity_id TEXT PRIMARY KEY,
  ip_domain TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  evidence_count INTEGER NOT NULL,
  work_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  method TEXT NOT NULL,
  UNIQUE(ip_domain,entity_type,canonical_name)
);
CREATE TABLE IF NOT EXISTS entity_aliases(
  entity_id TEXT NOT NULL REFERENCES entity_dictionary(entity_id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  mention_count INTEGER NOT NULL,
  evidence_count INTEGER NOT NULL,
  work_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY(entity_id,alias)
);
CREATE INDEX IF NOT EXISTS idx_entity_name ON entity_dictionary(canonical_name);
CREATE INDEX IF NOT EXISTS idx_alias_name ON entity_aliases(alias);
"""


def _entity_id(ip_domain: str, entity_type: str, canonical_name: str) -> str:
    raw = f"{ip_domain}\0{entity_type}\0{canonical_name}".encode("utf-8")
    return "entity-" + hashlib.sha256(raw).hexdigest()[:32]


def build_entity_dictionary(database: Path, output: Path | None = None, ip_domain: str = "douluo") -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM entity_aliases")
        connection.execute("DELETE FROM entity_dictionary")
        rows = connection.execute(
            """SELECT label AS entity_type,canonical_name,
                      SUM(occurrence_count) AS mention_count,COUNT(*) AS evidence_count,
                      COUNT(DISTINCT work_id) AS work_count
               FROM rule_candidates WHERE candidate_type='entity_mention'
               GROUP BY label,canonical_name ORDER BY label,canonical_name"""
        ).fetchall()
        exported = []
        for row in rows:
            entity_id = _entity_id(ip_domain, row["entity_type"], row["canonical_name"])
            connection.execute(
                "INSERT INTO entity_dictionary VALUES(?,?,?,?,?,?,?,?,?)",
                (entity_id, ip_domain, row["entity_type"], row["canonical_name"],
                 row["mention_count"], row["evidence_count"], row["work_count"],
                 "candidate", "configured_alias_mentions_v1"),
            )
            aliases = connection.execute(
                """SELECT mention_text AS alias,SUM(occurrence_count) AS mention_count,
                          COUNT(*) AS evidence_count,COUNT(DISTINCT work_id) AS work_count
                   FROM rule_candidates
                   WHERE candidate_type='entity_mention' AND label=? AND canonical_name=?
                   GROUP BY mention_text ORDER BY SUM(occurrence_count) DESC,mention_text""",
                (row["entity_type"], row["canonical_name"]),
            ).fetchall()
            connection.executemany(
                "INSERT INTO entity_aliases VALUES(?,?,?,?,?,?)",
                [(entity_id, alias["alias"], alias["mention_count"], alias["evidence_count"],
                  alias["work_count"], "candidate") for alias in aliases],
            )
            exported.append({**dict(row), "entity_id": entity_id, "status": "candidate", "aliases": [dict(a) for a in aliases]})
        connection.commit()
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("w", encoding="utf-8", newline="\n") as handle:
                for item in exported:
                    handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {
            "entities": len(exported),
            "aliases": sum(len(item["aliases"]) for item in exported),
            "cross_work_entities": sum(item["work_count"] > 1 for item in exported),
            "output": str(output) if output else None,
        }
    finally:
        connection.close()
