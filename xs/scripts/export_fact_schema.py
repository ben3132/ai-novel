"""Export the exact JSON Schema expected from rule or model extractors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.processing.fact_models import AtomicFactCandidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Export atomic fact candidate JSON Schema")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema = AtomicFactCandidate.model_json_schema() if hasattr(AtomicFactCandidate, "model_json_schema") else AtomicFactCandidate.schema()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
