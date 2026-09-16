"""把作品/卷/章节稳定层级写入证据 SQLite。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.processing.hierarchy import build_hierarchy


def main() -> int:
    parser = argparse.ArgumentParser(description="建立作品和章节层级")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    with args.config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    counts = build_hierarchy(args.database.resolve(), config["works"])
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
