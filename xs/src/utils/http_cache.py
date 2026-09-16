"""HTTP 条件请求状态：只保存公开 URL、ETag 与 Last-Modified，不保存凭据。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from src.storage.ip_paths import IpDataPaths


class NotModifiedError(Exception):
    """服务器确认资源未变化；属于正常跳过，不是采集失败。"""


class HttpValidatorStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"HTTP validator 状态格式错误: {self.path}")
        return value

    @staticmethod
    def _key(source_key: str, url: str) -> str:
        return f"{source_key}\n{url}"

    def request_headers(self, source_key: str, url: str) -> Dict[str, str]:
        item = self._load().get(self._key(source_key, url), {})
        headers: Dict[str, str] = {}
        if item.get("etag"):
            headers["If-None-Match"] = item["etag"]
        if item.get("last_modified"):
            headers["If-Modified-Since"] = item["last_modified"]
        return headers

    def update(self, source_key: str, requested_url: str, response: Any) -> None:
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        if not etag and not last_modified:
            return
        state = self._load()
        item = {
            "etag": etag,
            "last_modified": last_modified,
            "final_url": response.url,
        }
        state[self._key(source_key, requested_url)] = item
        state[self._key(source_key, response.url)] = item
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_path, self.path)


def validator_store(project_root: str, task: Dict[str, Any]) -> HttpValidatorStore:
    configured = task.get("http_validator_file", "_state/http_validators.json")
    path = IpDataPaths(project_root, task["ip_domain"]).raw_output(configured)
    return HttpValidatorStore(path)
