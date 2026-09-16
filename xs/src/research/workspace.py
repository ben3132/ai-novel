"""Durable research state shared by different agents and sessions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.storage.ip_paths import IpDataPaths, normalize_ip_domain


TRUST_LEVELS = {
    1: "official_primary",
    11: "third_party_transcription",
    2: "cited_fan_reference",
    3: "secondary_community",
    4: "low_reliability_excluded_from_reasoning",
}
SOURCE_STATUSES = {"discovered", "approved", "collecting", "collected", "failed", "rejected"}
CLAIM_STATUSES = {"candidate", "grounded", "verified", "conflicted", "rejected"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def validate_domain(value: str) -> str:
    return normalize_ip_domain(value)


class ResearchWorkspace:
    """JSON state store inside each IP's processed branch."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()

    def _directory(self, ip_domain: str) -> Path:
        return IpDataPaths(self.root, validate_domain(ip_domain)).research

    def _path(self, ip_domain: str) -> Path:
        return self._directory(ip_domain) / "research_state.json"

    def initialize_ip(
        self, ip_domain: str, name: str, aliases: list[str] | None = None,
        languages: list[str] | None = None, research_goal: str = "",
    ) -> dict:
        ip_domain = validate_domain(ip_domain)
        path = self._path(ip_domain)
        if path.exists():
            return self.load(ip_domain)
        now = utc_now()
        state = {
            "schema_version": 1,
            "ip": {
                "ip_domain": ip_domain, "name": name.strip(),
                "aliases": aliases or [], "languages": languages or ["zh", "en"],
                "research_goal": research_goal,
            },
            "works": [], "sources": [], "claims": [], "conflicts": [],
            "created_ts": now, "updated_ts": now,
        }
        self._save(ip_domain, state)
        self._event(ip_domain, "initialize_ip", {"name": name})
        return self.status(ip_domain)

    def load(self, ip_domain: str) -> dict:
        path = self._path(ip_domain)
        if not path.is_file():
            raise FileNotFoundError(f"Research IP is not initialized: {ip_domain}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, ip_domain: str, state: dict) -> None:
        directory = self._directory(ip_domain)
        directory.mkdir(parents=True, exist_ok=True)
        state["updated_ts"] = utc_now()
        temporary = directory / "research_state.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "research_state.json")

    def _event(self, ip_domain: str, operation: str, payload: dict) -> None:
        path = self._directory(ip_domain) / "events.jsonl"
        safe_payload = {key: value for key, value in payload.items() if "key" not in key.lower() and "token" not in key.lower()}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"ts": utc_now(), "operation": operation, "payload": safe_payload}, ensure_ascii=False) + "\n")

    def register_work(self, ip_domain: str, work: dict[str, Any]) -> dict:
        state = self.load(ip_domain)
        title = str(work.get("title", "")).strip()
        if not title:
            raise ValueError("work.title is required")
        work_id = str(work.get("work_id") or stable_id("work", ip_domain, title))
        if any(row["work_id"] == work_id for row in state["works"]):
            raise ValueError(f"work_id already exists: {work_id}")
        record = {
            "work_id": work_id, "title": title,
            "original_title": work.get("original_title"),
            "kind": work.get("kind", "unknown"),
            "continuity_id": work.get("continuity_id", "unresolved"),
            "release_date": work.get("release_date"),
            "parent_work_id": work.get("parent_work_id"),
            "canon_status": work.get("canon_status", "unknown"),
            "status": work.get("status", "candidate"),
            "notes": work.get("notes", ""),
        }
        state["works"].append(record)
        self._save(ip_domain, state)
        self._event(ip_domain, "register_work", {"work_id": work_id, "title": title})
        return record

    def register_source(self, ip_domain: str, source: dict[str, Any]) -> dict:
        state = self.load(ip_domain)
        url = str(source.get("url", "")).strip()
        if not url:
            raise ValueError("source.url is required")
        trust_level = int(source.get("trust_level"))
        if trust_level not in TRUST_LEVELS:
            raise ValueError(f"unsupported trust_level: {trust_level}")
        source_id = str(source.get("source_id") or stable_id("source", ip_domain, url))
        if any(row["source_id"] == source_id for row in state["sources"]):
            raise ValueError(f"source_id already exists: {source_id}")
        status = source.get("status", "discovered")
        if status not in SOURCE_STATUSES:
            raise ValueError(f"unsupported source status: {status}")
        record = {
            "source_id": source_id, "work_id": source.get("work_id"),
            "source_type": source.get("source_type", "unknown"), "url": url,
            "publisher": source.get("publisher"), "trust_level": trust_level,
            "trust_class": TRUST_LEVELS[trust_level], "status": status,
            "collector": source.get("collector"), "language": source.get("language"),
            "continuity_id": source.get("continuity_id", "unresolved"),
            "reason": source.get("reason", ""),
            "requires_cross_check": trust_level != 1,
            "eligible_for_reasoning": trust_level != 4,
            "discovered_ts": utc_now(),
        }
        state["sources"].append(record)
        self._save(ip_domain, state)
        self._event(ip_domain, "register_source", {"source_id": source_id, "url": url, "trust_level": trust_level})
        return record

    def update_source_status(self, ip_domain: str, source_id: str, status: str, note: str = "") -> dict:
        if status not in SOURCE_STATUSES:
            raise ValueError(f"unsupported source status: {status}")
        state = self.load(ip_domain)
        record = next((row for row in state["sources"] if row["source_id"] == source_id), None)
        if record is None:
            raise KeyError(source_id)
        record["status"] = status
        record["status_note"] = note
        record["status_ts"] = utc_now()
        self._save(ip_domain, state)
        self._event(ip_domain, "update_source_status", {"source_id": source_id, "status": status})
        return record

    def save_claim(self, ip_domain: str, claim: dict[str, Any]) -> dict:
        state = self.load(ip_domain)
        required = ("subject", "predicate", "object", "work_id", "evidence_window_ids")
        missing = [key for key in required if not claim.get(key)]
        if missing:
            raise ValueError(f"claim fields missing: {missing}")
        evidence_ids = list(dict.fromkeys(claim["evidence_window_ids"]))
        claim_id = str(claim.get("claim_id") or stable_id(
            "claim", ip_domain, claim["work_id"], claim["subject"], claim["predicate"], claim["object"], *evidence_ids,
        ))
        status = claim.get("status", "candidate")
        if status not in CLAIM_STATUSES:
            raise ValueError(f"unsupported claim status: {status}")
        levels = sorted({int(value) for value in claim.get("trust_levels", [])})
        if any(value not in TRUST_LEVELS for value in levels):
            raise ValueError("claim contains unsupported trust level")
        record = {
            "claim_id": claim_id, "subject": claim["subject"],
            "predicate": claim["predicate"], "object": claim["object"],
            "work_id": claim["work_id"],
            "continuity_id": claim.get("continuity_id", "unresolved"),
            "evidence_window_ids": evidence_ids,
            "source_ids": list(dict.fromkeys(claim.get("source_ids", []))),
            "trust_levels": levels, "status": status,
            "extraction_method": claim.get("extraction_method", "agent"),
            "needs_l1_cross_check": bool(levels) and 1 not in levels,
            "created_ts": utc_now(),
        }
        state["claims"].append(record)
        self._save(ip_domain, state)
        self._event(ip_domain, "save_claim", {"claim_id": claim_id, "status": status})
        return record

    def next_actions(self, ip_domain: str) -> list[dict]:
        state = self.load(ip_domain)
        actions = []
        if not state["works"]:
            actions.append({"priority": 1, "action": "discover_work_tree", "kind": "agent_task", "directly_executable": False, "reason": "No works registered"})
        if not state["sources"]:
            actions.append({"priority": 1, "action": "discover_sources", "kind": "agent_task", "directly_executable": False, "reason": "No sources registered"})
        for source in state["sources"]:
            if source["status"] in {"discovered", "approved", "failed"}:
                actions.append({
                    "priority": 2 if source["trust_level"] == 1 else 3,
                    "action": "collect_source", "source_id": source["source_id"],
                    "kind": "cli_workflow", "directly_executable": False,
                    "required_commands": ["run_l1_collect.py"],
                    "reason": f"source status is {source['status']}",
                })
        collected = [row for row in state["sources"] if row["status"] == "collected"]
        if collected and not state["claims"]:
            actions.append({
                "priority": 4, "action": "build_evidence_index",
                "kind": "cli_workflow", "directly_executable": False,
                "required_commands": ["run_process.py", "run_build_windows.py", "run_build_index.py"],
                "reason": "Collected sources have no claim candidates",
            })
        if any(row.get("needs_l1_cross_check") and row["status"] != "rejected" for row in state["claims"]):
            actions.append({"priority": 5, "action": "cross_check_l1", "kind": "agent_task", "directly_executable": False, "reason": "Claims lack independent L1 evidence"})
        return sorted(actions, key=lambda row: (row["priority"], row["action"], row.get("source_id", "")))

    def status(self, ip_domain: str) -> dict:
        state = self.load(ip_domain)
        return {
            "ip": state["ip"],
            "counts": {
                "works": len(state["works"]), "sources": len(state["sources"]),
                "collected_sources": sum(row["status"] == "collected" for row in state["sources"]),
                "claims": len(state["claims"]),
                "verified_claims": sum(row["status"] == "verified" for row in state["claims"]),
                "conflicts": len(state["conflicts"]),
            },
            "next_actions": self.next_actions(ip_domain),
            "updated_ts": state["updated_ts"],
        }
