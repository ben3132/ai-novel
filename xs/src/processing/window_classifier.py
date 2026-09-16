"""本地模型窗口预分类；输出只用于路由，不是事实。"""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from pydantic import BaseModel

from .model_client import ModelClient


TOPICS = ["人物背景", "能力设定", "关系", "事件", "时间变化", "地点组织", "普通叙事", "疑似噪声"]


class Classification(BaseModel):
    relevant: bool
    topics: list[str]
    contains_explicit_event: bool
    should_extract_facts: bool


SCHEMA = {
    "type": "object",
    "required": ["relevant", "topics", "contains_explicit_event", "should_extract_facts"],
    "properties": {
        "relevant": {"type": "boolean"},
        "topics": {"type": "array", "items": {"type": "string", "enum": TOPICS}, "uniqueItems": True, "maxItems": 4},
        "contains_explicit_event": {"type": "boolean"},
        "should_extract_facts": {"type": "boolean"},
    },
    "additionalProperties": False,
}


SYSTEM = """你是小说资料窗口分类器，不抽取事实、不补充外部知识。
只判断输入片段是否含有适合后续考据抽取的信息。topics只能使用给定枚举。
人物属性、能力、明确关系、发生的事件、状态变化可标为值得抽取；纯环境描写、重复对话、站点广告通常不值得抽取。
不要因为认识角色而使用输入之外的信息。"""


def classify_window(window: Dict[str, Any], client: ModelClient) -> dict:
    payload = client.generate_json(SYSTEM, window["text"], SCHEMA)
    parsed = Classification.model_validate(payload) if hasattr(Classification, "model_validate") else Classification.parse_obj(payload)
    invalid_topics = set(parsed.topics).difference(TOPICS)
    if invalid_topics:
        raise ValueError(f"模型返回未知主题: {sorted(invalid_topics)}")
    identity = f"{window['window_id']}\0{client.provider}\0{client.model}".encode("utf-8")
    data = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
    return {
        "classification_id": "classification-" + hashlib.sha256(identity).hexdigest()[:32],
        "window_id": window["window_id"],
        "source_id": window["source_id"],
        "chapter_index": window.get("chapter_index"),
        "chapter_title": window.get("chapter_title"),
        "status": "model_candidate",
        "provider": client.provider,
        "model": client.model,
        **data,
    }
