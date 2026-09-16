"""Assign grounded facts to semantic review queues."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.semantic_triage import triage


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage fact candidates without approving them")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(triage(args.database, args.input, args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
