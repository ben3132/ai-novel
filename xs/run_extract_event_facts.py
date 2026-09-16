"""Generate grounded event/state-change candidates from local evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.event_fact_extractor import extract_event_facts


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract grounded event candidates")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--per-work-limit", type=int)
    args = parser.parse_args()
    print(json.dumps(extract_event_facts(args.database, args.output, args.limit, args.per_work_limit), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
