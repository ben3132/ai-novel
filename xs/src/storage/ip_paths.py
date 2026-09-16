"""Canonical IP-first data layout.

Code and data must live in different roots.  Inside the data root every IP owns
exactly two top-level data branches::

    data/ip/<ip_domain>/raw/        # immutable acquired material
    data/ip/<ip_domain>/processed/  # reproducible derived artifacts

This prevents rebuilding one IP from overwriting another IP's evidence database.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_IP_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def normalize_ip_domain(value: str) -> str:
    domain = value.strip().lower()
    if not _IP_RE.fullmatch(domain):
        raise ValueError("ip_domain must match ^[a-z][a-z0-9_-]{0,63}$")
    return domain


def default_data_root(code_root: Path | None = None) -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT") or os.environ.get("IP_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    root = (code_root or Path(__file__).resolve().parents[2]).resolve()
    return root.with_name(f"{root.name}_data")


@dataclass(frozen=True)
class IpDataPaths:
    data_root: Path
    ip_domain: str

    def __init__(self, data_root: Path | str, ip_domain: str):
        object.__setattr__(self, "data_root", Path(data_root).expanduser().resolve())
        object.__setattr__(self, "ip_domain", normalize_ip_domain(ip_domain))

    @property
    def root(self) -> Path:
        return self.data_root / "data" / "ip" / self.ip_domain

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def state(self) -> Path:
        return self.raw / "_state"

    @property
    def research(self) -> Path:
        return self.processed / "research"

    @property
    def units(self) -> Path:
        return self.processed / "units"

    @property
    def windows(self) -> Path:
        return self.processed / "windows"

    @property
    def index(self) -> Path:
        return self.processed / "index"

    @property
    def database(self) -> Path:
        return self.index / "evidence.sqlite3"

    @property
    def vector(self) -> Path:
        return self.processed / "vector"

    def raw_output(self, configured: str | Path) -> Path:
        """Map a legacy ``data/raw/<kind>/file`` config path into this IP."""
        value = Path(configured)
        if value.is_absolute():
            return value
        parts = value.parts
        if len(parts) >= 3 and parts[0] == "data" and parts[1] == "raw":
            value = Path(*parts[2:])
        return self.raw / value

    def source_material(self, configured: str | Path, category: str) -> Path:
        """Resolve local input into ``raw/source_material/<category>``.

        Legacy config paths are reduced to their filename so existing task files
        keep working after the one-time data migration.
        """
        value = Path(configured)
        if value.is_absolute():
            return value.resolve()
        return (self.raw / "source_material" / category / value.name).resolve()

    def ensure(self) -> "IpDataPaths":
        self.raw.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(parents=True, exist_ok=True)
        return self
