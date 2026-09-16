"""One-time migration from the legacy type-first data tree to IP-first storage.

The operation only moves files on the same data volume. It refuses to overwrite
an existing destination and supports ``--dry-run``. Current processed artifacts
belong to Douluo; raw JSONL/WARC files are routed by their embedded ip_domain.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def first_domain(path: Path) -> str | None:
    if path.suffix.lower() != ".jsonl":
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    value = json.loads(line).get("ip_domain")
                    return str(value).strip().lower() if value else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return None


class Migrator:
    def __init__(self, root: Path, dry_run: bool):
        self.root = root.resolve()
        self.dry_run = dry_run
        self.moves: list[tuple[Path, Path]] = []

    def move(self, source: Path, destination: Path) -> None:
        if not source.exists():
            return
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite: {destination}")
        self.moves.append((source, destination))
        print(f"{'DRY' if self.dry_run else 'MOVE'} {source} -> {destination}")
        if not self.dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

    def migrate_raw(self) -> None:
        legacy = self.root / "data" / "raw"
        if not legacy.is_dir():
            return
        for path in sorted(legacy.rglob("*")):
            if not path.is_file():
                continue
            if path.name == ".gitkeep":
                continue
            relative = path.relative_to(legacy)
            if relative.parts[0] == "warc" and len(relative.parts) >= 3:
                domain = relative.parts[1]
                tail = Path("warc", *relative.parts[2:])
            elif relative.parts[0] == "_state":
                domain = "douluo"
                tail = relative
            else:
                domain = first_domain(path)
                if not domain:
                    raise RuntimeError(f"Cannot determine ip_domain for raw file: {path}")
                tail = relative
            self.move(path, self.root / "data" / "ip" / domain / "raw" / tail)

    def migrate_processed(self) -> None:
        legacy = self.root / "data" / "processed"
        if not legacy.is_dir():
            return
        target = self.root / "data" / "ip" / "douluo" / "processed"
        for path in sorted(legacy.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(legacy)
            parts = list(relative.parts)
            if len(parts) >= 2 and parts[1] == "douluo":
                parts.pop(1)
            if parts == ["index", "ip_evidence.sqlite3"]:
                parts[-1] = "evidence.sqlite3"
            self.move(path, target / Path(*parts))

    def migrate_manual_sources(self) -> None:
        derived = self.root / "source_derived" / "text" / "douluo"
        if derived.is_dir():
            for path in sorted(derived.iterdir()):
                if path.is_file():
                    self.move(path, self.root / "data" / "ip" / "douluo" / "raw" / "source_material" / "derived_text" / path.name)

    def run(self) -> None:
        self.migrate_raw()
        self.migrate_processed()
        self.migrate_manual_sources()
        print(json.dumps({"dry_run": self.dry_run, "move_count": len(self.moves)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate data to data/ip/<ip>/{raw,processed}")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    Migrator(args.data_root, args.dry_run).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
