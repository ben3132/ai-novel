"""对 ContextWindow JSONL 执行无模型规则候选召回。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import yaml

from src.processing.rule_candidates import compile_terms, extract_candidates


CODE_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="上下文窗口 -> 斗罗规则候选")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--config", type=Path, default=CODE_ROOT / "config" / "domain_douluo.yaml")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    with args.config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    compiled_terms = compile_terms(config)
    total = Counter()
    for value in args.input:
        source = Path(value).resolve()
        path_hash = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
        base = source.name.removesuffix(".windows.jsonl")
        output = args.output_root.resolve() / f"{base}.{path_hash}.candidates.jsonl"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        counts = Counter()
        with source.open("r", encoding="utf-8") as reader, temporary.open("w", encoding="utf-8", newline="\n") as writer:
            for line in reader:
                if not line.strip():
                    continue
                window = json.loads(line)
                counts["windows"] += 1
                for candidate in extract_candidates(window, config, compiled_terms):
                    writer.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts["candidates"] += 1
                    counts[candidate["candidate_type"]] += 1
        temporary.replace(output)
        total.update(counts)
        print(json.dumps({"input": str(source), "output": str(output), **counts}, ensure_ascii=False))
    print(json.dumps({"files": len(args.input), **total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
