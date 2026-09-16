"""候选窗口位置 -> 最小证据单元位置，结果写入 SQLite。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.processing.candidate_store import map_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="映射并去重规则候选")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--input", action="append", required=True)
    args = parser.parse_args()
    counts = map_candidates(args.database.resolve(), [Path(value).resolve() for value in args.input])
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
