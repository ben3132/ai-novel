"""Hybrid lexical + local-vector retrieval with evidence-preserving output."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .douluo_query import DouluoQueryEngine, normalize_work_ids
from .vector_index import FaissEvidenceIndex


class HybridIpQueryEngine:
    def __init__(
        self, database: Path | str, index_dir: Path | str,
        model_path: Path | str | None = None, ip_domain: str = "douluo",
        work_aliases: dict[str, str] | None = None,
    ):
        self.lexical = DouluoQueryEngine(database, ip_domain=ip_domain, work_aliases=work_aliases)
        self.vector = FaissEvidenceIndex(index_dir, model_path=model_path, index_name=f"{ip_domain}_windows")
        self.vector.validate_database(self.lexical.database)

    def search(
        self,
        question: str,
        works: Sequence[str] | None = None,
        top_k: int = 10,
        trust_levels: Sequence[int] = (1, 11),
        max_evidence_chars: int = 1200,
    ) -> dict:
        pool = max(50, top_k * 10)
        lexical_result = self.lexical.search(
            question, works=works, top_k=min(pool, 100), trust_levels=trust_levels,
            max_evidence_chars=max_evidence_chars,
        )
        vector_hits = self.vector.search(question, top_k=min(pool * 3, 500))
        hydrated = self.lexical.get_windows([hit["window_id"] for hit in vector_hits])
        work_ids = normalize_work_ids(works, self.lexical.work_aliases)
        allowed_trust = set(trust_levels)
        vector_hits = [
            hit for hit in vector_hits
            if (row := hydrated.get(hit["window_id"]))
            and (not work_ids or row["work_id"] in work_ids)
            and row["trust_level"] in allowed_trust
        ][:pool]

        fused: dict[str, dict] = {}
        for row in lexical_result["results"]:
            fused[row["window_id"]] = {
                **row, "lexical_rank": row["rank"], "vector_rank": None,
                "vector_score": None, "fusion_score": 1.0 / (60 + row["rank"]),
            }
        for hit in vector_hits:
            window_id = hit["window_id"]
            if window_id not in fused:
                row = hydrated[window_id]
                evidence, start, end, truncated = self.lexical._snippet(
                    row["text"], lexical_result["query_terms"], max_evidence_chars,
                )
                fused[window_id] = {
                    "rank": 0, "score": 0.0, "matched_terms": [],
                    "work_id": row["work_id"], "work_title": row["work_title"],
                    "chapter_id": row["chapter_id"], "chapter_index": row["chapter_index"],
                    "chapter_title": row["chapter_title"], "window_id": window_id,
                    "source_id": row["source_id"], "source_type": row["source_type"],
                    "trust_level": row["trust_level"], "url": row["url"],
                    "evidence_text": evidence, "evidence_window_start": start,
                    "evidence_window_end": end, "evidence_truncated": truncated,
                    "lexical_rank": None, "fusion_score": 0.0,
                }
            fused[window_id]["vector_rank"] = hit["vector_rank"]
            fused[window_id]["vector_score"] = round(hit["vector_score"], 8)
            # Slightly favor semantic retrieval so paraphrased relation evidence is not
            # crowded out by many literal single-term matches.
            fused[window_id]["fusion_score"] += 1.1 / (60 + hit["vector_rank"])

        ranked = sorted(
            fused.values(),
            key=lambda row: (-row["fusion_score"], row["lexical_rank"] or 10**9, row["vector_rank"] or 10**9),
        )[:top_k]
        for rank, row in enumerate(ranked, 1):
            row["rank"] = rank
            row["fusion_score"] = round(row["fusion_score"], 8)
        return {
            **{key: value for key, value in lexical_result.items() if key not in ("results", "result_count")},
            "retrieval_mode": "hybrid_rrf",
            "result_count": len(ranked),
            "results": ranked,
        }


class HybridDouluoQueryEngine(HybridIpQueryEngine):
    """Backward-compatible Douluo wrapper."""

    def __init__(self, database: Path | str, index_dir: Path | str, model_path: Path | str | None = None):
        super().__init__(database, index_dir, model_path=model_path, ip_domain="douluo")
