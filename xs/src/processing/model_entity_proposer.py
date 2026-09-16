"""Use a local model to propose entity mentions, then enforce exact-text grounding."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .model_client import ModelClient


ENTITY_TYPES = ("person", "organization", "location", "item", "creature", "ability", "other")
SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "maxItems": 15,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {"type": "string", "enum": list(ENTITY_TYPES)},
                },
                "required": ["name", "entity_type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entities"],
    "additionalProperties": False,
}

SYSTEM = """你是中文小说实体提名器。只抄录输入文本中逐字出现的专名，不补全、不改写、不解释。
最多输出15个。提取人物、组织、地点、物品、生物、能力名称。普通代词、泛称、头衔加姓名、属性词、句子片段不得作为实体。
不确定时不要输出。返回严格符合给定 JSON Schema 的对象。"""


def propose(window: dict[str, Any], client: ModelClient, known_aliases: set[str]) -> dict:
    result = client.generate_json(SYSTEM, window["text"], SCHEMA)
    accepted, rejected = [], []
    seen = set()
    for raw in result.get("entities", []):
        name = str(raw.get("name", "")).strip()
        entity_type = raw.get("entity_type")
        reason = None
        if len(name) < 2 or len(name) > 20:
            reason = "invalid_name_length"
        elif entity_type == "other":
            reason = "unscoped_other_type"
        elif re.fullmatch(r"[零〇一二三四五六七八九十百千万两\d]+(?:年|岁|级|次)", name):
            reason = "numeric_or_temporal_phrase"
        elif "的" in name:
            reason = "descriptive_phrase"
        elif name.endswith(("先祖", "父亲", "母亲", "老师", "哥哥", "姐姐", "弟弟", "妹妹")):
            reason = "title_or_kinship_phrase"
        elif entity_type == "person" and len(name) > 6:
            reason = "person_name_boundary_uncertain"
        elif entity_type not in ENTITY_TYPES:
            reason = "invalid_entity_type"
        elif name not in window["text"]:
            reason = "not_exactly_in_window"
        elif name in known_aliases:
            reason = "already_known"
        elif name in seen:
            reason = "duplicate_in_window"
        if reason:
            rejected.append({"name": name, "entity_type": entity_type, "reason": reason})
            continue
        seen.add(name)
        offsets = []
        start = 0
        while True:
            index = window["text"].find(name, start)
            if index < 0:
                break
            offsets.append([index, index + len(name)])
            start = index + len(name)
        candidate_id = "model-entity-" + hashlib.sha256(
            f"{window['window_id']}\0{name}\0{entity_type}".encode("utf-8")
        ).hexdigest()[:32]
        accepted.append({
            "candidate_id": candidate_id, "name": name, "entity_type": entity_type,
            "window_id": window["window_id"], "work_id": window["work_id"],
            "chapter_id": window["chapter_id"], "window_offsets": offsets,
            "status": "candidate", "grounding_status": "exact_text",
            "method": "local_model_entity_proposal_v1", "model": client.model,
        })
    return {"accepted": accepted, "rejected": rejected}
