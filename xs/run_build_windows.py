"""从 TextUnit JSONL 构建章节内上下文窗口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from src.processing.window_builder import build_context_windows
from src.storage.ip_paths import IpDataPaths


CODE_ROOT = Path(__file__).resolve().parent


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    return Path(configured).resolve() if configured else CODE_ROOT.with_name(f"{CODE_ROOT.name}_data")


def payloads(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def destination(data_root: Path, input_path: Path, ip_domain: str) -> Path:
    path_hash = hashlib.sha256(str(input_path.resolve()).encode("utf-8")).hexdigest()[:10]
    base = input_path.name.removesuffix(".units.jsonl")
    return IpDataPaths(data_root, ip_domain).windows / f"{base}.{path_hash}.windows.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="TextUnit JSONL -> 章节内模型上下文窗口")
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--target-chars", type=int, default=1000)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--overlap-units", type=int, default=2)
    args = parser.parse_args()

    failed = 0
    total_windows = 0
    for value in args.input:
        input_path = Path(value).resolve()
        try:
            iterator = build_context_windows(
                payloads(input_path),
                target_chars=args.target_chars,
                max_chars=args.max_chars,
                overlap_units=args.overlap_units,
            )
            temporary_paths: dict[str, tuple[Path, object]] = {}
            counts: dict[str, int] = {}
            try:
                for window in iterator:
                    if window.ip_domain not in temporary_paths:
                        output = destination(args.data_root.resolve(), input_path, window.ip_domain)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        temporary = output.with_suffix(output.suffix + ".tmp")
                        temporary_paths[window.ip_domain] = (output, temporary.open("w", encoding="utf-8", newline="\n"))
                        counts[window.ip_domain] = 0
                    output, handle = temporary_paths[window.ip_domain]
                    data = window.model_dump() if hasattr(window, "model_dump") else window.dict()
                    handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts[window.ip_domain] += 1
                    total_windows += 1
            finally:
                for output, handle in temporary_paths.values():
                    handle.close()
                    Path(handle.name).replace(output)
            print(f"[OK] {input_path.name}: {sum(counts.values())} windows")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {input_path}: {type(exc).__name__}: {exc}")
    print(json.dumps({"files": len(args.input), "windows": total_windows, "failed": failed}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
