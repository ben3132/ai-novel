"""Stable Python API for other agents; all operations are read-only and evidence-first."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .douluo_query import DouluoQueryEngine
from .ip_query import IpQueryEngine
from src.storage.ip_paths import IpDataPaths, default_data_root


def _database(database: str | Path | None, ip_domain: str) -> Path:
    value = database or os.environ.get("IP_EVIDENCE_DB")
    return Path(value) if value else IpDataPaths(default_data_root(), ip_domain).database


def search_evidence(
    question: str,
    works: Sequence[str] | None = None,
    top_k: int = 10,
    trust_levels: Sequence[int] = (1, 11),
    max_evidence_chars: int = 1200,
    database: str | Path | None = None,
    ip_domain: str = "douluo",
) -> dict:
    return IpQueryEngine(_database(database, ip_domain), ip_domain=ip_domain).search(
        question=question, works=works, top_k=top_k,
        trust_levels=trust_levels, max_evidence_chars=max_evidence_chars,
    )


def search_hybrid(
    question: str,
    works: Sequence[str] | None = None,
    top_k: int = 10,
    trust_levels: Sequence[int] = (1, 11),
    max_evidence_chars: int = 1200,
    database: str | Path | None = None,
    index_dir: str | Path | None = None,
    model_path: str | Path | None = None,
    ip_domain: str = "douluo",
) -> dict:
    from .hybrid_query import HybridIpQueryEngine

    selected_index = index_dir or os.environ.get("IP_VECTOR_INDEX_DIR") or IpDataPaths(default_data_root(), ip_domain).vector
    selected_model = model_path or os.environ.get("IP_EMBEDDING_MODEL")
    return HybridIpQueryEngine(
        _database(database, ip_domain), selected_index, model_path=selected_model, ip_domain=ip_domain,
    ).search(
        question=question, works=works, top_k=top_k,
        trust_levels=trust_levels, max_evidence_chars=max_evidence_chars,
    )


def list_works(database: str | Path | None = None, ip_domain: str = "douluo") -> list[dict]:
    return IpQueryEngine(_database(database, ip_domain), ip_domain=ip_domain).list_works()


def get_corpus_status(database: str | Path | None = None, ip_domain: str = "douluo") -> dict:
    return IpQueryEngine(_database(database, ip_domain), ip_domain=ip_domain).corpus_status()


def get_entity(
    name: str,
    works: Sequence[str] | None = None,
    top_k: int = 10,
    database: str | Path | None = None,
    ip_domain: str = "douluo",
) -> dict:
    response = search_evidence(name, works=works, top_k=top_k, database=database, ip_domain=ip_domain)
    response["entity_query"] = name
    response["entity_status"] = "evidence_mentions_only"
    return response


def query_agent(
    request: dict[str, Any], database: str | Path | None = None,
    index_dir: str | Path | None = None, model_path: str | Path | None = None,
) -> dict:
    operation = request.get("operation", "search_evidence")
    ip_domain = request.get("ip_domain", "douluo")
    if operation == "list_works":
        return {"operation": operation, "ip_domain": ip_domain, "works": list_works(database, ip_domain=ip_domain)}
    if operation == "get_corpus_status":
        return get_corpus_status(database, ip_domain=ip_domain)
    if operation == "get_entity":
        return get_entity(
            request.get("name", ""), works=request.get("works"),
            top_k=int(request.get("top_k", 10)), database=database, ip_domain=ip_domain,
        )
    if operation == "search_evidence":
        return search_evidence(
            request.get("question", ""), works=request.get("works"),
            top_k=int(request.get("top_k", 10)),
            trust_levels=tuple(request.get("trust_levels", [1, 11])),
            max_evidence_chars=int(request.get("max_evidence_chars", 1200)),
            database=database, ip_domain=ip_domain,
        )
    if operation == "search_hybrid":
        return search_hybrid(
            request.get("question", ""), works=request.get("works"),
            top_k=int(request.get("top_k", 10)),
            trust_levels=tuple(request.get("trust_levels", [1, 11])),
            max_evidence_chars=int(request.get("max_evidence_chars", 1200)),
            database=database, index_dir=index_dir, model_path=model_path, ip_domain=ip_domain,
        )
    raise ValueError(f"Unsupported operation: {operation}")
