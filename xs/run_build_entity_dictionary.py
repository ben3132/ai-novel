"""Build the candidate entity and alias dictionary without asserting identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.entity_dictionary import build_entity_dictionary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reviewable entity dictionary")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ip-domain", default="douluo")
    args = parser.parse_args()
    print(json.dumps(build_entity_dictionary(args.database, args.output, args.ip_domain), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
