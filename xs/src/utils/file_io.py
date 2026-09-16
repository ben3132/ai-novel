"""JSONL 与目录操作；不修改 raw_content。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator

from src.collector.base_collector import RawRecord


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, record: RawRecord) -> None:
    ensure_parent(path)
    payload = record.model_dump() if hasattr(record, "model_dump") else record.dict()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def append_jsonl_dict(path: Path, payload: Dict[str, Any]) -> None:
    """追加运行状态等非 RawRecord JSONL；不改变传入字段。"""
    ensure_parent(path)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)
