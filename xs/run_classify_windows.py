"""小规模运行本地模型窗口分类，默认每个输入文件只取1个窗口。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from src.processing.model_client import ModelClient
from src.processing.rule_candidates import compile_terms
from src.processing.window_classifier import classify_window


def main() -> int:
    parser = argparse.ArgumentParser(description="本地模型窗口预分类")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--per-file", type=int, default=1)
    parser.add_argument("--domain-config", type=Path)
    parser.add_argument("--scan-limit", type=int, default=1000)
    args = parser.parse_args()
    if args.per_file < 1:
        parser.error("--per-file 必须大于0")
    client = ModelClient()
    terms = []
    if args.domain_config:
        with args.domain_config.open("r", encoding="utf-8") as handle:
            terms = compile_terms(yaml.safe_load(handle))
    total = failed = 0
    for value in args.input:
        source = Path(value).resolve()
        path_hash = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
        output = args.output_root.resolve() / f"{source.stem}.{path_hash}.classifications.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        selected = 0
        attempted = 0
        with source.open("r", encoding="utf-8") as reader:
            pool = []
            for line_no, line in enumerate(reader):
                if line_no >= args.scan_limit:
                    break
                if not line.strip():
                    continue
                window = json.loads(line)
                if len(window.get("text", "")) < 500:
                    continue
                score = sum(min(window["text"].count(literal), 5) * (2 if kind == "event_trigger" else 1) for literal, kind, _, _ in terms)
                pool.append((score, -line_no, window))
        pool.sort(key=lambda item: (item[0], item[1]), reverse=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as writer:
            for _, _, window in pool:
                if selected >= args.per_file or attempted >= args.per_file * 3:
                    break
                attempted += 1
                try:
                    result = classify_window(window, client)
                    writer.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                    writer.flush()
                    selected += 1
                    total += 1
                    print(f"[CLASSIFIED] {window.get('window_id')}", flush=True)
                except Exception as exc:
                    failed += 1
                    print(f"[FAIL] {window.get('window_id')}: {type(exc).__name__}: {exc}")
        temporary.replace(output)
        print(f"[OK] {source.name}: {selected} classifications -> {output}")
    print(json.dumps({"classifications": total, "failed": failed, "provider": client.provider, "model": client.model}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
