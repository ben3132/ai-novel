"""Generate the first conservative batch of grounded fact candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.explicit_fact_extractor import extract_explicit_facts


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract explicit grounded fact candidates")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(extract_explicit_facts(args.database, args.output, args.limit), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
