"""构建或查询 SQLite 证据索引。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.processing.index_store import build_index, search
from src.storage.ip_paths import IpDataPaths


CODE_ROOT = Path(__file__).resolve().parent


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    return Path(configured).resolve() if configured else CODE_ROOT.with_name(f"{CODE_ROOT.name}_data")


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite 证据索引")
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--database", type=Path)
    parser.add_argument("--ip-domain", required=True)
    parser.add_argument("--unit-input", action="append", default=[])
    parser.add_argument("--window-input", action="append", default=[])
    parser.add_argument("--query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    database = args.database.resolve() if args.database else IpDataPaths(args.data_root, args.ip_domain).database
    if args.query is not None:
        for row in search(database, args.query, args.limit):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if not args.unit_input or not args.window_input:
        parser.error("构建索引必须同时提供 --unit-input 和 --window-input")
    counts = build_index(
        database,
        [Path(value).resolve() for value in args.unit_input],
        [Path(value).resolve() for value in args.window_input],
    )
    print(json.dumps({"database": str(database), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
