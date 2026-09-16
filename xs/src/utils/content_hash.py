"""按 source_key 记录已落盘内容哈希；不跨信源删除相同内容，保留独立溯源关系。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ContentHashStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"内容哈希状态格式错误: {self.path}")
        return value

    @staticmethod
    def _key(source_key: str, content_sha256: str) -> str:
        return f"{source_key}\n{content_sha256}"

    def existing_source_id(self, source_key: str, content_sha256: str) -> Optional[str]:
        item = self._load().get(self._key(source_key, content_sha256))
        return item.get("source_id") if item else None

    def add(
        self, source_key: str, content_sha256: str, source_id: str, output: str
    ) -> None:
        state = self._load()
        state[self._key(source_key, content_sha256)] = {
            "source_id": source_id,
            "output": output,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_path, self.path)
