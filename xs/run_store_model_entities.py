"""Load the reviewed model shortlist into its candidate-only SQLite tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.model_entity_store import store_model_entities


def main() -> int:
    parser = argparse.ArgumentParser(description="Store model entity candidates separately")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--shortlist", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(store_model_entities(args.database, args.shortlist), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
