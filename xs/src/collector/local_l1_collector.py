"""本地正版文本采集器（L1，trust_level 强制为 1）。"""

import hashlib
from pathlib import Path

from .base_collector import BaseCollector, RawRecord, TRUST_L1
from src.storage.ip_paths import IpDataPaths


class LocalL1Collector(BaseCollector):
    trust_level = TRUST_L1
    source_type = "local_text"

    def collect(self) -> RawRecord:
        paths = IpDataPaths(self.project_root, self.task["ip_domain"])
        path = paths.source_material(self.task["path"], "official_text").resolve(strict=True)
        allowed_root = (paths.raw / "source_material" / "official_text").resolve()
        if allowed_root not in path.parents:
            raise ValueError(f"本地 L1 文件必须位于该 IP 的 raw/source_material/official_text 下: {path}")
        if path.suffix.lower() not in {".txt", ".md"}:
            raise ValueError("local_l1_collector 只读取 .txt 或 .md")
        encoding = self.task.get("encoding", "utf-8")
        raw_bytes = path.read_bytes()
        raw_content = raw_bytes.decode(encoding, errors="strict")
        return self.make_record(
            url=str(path),
            raw_content=raw_content,
            extra_meta={
                "media_type": "text/markdown" if path.suffix.lower() == ".md" else "text/plain",
                "content_encoding": encoding,
                "content_length_bytes": len(raw_bytes),
                "content_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "acquisition_method": "local_read",
            },
        )
