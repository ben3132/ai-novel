"""不调用 LLM 的确定性文本分片器。"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import TextUnit


CHAPTER_RE = re.compile(
    r"(?m)^[ \t]*(?P<title>(?:第[零〇一二三四五六七八九十百千万两\d]+[章节卷回部集篇]|"
    r"序章|楔子|引子|前言|后记|尾声|番外)[^\r\n]{0,80})[ \t]*\r?$"
)
BLOCK_TAG_RE = re.compile(
    r"^<\s*/?\s*(?:address|article|aside|blockquote|br|dd|div|dl|dt|fieldset|"
    r"figcaption|figure|footer|form|h[1-6]|header|hr|li|main|nav|ol|p|pre|"
    r"section|table|tbody|td|tfoot|th|thead|tr|ul)\b",
    re.I,
)
TOKEN_RE = re.compile(r"<!--[\s\S]*?-->|<![^>]*>|<[^>]*>|[^<]+")
SPACE_RE = re.compile(r"[\t\f\v ]+")
SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;])")
SRT_CUE_RE = re.compile(
    r"(?ms)(?:^|\n)(?:\d+\s*\n)?"
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})[^\n]*\n"
    r"(?P<text>.*?)(?=\n\s*\n|\Z)"
)
VTT_CUE_RE = re.compile(
    r"(?ms)(?:^|\n)(?:[^\n]*\n)?"
    r"(?P<start>\d{2}:\d{2}(?::\d{2})?\.\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}(?::\d{2})?\.\d{3})[^\n]*\n"
    r"(?P<text>.*?)(?=\n\s*\n|\Z)"
)


@dataclass(frozen=True)
class Segment:
    text: str
    unit_type: str
    derived_start: int
    derived_end: int
    raw_start: Optional[int]
    raw_end: Optional[int]
    meta: Dict[str, Any]


def _clean_plain(value: str) -> str:
    lines = [SPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _split_long(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = [part for part in SENTENCE_END_RE.split(text) if part]
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = ""
        while len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        current += sentence
    if current:
        chunks.append(current)
    return chunks


def _plain_segments(raw: str, max_chars: int) -> List[Segment]:
    """按章节标题和自然段切分，所有位置直接对应 raw_content。"""
    boundaries = list(CHAPTER_RE.finditer(raw))
    chapter_ranges: List[Tuple[int, int, Optional[str]]] = []
    if boundaries:
        if boundaries[0].start() > 0:
            chapter_ranges.append((0, boundaries[0].start(), None))
        for index, match in enumerate(boundaries):
            end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(raw)
            chapter_ranges.append((match.start(), end, match.group("title").strip()))
    else:
        chapter_ranges.append((0, len(raw), None))

    segments: List[Segment] = []
    derived_cursor = 0
    for chapter_index, (start, end, title) in enumerate(chapter_ranges):
        chapter_text = raw[start:end]
        # PDF 文本提取通常在页末保留一个换行；允许末段后的纯空白直到 EOF，
        # 否则整页会因最后一个换行而被错误跳过。
        for para_match in re.finditer(r"\S(?:[\s\S]*?\S)?(?=\r?\n\s*\r?\n|\s*\Z)", chapter_text):
            para_raw = para_match.group(0)
            cleaned = _clean_plain(para_raw)
            if not cleaned:
                continue
            raw_base = start + para_match.start()
            search_from = 0
            for part_index, part in enumerate(_split_long(cleaned, max_chars)):
                local = para_raw.find(part, search_from)
                part_raw_start = raw_base + local if local >= 0 else raw_base
                part_raw_end = part_raw_start + len(part) if local >= 0 else raw_base + len(para_raw)
                segments.append(Segment(
                    text=part,
                    unit_type="chapter" if title and para_match.start() == 0 and part_index == 0 else "paragraph",
                    derived_start=derived_cursor,
                    derived_end=derived_cursor + len(part),
                    raw_start=part_raw_start,
                    raw_end=part_raw_end,
                    meta={"chapter_index": chapter_index, "chapter_title": title, "part_index": part_index},
                ))
                derived_cursor += len(part) + 1
                if local >= 0:
                    search_from = local + len(part)
    return segments


def _html_segments(raw: str, max_chars: int) -> List[Segment]:
    """提取可见文本块，同时保存覆盖它们的原始 HTML 范围。"""
    blocks: List[Tuple[str, int, int]] = []
    pieces: List[Tuple[str, int, int]] = []
    suppressed: Optional[str] = None

    def flush() -> None:
        if not pieces:
            return
        # 不同文本节点之间可能隔着 <a>/<span>/<strong> 等内联标签。保留一个
        # 规范空格，避免“版本介绍游戏介绍”一类粘连；同一文本节点内部不改字。
        value = _clean_plain(" ".join(item[0] for item in pieces))
        if value:
            blocks.append((value, pieces[0][1], pieces[-1][2]))
        pieces.clear()

    for token in TOKEN_RE.finditer(raw):
        value = token.group(0)
        if value.startswith("<"):
            tag_match = re.match(r"<\s*(/?)\s*([a-zA-Z0-9]+)", value)
            if tag_match:
                closing, tag = tag_match.group(1), tag_match.group(2).lower()
                if suppressed:
                    if closing and tag == suppressed:
                        suppressed = None
                    continue
                if not closing and tag in {"script", "style", "noscript", "template", "svg"}:
                    flush()
                    suppressed = tag
                    continue
            if BLOCK_TAG_RE.match(value):
                flush()
            continue
        if suppressed:
            continue
        decoded = html.unescape(value)
        if decoded.strip():
            pieces.append((decoded, token.start(), token.end()))
    flush()

    segments: List[Segment] = []
    cursor = 0
    for block_index, (text, raw_start, raw_end) in enumerate(blocks):
        for part_index, part in enumerate(_split_long(text, max_chars)):
            segments.append(Segment(
                text=part,
                unit_type="html_block",
                derived_start=cursor,
                derived_end=cursor + len(part),
                raw_start=raw_start,
                raw_end=raw_end,
                meta={"block_index": block_index, "part_index": part_index},
            ))
            cursor += len(part) + 1
    return segments


def _subtitle_segments(raw: str, max_chars: int) -> List[Segment]:
    regex = VTT_CUE_RE if raw.lstrip().startswith("WEBVTT") else SRT_CUE_RE
    segments: List[Segment] = []
    cursor = 0
    for cue_index, match in enumerate(regex.finditer(raw)):
        value = _clean_plain(re.sub(r"<[^>]+>", "", match.group("text")))
        if not value:
            continue
        for part_index, part in enumerate(_split_long(value, max_chars)):
            segments.append(Segment(
                text=part,
                unit_type="subtitle_cue",
                derived_start=cursor,
                derived_end=cursor + len(part),
                raw_start=match.start("text"),
                raw_end=match.end("text"),
                meta={
                    "cue_index": cue_index,
                    "part_index": part_index,
                    "start_time": match.group("start"),
                    "end_time": match.group("end"),
                },
            ))
            cursor += len(part) + 1
    return segments if segments else _plain_segments(raw, max_chars)


def _kind(record: Dict[str, Any]) -> str:
    source_type = str(record.get("source_type", ""))
    media_type = str(record.get("extra_meta", {}).get("media_type", "")).lower()
    url = str(record.get("url", "")).lower()
    if "html" in source_type or "html" in media_type:
        return "html"
    if "subtitle" in source_type or url.endswith((".srt", ".vtt")):
        return "subtitle"
    return "text"


def segment_record(record: Dict[str, Any], max_chars: int = 1200) -> Iterable[TextUnit]:
    """将单条 RawRecord 转为 TextUnit；二进制 Base64 文档由未来专用解析器处理。"""
    raw = record.get("raw_content")
    if not isinstance(raw, str) or not raw:
        return []
    meta = record.get("extra_meta", {})
    media_type = str(meta.get("media_type", "")).lower()
    encoding = str(meta.get("content_encoding", "")).lower()
    if encoding == "base64" or media_type.startswith(("application/pdf", "image/", "audio/", "video/")):
        return []
    kind = _kind(record)
    if kind == "html":
        segments = _html_segments(raw, max_chars)
    elif kind == "subtitle":
        segments = _subtitle_segments(raw, max_chars)
    else:
        segments = _plain_segments(raw, max_chars)

    units: List[TextUnit] = []
    for sequence_no, segment in enumerate(segments):
        digest = hashlib.sha256(segment.text.encode("utf-8")).hexdigest()
        identity = f"{record['source_id']}\0{sequence_no}\0{digest}".encode("utf-8")
        unit_id = "unit-" + hashlib.sha256(identity).hexdigest()[:32]
        units.append(TextUnit(
            unit_id=unit_id,
            source_id=record["source_id"],
            trust_level=record["trust_level"],
            source_type=record["source_type"],
            ip_domain=record["ip_domain"],
            url=record["url"],
            unit_type=segment.unit_type,  # type: ignore[arg-type]
            sequence_no=sequence_no,
            text=segment.text,
            content_sha256=digest,
            text_start=segment.derived_start,
            text_end=segment.derived_end,
            raw_start=segment.raw_start,
            raw_end=segment.raw_end,
            extra_meta={
                **segment.meta,
                "segmenter": "deterministic_v1",
                "coordinate_space": "derived_text",
                "raw_coordinate_space": "raw_content_python_chars",
                "source_collect_ts": record.get("collect_ts"),
                "source_extra_meta": {
                    key: record.get("extra_meta", {}).get(key)
                    for key in (
                        "source_key", "work_title", "work_version", "canon_scope",
                        "derivation_type", "extraction_method", "parser", "parser_version",
                        "record_role", "source_artifact_id", "parent_source_id",
                        "source_sha256", "page_number", "page_index",
                        "page_text_sha256", "evidence_coordinate",
                    )
                },
            },
        ))
    return units
