"""Extract explicit time/stage anchors around fact candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.temporal_anchor import extract_temporal_anchors


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract nearby temporal anchors")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radius", type=int, default=80)
    args = parser.parse_args()
    print(json.dumps(extract_temporal_anchors(args.database, args.input, args.output, args.radius), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
