"""Local BGE/FAISS index for evidence windows; no remote API is used."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


class VectorDependencyError(RuntimeError):
    pass


def database_fingerprint(database: Path) -> dict:
    stat = database.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def iter_windows(
    database: Path, batch_size: int = 256, ip_domain: str | None = None,
) -> Iterable[list[tuple[str, str]]]:
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
        if ip_domain:
            cursor = connection.execute(
                """SELECT w.window_id,w.text FROM context_windows w
                   JOIN sources s ON s.source_id=w.source_id
                   WHERE s.ip_domain=? ORDER BY w.window_id""", (ip_domain,),
            )
        else:
            cursor = connection.execute("SELECT window_id,text FROM context_windows ORDER BY window_id")
        while rows := cursor.fetchmany(batch_size):
            yield [(row[0], row[1]) for row in rows]


def build_vector_index(
    database: Path | str,
    output_dir: Path | str,
    model_path: Path | str,
    batch_size: int = 64,
    progress: Callable[[int, int], None] | None = None,
    ip_domain: str | None = None,
    index_name: str | None = None,
) -> dict:
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise VectorDependencyError("Install faiss-cpu and sentence-transformers") from error

    database = Path(database).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    model_path = Path(model_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
        total = (
            connection.execute(
                """SELECT COUNT(*) FROM context_windows w JOIN sources s ON s.source_id=w.source_id
                   WHERE s.ip_domain=?""", (ip_domain,),
            ).fetchone()[0]
            if ip_domain else connection.execute("SELECT COUNT(*) FROM context_windows").fetchone()[0]
        )

    model = SentenceTransformer(str(model_path), local_files_only=True)
    index = None
    window_ids: list[str] = []
    completed = 0
    for rows in iter_windows(database, batch_size=batch_size, ip_domain=ip_domain):
        ids, texts = zip(*rows)
        vectors = model.encode(
            list(texts), batch_size=batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=False,
        ).astype("float32")
        if index is None:
            index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        window_ids.extend(ids)
        completed += len(rows)
        if progress:
            progress(completed, total)
    if index is None:
        raise RuntimeError("No context windows found")

    prefix = index_name or (f"{ip_domain}_windows" if ip_domain else "douluo_windows")
    if not prefix.replace("_", "").replace("-", "").isalnum():
        raise ValueError("index_name contains unsupported characters")
    index_tmp = output_dir / f"{prefix}.faiss.tmp"
    index_path = output_dir / f"{prefix}.faiss"
    metadata_tmp = output_dir / f"{prefix}.meta.json.tmp"
    metadata_path = output_dir / f"{prefix}.meta.json"
    faiss.write_index(index, str(index_tmp))
    metadata = {
        "schema_version": 1,
        "ip_domain": ip_domain,
        "index_name": prefix,
        "created_ts": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "database_fingerprint": database_fingerprint(database),
        "model_path": str(model_path),
        "model_name": model_path.name,
        "dimension": index.d,
        "count": index.ntotal,
        "normalized": True,
        "window_ids": window_ids,
        "window_ids_sha256": hashlib.sha256("\n".join(window_ids).encode()).hexdigest(),
    }
    metadata_tmp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    index_tmp.replace(index_path)
    metadata_tmp.replace(metadata_path)
    return {**metadata, "index_path": str(index_path), "metadata_path": str(metadata_path)}


class FaissEvidenceIndex:
    def __init__(
        self, index_dir: Path | str, model_path: Path | str | None = None,
        index_name: str = "douluo_windows",
    ):
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise VectorDependencyError("Install faiss-cpu and sentence-transformers") from error
        self.index_dir = Path(index_dir).expanduser().resolve()
        self.metadata = json.loads((self.index_dir / f"{index_name}.meta.json").read_text(encoding="utf-8"))
        self.window_ids = self.metadata["window_ids"]
        self.index = faiss.read_index(str(self.index_dir / f"{index_name}.faiss"))
        selected_model = Path(model_path or self.metadata["model_path"]).expanduser().resolve()
        self.model = SentenceTransformer(str(selected_model), local_files_only=True)
        if self.index.ntotal != len(self.window_ids):
            raise RuntimeError("FAISS index and metadata count do not match")

    def validate_database(self, database: Path | str) -> None:
        database = Path(database).expanduser().resolve()
        if database_fingerprint(database) != self.metadata["database_fingerprint"]:
            raise RuntimeError("Evidence database changed; rebuild the vector index")

    def search(self, question: str, top_k: int = 50) -> list[dict]:
        vector = self.model.encode(
            [question], convert_to_numpy=True, normalize_embeddings=True,
            show_progress_bar=False,
        ).astype("float32")
        scores, positions = self.index.search(vector, min(top_k, self.index.ntotal))
        return [
            {"window_id": self.window_ids[position], "vector_score": float(score), "vector_rank": rank}
            for rank, (position, score) in enumerate(zip(positions[0], scores[0]), 1)
            if position >= 0
        ]
