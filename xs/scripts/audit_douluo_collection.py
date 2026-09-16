"""Validate the Douluo raw archive and write a machine-readable audit report."""

from __future__ import annotations

import json
import argparse
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml


CODE_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FIELDS = {
    "source_id", "trust_level", "source_type", "url", "collect_ts",
    "ip_domain", "raw_content", "extra_meta",
}


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record is not an object")
            records.append(value)
    return records


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (CODE_ROOT.parent / f"{CODE_ROOT.name}_data").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="审计独立数据目录中的斗罗采集结果")
    parser.add_argument("--data-root", help="数据根目录；默认与采集入口相同")
    args = parser.parse_args()
    data_root = Path(args.data_root).expanduser().resolve() if args.data_root else default_data_root()
    config = yaml.safe_load((CODE_ROOT / "config/source_config_l1.yaml").read_text(encoding="utf-8"))
    tasks = [
        task for task in config.get("tasks", [])
        if task.get("ip_domain") == "douluo" and task.get("enabled", True)
    ]

    raw_root = data_root / "data" / "ip" / "douluo" / "raw"
    events = load_jsonl(raw_root / "_state" / "collect_runs.jsonl")
    latest_status = {}
    for event in events:
        if event.get("source_key") and event.get("event") == "task_finished":
            latest_status[event["source_key"]] = event

    records = []
    validation_errors = []
    for path in sorted(raw_root.glob("**/*.jsonl")):
        if "_state" in path.parts:
            continue
        for line_number, record in enumerate(load_jsonl(path), 1):
            if record.get("ip_domain") != "douluo":
                continue
            missing = sorted(REQUIRED_FIELDS - record.keys())
            if missing:
                validation_errors.append({
                    "path": str(path.relative_to(data_root)),
                    "line": line_number,
                    "missing_fields": missing,
                })
            if record.get("trust_level") not in {1, 2, 3, 4, 11}:
                validation_errors.append({
                    "path": str(path.relative_to(data_root)),
                    "line": line_number,
                    "invalid_trust_level": record.get("trust_level"),
                })
            records.append(record)

    source_ids = [record.get("source_id") for record in records]
    duplicate_source_ids = sorted(
        source_id for source_id, count in Counter(source_ids).items()
        if source_id and count > 1
    )
    task_status = Counter(
        latest_status.get(task["source_key"], {}).get("status", "never_run")
        for task in tasks
    )
    blocked = []
    for task in tasks:
        event = latest_status.get(task["source_key"], {})
        if event.get("status") == "failed":
            blocked.append({
                "source_key": task["source_key"],
                "url": task.get("url"),
                "collector": task.get("collector"),
                "error_type": event.get("error_type"),
                "error_message": event.get("error_message"),
            })

    report = {
        "audit_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ip_domain": "douluo",
        "scope_statement": (
            "Publicly reachable configured sources only; no bypass of robots.txt, "
            "authentication, paywalls, DRM, or access controls. Raw content is not normalized."
        ),
        "configured_enabled_tasks": len(tasks),
        "task_status": dict(sorted(task_status.items())),
        "record_count": len(records),
        "raw_content_character_count": sum(len(record.get("raw_content", "")) for record in records),
        "unique_url_count": len({record.get("url") for record in records}),
        "trust_level_counts": dict(sorted(Counter(record.get("trust_level") for record in records).items())),
        "source_type_counts": dict(sorted(Counter(record.get("source_type") for record in records).items())),
        "continuity_counts": dict(sorted(Counter(
            record.get("extra_meta", {}).get("continuity", "unknown") for record in records
        ).items())),
        "warc_archived_record_count": sum(
            bool(record.get("extra_meta", {}).get("warc_archived")) for record in records
        ),
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "duplicate_source_id_count": len(duplicate_source_ids),
        "duplicate_source_ids": duplicate_source_ids,
        "blocked_or_unreachable_sources": blocked,
    }
    output = raw_root / "_state" / "douluo_collection_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if validation_errors or duplicate_source_ids else 0


if __name__ == "__main__":
    raise SystemExit(main())
