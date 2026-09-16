"""Run a small, work-balanced local-model entity proposal pilot."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from src.processing.model_client import ModelClient
from src.processing.model_entity_proposer import propose


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local model entity proposal pilot")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-work", type=int, default=1)
    args = parser.parse_args()
    client = ModelClient()
    if client.provider != "ollama":
        raise RuntimeError("This pilot is restricted to the local Ollama provider")
    connection = sqlite3.connect(args.database)
    known = {row[0] for row in connection.execute("SELECT alias FROM entity_aliases")}
    known.update(row[0] for row in connection.execute(
        "SELECT canonical_name FROM rule_candidates WHERE candidate_type='domain_term'"
    ))
    known.update(row[0] for row in connection.execute(
        "SELECT mention_text FROM rule_candidates WHERE candidate_type='domain_term'"
    ))
    selected = Counter()
    counts = Counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("w", encoding="utf-8", newline="\n") as target:
            for line in args.evaluation.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                sample = json.loads(line)
                work_id = sample["work_id"]
                if selected[work_id] >= args.per_work:
                    continue
                selected[work_id] += 1
                window = {
                    "window_id": sample["window_id"], "work_id": work_id,
                    "chapter_id": sample["chapter_id"], "text": sample["text"],
                }
                try:
                    result = propose(window, client, known)
                except Exception as error:
                    counts["failed_windows"] += 1
                    target.write(json.dumps({"window_id": window["window_id"], "work_id": work_id,
                                             "status": "model_error", "error": str(error)}, ensure_ascii=False) + "\n")
                    continue
                counts["windows"] += 1
                counts["accepted"] += len(result["accepted"])
                counts["rejected"] += len(result["rejected"])
                for candidate in result["accepted"]:
                    support = connection.execute(
                        """SELECT COUNT(*) AS evidence_units,COUNT(DISTINCT sw.work_id) AS work_count
                           FROM text_units u JOIN source_works sw ON sw.source_id=u.source_id
                           WHERE instr(u.text,?)>0""", (candidate["name"],)
                    ).fetchone()
                    candidate["corpus_evidence_units"] = support[0]
                    candidate["corpus_work_count"] = support[1]
                target.write(json.dumps({**window, "text": None, "accepted": result["accepted"],
                                         "rejected": result["rejected"], "status": "candidate"},
                                        ensure_ascii=False, separators=(",", ":")) + "\n")
        print(json.dumps({"output": str(args.output), "model": client.model,
                          "selected_by_work": dict(selected), **counts}, ensure_ascii=False))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
