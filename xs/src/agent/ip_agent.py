"""One stable router for research control-plane and evidence-query operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.query.agent_api import query_agent
from src.research.agent_tools import run_research_operation
from src.storage.ip_paths import default_data_root
from src.agent.guidance import get_agent_guidance


RESEARCH_OPERATIONS = {
    "initialize_ip", "get_research_state", "get_research_status",
    "register_work", "register_source", "update_source_status",
    "save_claim_candidate", "next_actions",
}
QUERY_OPERATIONS = {"list_works", "get_corpus_status", "get_entity", "search_evidence", "search_hybrid"}


def run_ip_agent(
    request: dict[str, Any], *, research_root: Path | str | None = None,
    database: Path | str | None = None, index_dir: Path | str | None = None,
    model_path: Path | str | None = None,
) -> dict:
    """Run one operation without embedding credentials in request data or state files."""
    operation = request.get("operation", "")
    if operation == "get_agent_guidance":
        return get_agent_guidance()
    if operation in RESEARCH_OPERATIONS:
        selected_root = research_root or os.environ.get("IP_RESEARCH_ROOT") or default_data_root()
        return run_research_operation(request, selected_root)
    if operation in QUERY_OPERATIONS:
        return query_agent(request, database=database, index_dir=index_dir, model_path=model_path)
    raise ValueError(f"Unsupported IP agent operation: {operation}")
