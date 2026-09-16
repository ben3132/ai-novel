"""Single JSON-dictionary interface exposed to any tool-using agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .workspace import ResearchWorkspace


def run_research_operation(request: dict[str, Any], research_root: Path | str) -> dict:
    store = ResearchWorkspace(research_root)
    operation = request.get("operation")
    domain = request.get("ip_domain", "")
    if operation == "initialize_ip":
        return store.initialize_ip(
            domain, request.get("name", ""), aliases=request.get("aliases"),
            languages=request.get("languages"), research_goal=request.get("research_goal", ""),
        )
    if operation == "get_research_state":
        return store.load(domain)
    if operation == "get_research_status":
        return store.status(domain)
    if operation == "register_work":
        return store.register_work(domain, request.get("work", {}))
    if operation == "register_source":
        return store.register_source(domain, request.get("source", {}))
    if operation == "update_source_status":
        return store.update_source_status(
            domain, request.get("source_id", ""), request.get("status", ""), request.get("note", ""),
        )
    if operation == "save_claim_candidate":
        return store.save_claim(domain, request.get("claim", {}))
    if operation == "next_actions":
        return {"ip_domain": domain, "actions": store.next_actions(domain)}
    raise ValueError(f"Unsupported research operation: {operation}")

