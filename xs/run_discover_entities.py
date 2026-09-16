"""Discover new entity-name candidates without merging them automatically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.entity_discovery import discover


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover reviewable entity candidates")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-evidence", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(discover(args.database, args.output, args.minimum_evidence), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
