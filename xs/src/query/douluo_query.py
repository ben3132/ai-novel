"""Read-only evidence retrieval; work hierarchy is an optional enhancement."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Sequence


WORK_ALIASES = {
    "斗一": "douluo_1", "斗罗一": "douluo_1", "douluo1": "douluo_1",
    "斗二": "douluo_2", "斗罗二": "douluo_2", "绝世唐门": "douluo_2", "douluo2": "douluo_2",
    "斗三": "douluo_3", "斗罗三": "douluo_3", "龙王传说": "douluo_3", "douluo3": "douluo_3",
    "斗四": "douluo_4", "斗罗四": "douluo_4", "终极斗罗": "douluo_4", "douluo4": "douluo_4",
    "斗五": "douluo_5", "斗罗五": "douluo_5", "重生唐三": "douluo_5", "douluo5": "douluo_5",
    "神界传说": "douluo_divine_realm", "唐门英雄传": "douluo_tangmen_heroes",
    "史莱克天团": "douluo_shrek_team",
}
QUESTION_SPLIT = re.compile(
    r"(?:请问|告诉我|介绍一下|关于|相关|全部|所有|分别|到底|究竟|为什么|为何|怎么|如何|"
    r"是什么|有哪些|有多少|是谁|在哪里|哪一|是否|的|了|吗|呢|？|\?|，|,|。|：|:)"
)
REQUIRED_TABLES = {"sources", "context_windows", "windows_fts"}
HIERARCHY_TABLES = {"works", "source_works", "chapters"}


class QueryDatabaseError(RuntimeError):
    pass


def normalize_work_ids(values: Sequence[str] | None, aliases: dict[str, str] | None = None) -> list[str]:
    if not values:
        return []
    normalized = []
    for value in values:
        key = value.strip()
        mapping = WORK_ALIASES if aliases is None else aliases
        work_id = mapping.get(key, mapping.get(key.lower(), key))
        if work_id not in normalized:
            normalized.append(work_id)
    return normalized


class DouluoQueryEngine:
    def __init__(
        self, database: Path | str, ip_domain: str = "douluo",
        work_aliases: dict[str, str] | None = None,
    ):
        self.database = Path(database).expanduser().resolve()
        self.ip_domain = ip_domain.strip()
        if not self.ip_domain:
            raise ValueError("ip_domain must not be empty")
        self.work_aliases = WORK_ALIASES if work_aliases is None and self.ip_domain == "douluo" else (work_aliases or {})
        if not self.database.is_file():
            raise QueryDatabaseError(f"Evidence database not found: {self.database}")
        self._validate_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_schema(self) -> None:
        with closing(self._connect()) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise QueryDatabaseError(f"Evidence database is missing tables: {sorted(missing)}")
        self.has_hierarchy = HIERARCHY_TABLES <= tables

    def _hierarchy_sql(self) -> tuple[str, str]:
        """Return optional columns and joins without making hierarchy a search prerequisite."""
        if self.has_hierarchy:
            return (
                "sw.work_id,c.chapter_id",
                "LEFT JOIN source_works sw ON sw.source_id=w.source_id "
                "LEFT JOIN chapters c ON c.source_id=w.source_id AND c.chapter_index=w.chapter_index",
            )
        return "NULL AS work_id,NULL AS chapter_id", ""

    def list_works(self) -> list[dict]:
        with closing(self._connect()) as connection:
            if self.has_hierarchy:
                rows = connection.execute(
                """SELECT w.work_id,w.title,w.sequence_no,w.continuity,w.kind,
                          COUNT(DISTINCT c.chapter_id) AS chapter_count
                   FROM works w JOIN source_works sw ON sw.work_id=w.work_id
                   JOIN sources s ON s.source_id=sw.source_id
                   LEFT JOIN chapters c ON c.work_id=w.work_id
                   WHERE s.ip_domain=?
                   GROUP BY w.work_id ORDER BY w.sequence_no""", (self.ip_domain,)
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT s.work_title AS work_id,s.work_title AS title,
                              0 AS sequence_no,'unknown' AS continuity,
                              'document' AS kind,0 AS chapter_count
                       FROM sources s WHERE s.ip_domain=?
                       GROUP BY s.work_title ORDER BY s.work_title""",
                    (self.ip_domain,),
                ).fetchall()
        return [dict(row) for row in rows]

    def corpus_status(self) -> dict:
        """Return unambiguous processed-corpus counts; derived pages are not sources."""
        with closing(self._connect()) as connection:
            source_records = connection.execute(
                "SELECT COUNT(*) FROM sources WHERE ip_domain=?", (self.ip_domain,)
            ).fetchone()[0]
            text_units = connection.execute(
                """SELECT COUNT(*) FROM text_units u JOIN sources s ON s.source_id=u.source_id
                   WHERE s.ip_domain=?""", (self.ip_domain,),
            ).fetchone()[0]
            windows = connection.execute(
                """SELECT COUNT(*) FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                   WHERE s.ip_domain=?""", (self.ip_domain,),
            ).fetchone()[0]
            artifact_ids = set()
            document_unit_ids = set()
            for row in connection.execute(
                """SELECT u.source_id,u.extra_meta_json FROM text_units u
                   JOIN sources s ON s.source_id=u.source_id WHERE s.ip_domain=?""",
                (self.ip_domain,),
            ):
                meta = __import__("json").loads(row["extra_meta_json"] or "{}")
                source_meta = meta.get("source_extra_meta") or {}
                artifact_ids.add(source_meta.get("source_artifact_id") or row["source_id"])
                if source_meta.get("record_role") == "derived_document_unit":
                    document_unit_ids.add(row["source_id"])
        return {
            "ip_domain": self.ip_domain,
            "scope": "processed_evidence_database",
            "source_artifact_count": len(artifact_ids),
            "processed_source_record_count": source_records,
            "document_unit_count": len(document_unit_ids),
            "text_unit_count": text_units,
            "context_window_count": windows,
            "warning": "processed_source_record_count includes technical derived records; do not report it as source count",
        }

    def get_windows(self, window_ids: Sequence[str]) -> dict[str, dict]:
        """Hydrate vector hits from the canonical SQLite evidence store."""
        if not window_ids:
            return {}
        result: dict[str, dict] = {}
        hierarchy_columns, hierarchy_joins = self._hierarchy_sql()
        with closing(self._connect()) as connection:
            for offset in range(0, len(window_ids), 800):
                chunk = list(window_ids[offset:offset + 800])
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""SELECT w.window_id,w.text,w.sequence_no,w.chapter_index,w.chapter_title,
                               s.source_id,s.work_title,s.trust_level,s.source_type,s.url,
                               {hierarchy_columns}
                        FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                        {hierarchy_joins}
                        WHERE s.ip_domain=? AND w.window_id IN ({placeholders})""", [self.ip_domain, *chunk],
                ).fetchall()
                result.update((row["window_id"], dict(row)) for row in rows)
        return result

    def _vocabulary(self, question: str) -> list[str]:
        found = set()
        with closing(self._connect()) as connection:
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            queries = []
            if "entity_aliases" in table_names:
                queries.append("SELECT alias FROM entity_aliases")
            if "rule_candidates" in table_names:
                queries.append("SELECT DISTINCT mention_text FROM rule_candidates WHERE candidate_type='domain_term'")
            if "model_entity_candidates" in table_names:
                queries.append("SELECT name FROM model_entity_candidates")
            for sql in queries:
                for row in connection.execute(sql):
                    term = row[0]
                    if len(term) >= 2 and term in question:
                        found.add(term)
        fragments = [piece.strip() for piece in QUESTION_SPLIT.split(question) if len(piece.strip()) >= 2]
        found.update(fragments)
        # Longer domain/entity terms are more discriminative, but cap query fan-out.
        ordered = sorted(found, key=lambda term: (-len(term), term))
        reduced = []
        for term in ordered:
            if any(term in longer for longer in reduced):
                continue
            reduced.append(term)
        return reduced[:12]

    @staticmethod
    def _best_term_span(text: str, terms: Sequence[str]) -> tuple[int, int] | None:
        occurrences = {}
        for term in terms:
            positions, cursor = [], 0
            while term and (index := text.find(term, cursor)) >= 0:
                positions.append(index)
                cursor = index + max(1, len(term))
            if positions:
                occurrences[term] = positions
        best = None
        anchors = [position for positions in occurrences.values() for position in positions]
        for anchor in anchors:
            chosen = []
            for term, positions in occurrences.items():
                position = min(positions, key=lambda value: abs(value - anchor))
                chosen.append((position, position + len(term)))
            if chosen:
                left, right = min(x[0] for x in chosen), max(x[1] for x in chosen)
                candidate = (right - left, left, right)
                if best is None or candidate < best:
                    best = candidate
        return (best[1], best[2]) if best else None

    @classmethod
    def _snippet(cls, text: str, terms: Sequence[str], max_chars: int) -> tuple[str, int, int, bool]:
        if max_chars <= 0 or len(text) <= max_chars:
            return text, 0, len(text), False
        best_span = cls._best_term_span(text, terms)
        focus_start, focus_end = best_span if best_span else (0, 0)
        span = focus_end - focus_start
        start = max(0, focus_start - max(0, max_chars - span) // 2)
        end = min(len(text), start + max_chars)
        start = max(0, end - max_chars)
        return text[start:end], start, end, True

    def _retrieve_term(
        self, term: str, works: Sequence[str], trust_levels: Sequence[int], limit: int
    ) -> list[dict]:
        filters, params = ["s.ip_domain=?"], [self.ip_domain]
        if works:
            work_column = "sw.work_id" if self.has_hierarchy else "s.work_title"
            filters.append(f"{work_column} IN ({','.join('?' for _ in works)})")
            params.extend(works)
        if trust_levels:
            filters.append(f"s.trust_level IN ({','.join('?' for _ in trust_levels)})")
            params.extend(trust_levels)
        where_extra = (" AND " + " AND ".join(filters)) if filters else ""
        hierarchy_columns, hierarchy_joins = self._hierarchy_sql()
        with closing(self._connect()) as connection:
            if len(term) < 3:
                sql = f"""SELECT w.window_id,w.text,w.sequence_no,w.chapter_index,w.chapter_title,
                                  s.source_id,s.work_title,s.trust_level,s.source_type,s.url,
                                  {hierarchy_columns},0.0 AS lexical_rank
                           FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                           {hierarchy_joins}
                           WHERE w.text LIKE ?{where_extra}
                           ORDER BY w.source_id,w.sequence_no LIMIT ?"""
                rows = connection.execute(sql, [f"%{term}%", *params, limit]).fetchall()
            else:
                escaped = term.replace('"', '""')
                sql = f"""SELECT w.window_id,w.text,w.sequence_no,w.chapter_index,w.chapter_title,
                                  s.source_id,s.work_title,s.trust_level,s.source_type,s.url,
                                  {hierarchy_columns},bm25(windows_fts) AS lexical_rank
                           FROM windows_fts f JOIN context_windows w ON w.window_id=f.window_id
                           JOIN sources s ON s.source_id=w.source_id
                           {hierarchy_joins}
                           WHERE windows_fts MATCH ?{where_extra}
                           ORDER BY bm25(windows_fts) LIMIT ?"""
                rows = connection.execute(sql, [f'"{escaped}"', *params, limit]).fetchall()
        return [dict(row) for row in rows]

    def _retrieve_combined(
        self, terms: Sequence[str], works: Sequence[str], trust_levels: Sequence[int], limit: int
    ) -> list[dict]:
        if len(terms) < 2:
            return []
        filters, params = ["s.ip_domain=?"], [self.ip_domain]
        for term in terms[:4]:
            filters.append("w.text LIKE ?")
            params.append(f"%{term}%")
        if works:
            work_column = "sw.work_id" if self.has_hierarchy else "s.work_title"
            filters.append(f"{work_column} IN ({','.join('?' for _ in works)})")
            params.extend(works)
        if trust_levels:
            filters.append(f"s.trust_level IN ({','.join('?' for _ in trust_levels)})")
            params.extend(trust_levels)
        hierarchy_columns, hierarchy_joins = self._hierarchy_sql()
        sql = f"""SELECT w.window_id,w.text,w.sequence_no,w.chapter_index,w.chapter_title,
                          s.source_id,s.work_title,s.trust_level,s.source_type,s.url,
                          {hierarchy_columns},0.0 AS lexical_rank
                   FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                   {hierarchy_joins}
                   WHERE {' AND '.join(filters)}
                   ORDER BY w.source_id,w.sequence_no LIMIT ?"""
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, [*params, limit]).fetchall()
        return [dict(row) for row in rows]

    def search(
        self,
        question: str,
        works: Sequence[str] | None = None,
        top_k: int = 10,
        trust_levels: Sequence[int] = (1, 11),
        max_evidence_chars: int = 1200,
    ) -> dict:
        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        work_ids = normalize_work_ids(works, self.work_aliases)
        available = {row["work_id"] for row in self.list_works()}
        unknown = sorted(set(work_ids) - available)
        if unknown:
            raise ValueError(f"Unknown work ids: {unknown}")
        invalid_trust = sorted(set(trust_levels) - {1, 2, 3, 4, 11})
        if invalid_trust:
            raise ValueError(f"Invalid trust levels: {invalid_trust}")
        terms = self._vocabulary(question)
        if not terms:
            terms = [question]
        pool_limit = max(40, top_k * 8)
        aggregated: dict[str, dict] = {}
        matches = defaultdict(set)
        combined_terms = terms[:4]
        for rank, row in enumerate(
            self._retrieve_combined(combined_terms, work_ids, trust_levels, pool_limit), 1
        ):
            item = aggregated.setdefault(row["window_id"], {**row, "rrf_score": 0.0})
            item["rrf_score"] += 1.0 / (10.0 + rank)
            matches[row["window_id"]].update(combined_terms)
        for term in terms:
            for rank, row in enumerate(self._retrieve_term(term, work_ids, trust_levels, pool_limit), 1):
                item = aggregated.setdefault(row["window_id"], {**row, "rrf_score": 0.0})
                item["rrf_score"] += 1.0 / (60.0 + rank)
                matches[row["window_id"]].add(term)
        total_terms = max(1, len(terms))
        for window_id, item in aggregated.items():
            coverage = len(matches[window_id]) / total_terms
            # Do not reward the full question verbatim: novels often contain questions in dialogue.
            item["matched_terms"] = sorted(matches[window_id], key=lambda value: (-len(value), value))
            best_span = self._best_term_span(item["text"], item["matched_terms"])
            span_width = (best_span[1] - best_span[0]) if best_span else len(item["text"])
            # Closely co-occurring terms are usually a definition or direct relation statement.
            proximity = 0.15 / (1.0 + span_width / 50.0) if len(item["matched_terms"]) > 1 else 0.0
            definition_cue = 0.0
            if re.search(r"(?:武魂.{0,8}(?:是|为)|(?:这就是|分别是).{0,12}武魂)", item["text"]):
                definition_cue = 0.12
            item["score"] = item.pop("rrf_score") + coverage * 0.25 + proximity + definition_cue
        ranked = sorted(
            aggregated.values(),
            key=lambda row: (-row["score"], -len(row["matched_terms"]), row["work_id"] or "", row["sequence_no"]),
        )[:top_k]
        results = []
        for rank, row in enumerate(ranked, 1):
            evidence, start, end, truncated = self._snippet(row["text"], row["matched_terms"], max_evidence_chars)
            results.append({
                "rank": rank, "score": round(row["score"], 8),
                "matched_terms": row["matched_terms"], "work_id": row["work_id"],
                "work_title": row["work_title"], "chapter_id": row["chapter_id"],
                "chapter_index": row["chapter_index"], "chapter_title": row["chapter_title"],
                "window_id": row["window_id"], "source_id": row["source_id"],
                "source_type": row["source_type"], "trust_level": row["trust_level"], "url": row["url"],
                "evidence_text": evidence, "evidence_window_start": start,
                "evidence_window_end": end, "evidence_truncated": truncated,
            })
        warnings = ["返回结果是检索证据，不是已经验证的设定结论。"]
        if any(row["trust_level"] == 11 for row in results):
            warnings.append("结果包含 trust_level=11 的第三方转录副本，正式考据必须与 L1 原件交叉验证。")
        return {
            "query": question, "answer_status": "evidence_only", "ip_domain": self.ip_domain,
            "works": work_ids, "trust_levels": list(trust_levels), "query_terms": terms,
            "result_count": len(results), "results": results, "warnings": warnings,
        }
