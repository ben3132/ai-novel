"""SQLite 证据索引：结构化存储 TextUnit、ContextWindow 与全文检索。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Sequence


SCHEMA_VERSION = 1


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources(
    source_id TEXT PRIMARY KEY,
    trust_level INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    ip_domain TEXT NOT NULL,
    url TEXT NOT NULL,
    work_title TEXT,
    work_version TEXT,
    canon_scope TEXT
);
CREATE TABLE text_units(
    unit_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    sequence_no INTEGER NOT NULL,
    unit_type TEXT NOT NULL,
    chapter_index INTEGER,
    chapter_title TEXT,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    text_start INTEGER NOT NULL,
    text_end INTEGER NOT NULL,
    raw_start INTEGER,
    raw_end INTEGER,
    extra_meta_json TEXT NOT NULL,
    UNIQUE(source_id, sequence_no)
);
CREATE INDEX idx_units_source_chapter ON text_units(source_id, chapter_index, sequence_no);
CREATE INDEX idx_units_hash ON text_units(content_sha256);
CREATE TABLE context_windows(
    window_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    sequence_no INTEGER NOT NULL,
    chapter_index INTEGER,
    chapter_title TEXT,
    text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    extra_meta_json TEXT NOT NULL,
    UNIQUE(source_id, sequence_no)
);
CREATE INDEX idx_windows_source_chapter ON context_windows(source_id, chapter_index, sequence_no);
CREATE TABLE window_units(
    window_id TEXT NOT NULL REFERENCES context_windows(window_id) ON DELETE CASCADE,
    unit_id TEXT NOT NULL REFERENCES text_units(unit_id),
    ordinal INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    window_end INTEGER NOT NULL,
    PRIMARY KEY(window_id, ordinal)
);
CREATE INDEX idx_window_units_unit ON window_units(unit_id);
CREATE VIRTUAL TABLE windows_fts USING fts5(
    window_id UNINDEXED,
    work_title,
    chapter_title,
    text,
    tokenize='trigram'
);
"""


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _json_lines(paths: Sequence[Path]) -> Iterator[dict]:
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def build_index(database: Path, unit_paths: Sequence[Path], window_paths: Sequence[Path]) -> dict:
    """使用临时数据库完整重建；成功后原子替换目标。"""
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(database.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    connection = connect(temporary)
    counts = {"sources": 0, "units": 0, "windows": 0, "window_units": 0}
    try:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        unit_batch = []
        for unit in _json_lines(unit_paths):
            meta = unit.get("extra_meta", {})
            source_meta = meta.get("source_extra_meta", {})
            before = connection.total_changes
            connection.execute(
                "INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?,?)",
                (
                    unit["source_id"], unit["trust_level"], unit["source_type"],
                    unit["ip_domain"], unit["url"], source_meta.get("work_title"),
                    source_meta.get("work_version"), source_meta.get("canon_scope"),
                ),
            )
            if connection.total_changes > before:
                counts["sources"] += 1
            unit_batch.append((
                unit["unit_id"], unit["source_id"], unit["sequence_no"], unit["unit_type"],
                meta.get("chapter_index"), meta.get("chapter_title"), unit["text"],
                unit["content_sha256"], unit["text_start"], unit["text_end"],
                unit.get("raw_start"), unit.get("raw_end"),
                json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            ))
            if len(unit_batch) >= 2000:
                connection.executemany(
                    "INSERT INTO text_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", unit_batch
                )
                counts["units"] += len(unit_batch)
                unit_batch.clear()
        if unit_batch:
            connection.executemany("INSERT INTO text_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", unit_batch)
            counts["units"] += len(unit_batch)

        window_batch = []
        mapping_batch = []
        fts_batch = []
        for window in _json_lines(window_paths):
            meta = window.get("extra_meta", {})
            window_batch.append((
                window["window_id"], window["source_id"], window["sequence_no"],
                window.get("chapter_index"), window.get("chapter_title"), window["text"],
                window["content_sha256"], json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
            ))
            work_title = meta.get("work_title") or ""
            fts_batch.append((window["window_id"], work_title, window.get("chapter_title") or "", window["text"]))
            for ordinal, span in enumerate(window["unit_spans"]):
                mapping_batch.append((
                    window["window_id"], span["unit_id"], ordinal,
                    span["window_start"], span["window_end"],
                ))
            if len(window_batch) >= 1000:
                connection.executemany("INSERT INTO context_windows VALUES(?,?,?,?,?,?,?,?)", window_batch)
                connection.executemany("INSERT INTO windows_fts VALUES(?,?,?,?)", fts_batch)
                connection.executemany("INSERT INTO window_units VALUES(?,?,?,?,?)", mapping_batch)
                counts["windows"] += len(window_batch)
                counts["window_units"] += len(mapping_batch)
                window_batch.clear(); fts_batch.clear(); mapping_batch.clear()
        if window_batch:
            connection.executemany("INSERT INTO context_windows VALUES(?,?,?,?,?,?,?,?)", window_batch)
            connection.executemany("INSERT INTO windows_fts VALUES(?,?,?,?)", fts_batch)
            connection.executemany("INSERT INTO window_units VALUES(?,?,?,?,?)", mapping_batch)
            counts["windows"] += len(window_batch)
            counts["window_units"] += len(mapping_batch)
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"SQLite 校验失败: integrity={integrity}, foreign_keys={len(foreign_keys)}")
    except Exception:
        connection.close()
        if temporary.exists():
            temporary.unlink()
        raise
    connection.close()
    temporary.replace(database)
    return counts


def search(database: Path, query: str, limit: int = 10) -> Iterable[dict]:
    """中文短词（少于3字符）用 LIKE；其余优先 trigram FTS5。"""
    if not query.strip():
        return []
    connection = connect(database)
    try:
        if len(query.strip()) < 3:
            rows = connection.execute(
                """SELECT w.window_id,s.work_title,w.chapter_title,w.text,s.trust_level,s.url
                   FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                   WHERE w.text LIKE ? ORDER BY w.source_id,w.sequence_no LIMIT ?""",
                (f"%{query.strip()}%", limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT w.window_id,s.work_title,w.chapter_title,w.text,s.trust_level,s.url
                   FROM windows_fts f JOIN context_windows w ON w.window_id=f.window_id
                   JOIN sources s ON s.source_id=w.source_id
                   WHERE windows_fts MATCH ? ORDER BY bm25(windows_fts) LIMIT ?""",
                (f'"{query.strip().replace(chr(34), chr(34) * 2)}"', limit),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
