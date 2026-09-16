"""将 raw JSONL 中的 PDF 原件按页提取到 processed/pdf_pages。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from src.processing.pdf_extractor import extract_pdf_pages
from src.storage.ip_paths import IpDataPaths


CODE_ROOT = Path(__file__).resolve().parent


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    return Path(configured).resolve() if configured else CODE_ROOT.with_name(f"{CODE_ROOT.name}_data")


def iter_inputs(data_root: Path, explicit: Iterable[str], ip_domain: str | None) -> Iterable[Path]:
    if explicit:
        for value in explicit:
            path = Path(value).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            yield path
        return
    root = IpDataPaths(data_root, ip_domain).raw if ip_domain else data_root / "data" / "ip"
    for path in sorted(root.rglob("*.jsonl")):
        if "_state" not in path.parts:
            yield path


def destination(data_root: Path, input_path: Path, ip_domain: str) -> Path:
    suffix = hashlib.sha256(str(input_path).encode("utf-8")).hexdigest()[:10]
    return IpDataPaths(data_root, ip_domain).processed / "pdf_pages" / f"{input_path.stem}.{suffix}.pdf_pages.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF页级提取：raw PDF JSONL -> processed/pdf_pages JSONL")
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--input", action="append", default=[], help="指定包含 PDF 的 raw JSONL；可重复")
    parser.add_argument("--ip-domain", help="只处理指定 IP")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    totals = {"files": 0, "pdf_records": 0, "pages": 0, "pages_requiring_ocr": 0, "skipped": 0, "failed": 0}
    for path in iter_inputs(args.data_root.resolve(), args.input, args.ip_domain):
        by_domain: dict[str, list[dict]] = {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    meta = record.get("extra_meta") or {}
                    media_type = str(meta.get("media_type", "")).lower()
                    is_pdf = media_type == "application/pdf" or str(record.get("url", "")).lower().endswith(".pdf")
                    if not is_pdf or (args.ip_domain and record.get("ip_domain") != args.ip_domain):
                        totals["skipped"] += 1
                        continue
                    pages = list(extract_pdf_pages(record))
                    totals["pdf_records"] += 1
                    totals["pages"] += len(pages)
                    totals["pages_requiring_ocr"] += sum(bool(p["extra_meta"]["requires_ocr"]) for p in pages)
                    by_domain.setdefault(record["ip_domain"], []).extend(pages)
            if not args.dry_run:
                for domain, pages in by_domain.items():
                    output = destination(args.data_root.resolve(), path, domain)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    temporary = output.with_suffix(output.suffix + ".tmp")
                    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                        for page in pages:
                            handle.write(json.dumps(page, ensure_ascii=False, separators=(",", ":")) + "\n")
                    temporary.replace(output)
                    print(f"[OK] {path.name}: {len(pages)} pages -> {output}")
            totals["files"] += 1
        except Exception as exc:
            totals["failed"] += 1
            print(f"[FAIL] {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps(totals, ensure_ascii=False))
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
