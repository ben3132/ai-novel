"""JSON stdin/stdout entry point for generic IP research agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.agent.ip_agent import run_ip_agent


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic IP research Agent interface")
    parser.add_argument("--request-json", default="-", help="JSON object or '-' for stdin")
    parser.add_argument("--research-root", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--index-dir", type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.request_json == "-" else args.request_json
        result = run_ip_agent(
            json.loads(raw), research_root=args.research_root, database=args.database,
            index_dir=args.index_dir, model_path=args.model_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

