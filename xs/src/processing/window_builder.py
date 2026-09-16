"""把最小证据单元组合成章节内模型上下文窗口。"""

from __future__ import annotations

import hashlib
from itertools import groupby
from typing import Dict, Iterable, Iterator, List, Tuple

from .models import ContextWindow, TextUnit, WindowUnitSpan


BUILDER_VERSION = "chapter_window_v1"


def _model_validate(payload: dict) -> TextUnit:
    if hasattr(TextUnit, "model_validate"):
        return TextUnit.model_validate(payload)
    return TextUnit.parse_obj(payload)


def _group_key(unit: TextUnit) -> Tuple[str, int | None]:
    return unit.source_id, unit.extra_meta.get("chapter_index")


def build_context_windows(
    payloads: Iterable[dict],
    *,
    target_chars: int = 1000,
    max_chars: int = 1600,
    overlap_units: int = 2,
) -> Iterator[ContextWindow]:
    """按来源和章节组合相邻单元；绝不跨章节，也不改写单元文字。"""
    if target_chars < 200 or max_chars < target_chars:
        raise ValueError("窗口长度必须满足 200 <= target_chars <= max_chars")
    if overlap_units < 0:
        raise ValueError("overlap_units 不能为负数")

    units = (_model_validate(payload) for payload in payloads)
    global_sequence = 0
    for (_, chapter_index), grouped in groupby(units, key=_group_key):
        chapter_units = list(grouped)
        if not chapter_units:
            continue
        start = 0
        while start < len(chapter_units):
            selected: List[TextUnit] = []
            length = 0
            end = start
            while end < len(chapter_units):
                candidate = chapter_units[end]
                proposed = length + (1 if selected else 0) + len(candidate.text)
                if selected and proposed > max_chars:
                    break
                selected.append(candidate)
                length = proposed
                end += 1
                if length >= target_chars:
                    break

            text_parts: List[str] = []
            spans: List[WindowUnitSpan] = []
            cursor = 0
            for unit in selected:
                if text_parts:
                    text_parts.append("\n")
                    cursor += 1
                window_start = cursor
                text_parts.append(unit.text)
                cursor += len(unit.text)
                spans.append(WindowUnitSpan(
                    unit_id=unit.unit_id,
                    window_start=window_start,
                    window_end=cursor,
                    source_raw_start=unit.raw_start,
                    source_raw_end=unit.raw_end,
                ))
            window_text = "".join(text_parts)
            content_hash = hashlib.sha256(window_text.encode("utf-8")).hexdigest()
            first, last = selected[0], selected[-1]
            identity = "\0".join((
                BUILDER_VERSION,
                first.source_id,
                first.unit_id,
                last.unit_id,
                str(target_chars),
                str(max_chars),
                str(overlap_units),
                content_hash,
            )).encode("utf-8")
            source_meta: Dict = first.extra_meta.get("source_extra_meta", {})
            yield ContextWindow(
                window_id="window-" + hashlib.sha256(identity).hexdigest()[:32],
                source_id=first.source_id,
                trust_level=first.trust_level,
                source_type=first.source_type,
                ip_domain=first.ip_domain,
                url=first.url,
                chapter_index=chapter_index,
                chapter_title=first.extra_meta.get("chapter_title"),
                sequence_no=global_sequence,
                text=window_text,
                content_sha256=content_hash,
                unit_ids=[unit.unit_id for unit in selected],
                unit_spans=spans,
                extra_meta={
                    "builder": BUILDER_VERSION,
                    "target_chars": target_chars,
                    "max_chars": max_chars,
                    "overlap_units": overlap_units,
                    "first_unit_sequence": first.sequence_no,
                    "last_unit_sequence": last.sequence_no,
                    "work_title": source_meta.get("work_title"),
                    "work_version": source_meta.get("work_version"),
                    "canon_scope": source_meta.get("canon_scope"),
                },
            )
            global_sequence += 1
            if end >= len(chapter_units):
                break
            start = max(start + 1, end - overlap_units)
