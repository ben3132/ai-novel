"""本地第三方全文转录导入器（L1-derived，trust_level 永久固定为 11）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .base_collector import BaseCollector, RawRecord, TRUST_L1_DERIVED
from src.storage.ip_paths import IpDataPaths


DERIVED_NOTE = "第三方转录副本，必须L1原件交叉验证"


class LocalDerivedTextCollector(BaseCollector):
    """原样读取用户已有 TXT/MD；不清洗广告、不纠错、不拆章。"""

    trust_level = TRUST_L1_DERIVED
    source_type = "derived_transcription"

    def collect(self) -> RawRecord:
        paths = IpDataPaths(self.project_root, self.task["ip_domain"])
        path = paths.source_material(self.task["path"], "derived_text").resolve(strict=True)
        allowed_root = (paths.raw / "source_material" / "derived_text").resolve()
        if allowed_root not in path.parents:
            raise ValueError(f"本地 L1-derived 文件必须位于该 IP 的 raw/source_material/derived_text 下: {path}")
        if path.suffix.lower() not in {".txt", ".md"}:
            raise ValueError("local_derived_text 只读取 .txt 或 .md")
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
                "acquisition_method": "user_supplied_local_import",
                "original_import_path": self.task.get("original_import_path"),
                "note": DERIVED_NOTE,
                "requires_l1_cross_check": True,
            },
        )
