"""Stable read-only query interfaces for evidence-backed IP research."""

from .agent_api import get_entity, list_works, query_agent, search_evidence, search_hybrid
from .ip_query import IpQueryEngine

__all__ = ["IpQueryEngine", "search_evidence", "search_hybrid", "get_entity", "list_works", "query_agent"]
