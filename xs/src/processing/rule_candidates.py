"""配置驱动的斗罗候选召回器；不进行事实判断。"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, Iterator, List, Tuple


def compile_terms(config: Dict[str, Any]) -> List[Tuple[str, str, str, str]]:
    """返回 (literal, candidate_type, label, canonical_name)。"""
    terms: List[Tuple[str, str, str, str]] = []
    for entity_type, entities in config.get("entities", {}).items():
        for canonical, aliases in entities.items():
            for alias in aliases:
                terms.append((str(alias), "entity_mention", str(entity_type), str(canonical)))
    for term_type, values in config.get("domain_terms", {}).items():
        for value in values:
            terms.append((str(value), "domain_term", str(term_type), str(value)))
    for event_type, values in config.get("event_triggers", {}).items():
        for value in values:
            terms.append((str(value), "event_trigger", str(event_type), str(value)))
    # 长词优先只影响输出顺序，不会吞掉短词；所有精确提及仍保留。
    return sorted(set(terms), key=lambda item: (-len(item[0]), item))


def extract_candidates(
    window: Dict[str, Any],
    config: Dict[str, Any],
    compiled_terms: List[Tuple[str, str, str, str]] | None = None,
) -> Iterator[dict]:
    text = window["text"]
    seen = set()
    for literal, candidate_type, label, canonical in compiled_terms or compile_terms(config):
        start = 0
        while True:
            index = text.find(literal, start)
            if index < 0:
                break
            end = index + len(literal)
            key = (candidate_type, label, canonical, index, end)
            if key not in seen:
                seen.add(key)
                identity = "\0".join((window["window_id"], *map(str, key))).encode("utf-8")
                yield {
                    "candidate_id": "candidate-" + hashlib.sha256(identity).hexdigest()[:32],
                    "window_id": window["window_id"],
                    "source_id": window["source_id"],
                    "trust_level": window["trust_level"],
                    "ip_domain": window["ip_domain"],
                    "chapter_index": window.get("chapter_index"),
                    "chapter_title": window.get("chapter_title"),
                    "candidate_type": candidate_type,
                    "label": label,
                    "canonical_name": canonical,
                    "mention_text": literal,
                    "window_start": index,
                    "window_end": end,
                    "method": "literal_dictionary_v1",
                    "status": "candidate",
                }
            start = index + 1
    lowered = text.lower()
    for marker in config.get("noise_markers", []):
        index = lowered.find(str(marker).lower())
        if index >= 0:
            identity = f"{window['window_id']}\0noise\0{marker}\0{index}".encode("utf-8")
            yield {
                "candidate_id": "candidate-" + hashlib.sha256(identity).hexdigest()[:32],
                "window_id": window["window_id"],
                "source_id": window["source_id"],
                "trust_level": window["trust_level"],
                "ip_domain": window["ip_domain"],
                "chapter_index": window.get("chapter_index"),
                "chapter_title": window.get("chapter_title"),
                "candidate_type": "noise_marker",
                "label": "suspected_boilerplate",
                "canonical_name": str(marker),
                "mention_text": text[index:index + len(str(marker))],
                "window_start": index,
                "window_end": index + len(str(marker)),
                "method": "literal_dictionary_v1",
                "status": "candidate",
            }
