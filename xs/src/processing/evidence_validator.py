"""只验证事实候选的证据落点，不替代语义审核。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .fact_models import AtomicFactCandidate, EvidenceValidation


def validate_evidence(database: Path, payload: dict) -> EvidenceValidation:
    fact = (
        AtomicFactCandidate.model_validate(payload)
        if hasattr(AtomicFactCandidate, "model_validate")
        else AtomicFactCandidate.parse_obj(payload)
    )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        window = connection.execute(
            """SELECT w.*,sw.work_id,c.chapter_id,s.trust_level
               FROM context_windows w
               JOIN source_works sw ON sw.source_id=w.source_id
               JOIN chapters c ON c.source_id=w.source_id AND c.chapter_index=w.chapter_index
               JOIN sources s ON s.source_id=w.source_id
               WHERE w.window_id=?""",
            (fact.window_id,),
        ).fetchone()
        reasons = []
        if window is None:
            return EvidenceValidation(
                fact_id=fact.fact_id, grounding_status="rejected", evidence_exact=False,
                offsets_valid=False, units_valid=False, source_scope_valid=False,
                subject_in_window=False, object_in_window=False,
                rejection_reasons=["window_not_found"],
            )
        offsets_valid = 0 <= fact.evidence_window_start < fact.evidence_window_end <= len(window["text"])
        evidence_exact = offsets_valid and window["text"][fact.evidence_window_start:fact.evidence_window_end] == fact.evidence_text
        if not offsets_valid:
            reasons.append("invalid_evidence_offsets")
        elif not evidence_exact:
            reasons.append("evidence_text_mismatch")
        source_scope_valid = (
            fact.work_id == window["work_id"]
            and fact.chapter_id == window["chapter_id"]
            and fact.trust_level == window["trust_level"]
        )
        if not source_scope_valid:
            reasons.append("source_scope_mismatch")
        resolved = []
        if offsets_valid:
            spans = connection.execute(
                "SELECT unit_id,window_start,window_end FROM window_units WHERE window_id=? ORDER BY ordinal",
                (fact.window_id,),
            ).fetchall()
            resolved = [
                row["unit_id"] for row in spans
                if row["window_end"] > fact.evidence_window_start and row["window_start"] < fact.evidence_window_end
            ]
        units_valid = bool(resolved) and (not fact.evidence_unit_ids or fact.evidence_unit_ids == resolved)
        if not units_valid:
            reasons.append("evidence_units_mismatch")
        subject_in_window = fact.subject in window["text"]
        object_in_window = fact.object in window["text"]
        if not subject_in_window:
            reasons.append("subject_not_in_window")
        if not object_in_window:
            reasons.append("object_not_in_window")
        grounded = evidence_exact and units_valid and source_scope_valid and subject_in_window and object_in_window
        return EvidenceValidation(
            fact_id=fact.fact_id,
            grounding_status="grounded" if grounded else "rejected",
            evidence_exact=evidence_exact,
            offsets_valid=offsets_valid,
            units_valid=units_valid,
            source_scope_valid=source_scope_valid,
            subject_in_window=subject_in_window,
            object_in_window=object_in_window,
            resolved_unit_ids=resolved,
            rejection_reasons=reasons,
        )
    finally:
        connection.close()
