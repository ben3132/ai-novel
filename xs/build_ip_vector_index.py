"""Build an independent local BGE/FAISS index for one IP domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.query.vector_index import build_vector_index
from src.storage.ip_paths import IpDataPaths, default_data_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one IP vector index")
    parser.add_argument("--ip-domain", required=True)
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    last_percent = -1

    def report(done: int, total: int) -> None:
        nonlocal last_percent
        percent = int(done * 100 / total)
        if percent >= last_percent + 5 or done == total:
            print(f"vector_index ip={args.ip_domain} progress={done}/{total} ({percent}%)", flush=True)
            last_percent = percent

    paths = IpDataPaths(args.data_root, args.ip_domain)
    result = build_vector_index(
        args.database or paths.database, args.output_dir or paths.vector, args.model_path, batch_size=args.batch_size,
        progress=report, ip_domain=args.ip_domain,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "window_ids"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
