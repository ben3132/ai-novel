"""Consolidate exact-grounded local-model proposals into a conservative shortlist."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


SUPPORTED_TYPES = {"person", "organization", "location", "creature"}
GENERIC_PERSON_SUFFIXES = ("者", "人", "哥", "姐", "弟", "妹")


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidate model entity proposal JSONL")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-proposals", type=int, default=2)
    parser.add_argument("--minimum-corpus-evidence", type=int, default=2)
    args = parser.parse_args()
    grouped = defaultdict(lambda: {"windows": set(), "works": set(), "rows": []})
    for line in args.input.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        batch = json.loads(line)
        for row in batch.get("accepted", []):
            key = (row["name"], row["entity_type"])
            grouped[key]["windows"].add(row["window_id"])
            grouped[key]["works"].add(row["work_id"])
            grouped[key]["rows"].append(row)
    accepted, rejected = [], []
    for (name, entity_type), item in grouped.items():
        sample = item["rows"][0]
        reasons = []
        if entity_type not in SUPPORTED_TYPES:
            reasons.append("type_requires_specialized_extractor")
        if entity_type == "person" and name.endswith(GENERIC_PERSON_SUFFIXES):
            reasons.append("generic_person_label")
        if re.search(r"[A-Za-z]", name):
            reasons.append("ascii_or_encoding_anomaly")
        if len(item["windows"]) < args.minimum_proposals:
            reasons.append("insufficient_independent_proposals")
        if sample.get("corpus_evidence_units", 0) < args.minimum_corpus_evidence:
            reasons.append("insufficient_corpus_evidence")
        record = {
            "name": name, "entity_type": entity_type,
            "proposal_window_count": len(item["windows"]), "proposal_work_count": len(item["works"]),
            "corpus_evidence_units": sample.get("corpus_evidence_units", 0),
            "corpus_work_count": sample.get("corpus_work_count", 0),
            "window_ids": sorted(item["windows"]), "status": "candidate",
            "method": "multi_window_model_entity_consolidation_v1",
        }
        if reasons:
            record["rejection_reasons"] = reasons
            rejected.append(record)
        else:
            accepted.append(record)
    accepted.sort(key=lambda row: (-row["proposal_window_count"], -row["corpus_evidence_units"], row["name"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"accepted": accepted, "rejected": rejected}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "accepted": len(accepted), "rejected": len(rejected)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
