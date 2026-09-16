"""原子事实候选与证据校验结果模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


FactType = Literal["attribute", "relationship", "event", "identity", "possession", "membership", "state_change"]


class AtomicFactCandidate(BaseModel):
    """模型或规则输出只能先成为候选，不能直接成为正式设定。"""

    fact_id: str
    subject: str
    predicate: str
    object: str
    fact_type: FactType
    work_id: str
    chapter_id: str
    window_id: str
    evidence_text: str
    evidence_window_start: int
    evidence_window_end: int
    evidence_unit_ids: List[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative"] = "positive"
    certainty: Literal["explicit", "reported", "uncertain", "hypothetical"] = "explicit"
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    trust_level: Literal[1, 2, 3, 4, 11]
    extraction_method: str
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    status: Literal["candidate"] = "candidate"


class EvidenceValidation(BaseModel):
    fact_id: str
    grounding_status: Literal["grounded", "rejected"]
    semantic_review_status: Literal["pending_review"] = "pending_review"
    evidence_exact: bool
    offsets_valid: bool
    units_valid: bool
    source_scope_valid: bool
    subject_in_window: bool
    object_in_window: bool
    resolved_unit_ids: List[str] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
