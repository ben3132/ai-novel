"""处理层入口：从 raw JSONL 生成可追溯文本单元，不修改原始数据。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from src.processing.segmenter import segment_record
from src.storage.ip_paths import IpDataPaths


CODE_ROOT = Path(__file__).resolve().parent


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    return Path(configured).resolve() if configured else CODE_ROOT.with_name(f"{CODE_ROOT.name}_data")


def iter_input_files(data_root: Path, explicit: Iterable[str], ip_domain: str | None) -> Iterable[Path]:
    if explicit:
        for value in explicit:
            path = Path(value).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            yield path
        return
    raw_root = IpDataPaths(data_root, ip_domain).raw if ip_domain else data_root / "data" / "ip"
    for path in sorted(raw_root.rglob("*.jsonl")):
        if "_state" in path.parts:
            continue
        yield path


def output_path(data_root: Path, input_path: Path, ip_domain: str) -> Path:
    name_hash = __import__("hashlib").sha256(str(input_path).encode("utf-8")).hexdigest()[:10]
    return IpDataPaths(data_root, ip_domain).units / f"{input_path.stem}.{name_hash}.units.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="确定性分片：raw JSONL -> processed TextUnit JSONL")
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--input", action="append", default=[], help="指定 raw JSONL；可重复")
    parser.add_argument("--ip-domain", help="只处理指定 IP")
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_chars < 200:
        parser.error("--max-chars 不能小于 200")

    totals = {"files": 0, "records": 0, "units": 0, "skipped": 0, "failed": 0}
    for path in iter_input_files(args.data_root.resolve(), args.input, args.ip_domain):
        by_domain: dict[str, list[dict]] = {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if args.ip_domain and record.get("ip_domain") != args.ip_domain:
                        totals["skipped"] += 1
                        continue
                    totals["records"] += 1
                    units = list(segment_record(record, max_chars=args.max_chars))
                    totals["units"] += len(units)
                    if not units:
                        totals["skipped"] += 1
                    for unit in units:
                        payload = unit.model_dump() if hasattr(unit, "model_dump") else unit.dict()
                        by_domain.setdefault(unit.ip_domain, []).append(payload)
            if not args.dry_run:
                for domain, payloads in by_domain.items():
                    destination = output_path(args.data_root.resolve(), path, domain)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_suffix(destination.suffix + ".tmp")
                    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                        for payload in payloads:
                            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                    temporary.replace(destination)
                    print(f"[OK] {path.name}: {len(payloads)} units -> {destination}")
            else:
                print(f"[DRY] {path.name}: {sum(map(len, by_domain.values()))} units")
            totals["files"] += 1
        except Exception as exc:  # 单文件失败不阻断批处理
            totals["failed"] += 1
            print(f"[FAIL] {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(json.dumps(totals, ensure_ascii=False))
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
