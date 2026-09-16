"""IP-neutral evidence query entry point."""

from __future__ import annotations

from pathlib import Path

from .douluo_query import DouluoQueryEngine


class IpQueryEngine(DouluoQueryEngine):
    """Query one IP domain without allowing evidence to leak across domains."""

    def __init__(
        self, database: Path | str, ip_domain: str,
        work_aliases: dict[str, str] | None = None,
    ) -> None:
        super().__init__(database, ip_domain=ip_domain, work_aliases=work_aliases)

