"""从证据单元建立稳定作品、卷和章节层级。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict


VOLUME_RE = re.compile(r"^(第[零〇一二三四五六七八九十百千万两\d]+[集卷部])\s*([^第]{0,30})")


HIERARCHY_SCHEMA = """
CREATE TABLE IF NOT EXISTS works(
  work_id TEXT PRIMARY KEY,
  title TEXT NOT NULL UNIQUE,
  sequence_no INTEGER NOT NULL,
  continuity TEXT NOT NULL,
  kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_works(
  source_id TEXT PRIMARY KEY REFERENCES sources(source_id) ON DELETE CASCADE,
  work_id TEXT NOT NULL REFERENCES works(work_id)
);
CREATE TABLE IF NOT EXISTS volumes(
  volume_id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(work_id),
  volume_key TEXT NOT NULL,
  title TEXT NOT NULL,
  UNIQUE(work_id,volume_key)
);
CREATE TABLE IF NOT EXISTS chapters(
  chapter_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  work_id TEXT NOT NULL REFERENCES works(work_id),
  volume_id TEXT REFERENCES volumes(volume_id),
  chapter_index INTEGER NOT NULL,
  title TEXT,
  section_type TEXT NOT NULL,
  first_unit_sequence INTEGER NOT NULL,
  last_unit_sequence INTEGER NOT NULL,
  unit_count INTEGER NOT NULL,
  char_count INTEGER NOT NULL,
  UNIQUE(source_id,chapter_index)
);
CREATE INDEX IF NOT EXISTS idx_chapters_work ON chapters(work_id,chapter_index);
"""


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\0".join(map(str, parts)).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def build_hierarchy(database: Path, work_config: Dict[str, dict]) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    counts = {"works": 0, "volumes": 0, "chapters": 0, "front_matter": 0}
    try:
        connection.executescript(HIERARCHY_SCHEMA)
        connection.execute("DELETE FROM chapters")
        connection.execute("DELETE FROM volumes")
        connection.execute("DELETE FROM source_works")
        connection.execute("DELETE FROM works")
        for title, meta in work_config.items():
            connection.execute(
                "INSERT INTO works VALUES(?,?,?,?,?)",
                (meta["work_id"], title, meta["sequence"], meta["continuity"], meta["kind"]),
            )
            counts["works"] += 1
        sources = connection.execute("SELECT source_id,work_title FROM sources ORDER BY source_id").fetchall()
        for source in sources:
            title = source["work_title"]
            if title not in work_config:
                raise ValueError(f"作品配置缺失: {title!r}")
            work_id = work_config[title]["work_id"]
            connection.execute("INSERT INTO source_works VALUES(?,?)", (source["source_id"], work_id))
            rows = connection.execute(
                """SELECT chapter_index,chapter_title,MIN(sequence_no),MAX(sequence_no),COUNT(*),SUM(LENGTH(text))
                   FROM text_units WHERE source_id=? GROUP BY chapter_index,chapter_title ORDER BY chapter_index""",
                (source["source_id"],),
            ).fetchall()
            current_volume_id = None
            for row in rows:
                chapter_index, chapter_title = row[0], row[1]
                section_type = "chapter" if chapter_title else "front_matter"
                if section_type == "front_matter":
                    counts["front_matter"] += 1
                volume_match = VOLUME_RE.match(chapter_title or "")
                if volume_match:
                    volume_key = volume_match.group(1)
                    volume_title = (volume_key + " " + volume_match.group(2).strip()).strip()
                    current_volume_id = _stable_id("volume", work_id, volume_key)
                    before = connection.total_changes
                    connection.execute(
                        "INSERT OR IGNORE INTO volumes VALUES(?,?,?,?)",
                        (current_volume_id, work_id, volume_key, volume_title),
                    )
                    if connection.total_changes > before:
                        counts["volumes"] += 1
                # 同一作品可以有原著、不同版本、PDF逐页派生等多个 source。
                # chapter_id 必须包含来源维度；(work_id, chapter_index) 并不唯一。
                chapter_id = _stable_id("section", work_id, source["source_id"], chapter_index)
                connection.execute(
                    "INSERT INTO chapters VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        chapter_id, source["source_id"], work_id, current_volume_id,
                        chapter_index, chapter_title, section_type,
                        row[2], row[3], row[4], row[5],
                    ),
                )
                counts["chapters"] += 1
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"层级数据库校验失败: {integrity}, foreign_keys={len(foreign_keys)}")
        return counts
    finally:
        connection.close()
