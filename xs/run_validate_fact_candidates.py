"""Batch-check atomic fact candidates against immutable evidence windows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from src.processing.evidence_validator import validate_evidence


def dump_model(value) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else value.dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate JSONL fact candidates against the evidence database")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with args.input.open("r", encoding="utf-8") as source, args.output.open("w", encoding="utf-8", newline="\n") as target:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            counts["input"] += 1
            try:
                payload = json.loads(line)
                result = dump_model(validate_evidence(args.database, payload))
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as error:
                counts["invalid_schema"] += 1
                result = {
                    "fact_id": None,
                    "grounding_status": "rejected",
                    "semantic_review_status": "pending_review",
                    "rejection_reasons": ["invalid_candidate_schema"],
                    "input_line": line_number,
                    "error": str(error),
                }
            counts[result["grounding_status"]] += 1
            target.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"output": str(args.output), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
