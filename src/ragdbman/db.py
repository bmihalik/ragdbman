# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""SQLite storage, idempotent schema initialization, and sqlite-vec helpers."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import sqlite_vec

from .errors import RagError
from .metadata import SYSTEM_FIELDS

log = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid4())


def rows(conn, query, params=()) -> list[dict]:
    return [dict(row) for row in conn.execute(query, params)]


def insert(conn, table: str, record: dict):
    # table/columns are internal constants, never request-provided SQL.
    keys = list(record)
    return conn.execute(
        f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
        [record[k] for k in keys],
    )


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def transaction(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def initialize_schema(conn, kind: str | None = None):
    """Create the complete collection schema and seed built-in metadata fields."""
    conn.executescript(files(__package__).joinpath("schema.sql").read_text(encoding="utf-8"))
    with transaction(conn):
        for name, (kind, aliases) in SYSTEM_FIELDS.items():
            conn.execute(
                """INSERT OR IGNORE INTO metadata_fields
                (id,canonical_name,display_name,value_type,aliases_json,created_at,is_system_field)
                VALUES (?,?,?,?,?,?,1)""",
                (uid(), name, name.replace("_", " ").title(), kind, json.dumps(aliases), now()),
            )
    if kind == "knowledge_cards":
        from .knowledge_cards import initialize_schema as initialize_kc_schema

        initialize_kc_schema(conn)


def ensure_vectors(conn, dimensions: int):
    if not isinstance(dimensions, int) or dimensions <= 0 or dimensions > 65536:
        raise RagError("VECTOR_SCHEMA_MISMATCH", "Invalid embedding dimensions")
    existing = conn.execute("SELECT sql FROM sqlite_master WHERE name='chunks_vec0'").fetchone()
    if existing:
        match = re.search(r"float\s*\[\s*(\d+)\s*\]", existing[0], re.I)
        if not match or int(match[1]) != dimensions:
            raise RagError("VECTOR_SCHEMA_MISMATCH", f"Vector table does not match {dimensions} dimensions")
    else:
        conn.execute(f"CREATE VIRTUAL TABLE chunks_vec0 USING vec0(embedding float[{dimensions}])")


def delete_chunks(conn, source_id: str):
    has_vectors = conn.execute("SELECT 1 FROM sqlite_master WHERE name='chunks_vec0'").fetchone()
    for row in conn.execute("SELECT seq FROM chunks WHERE source_id=?", (source_id,)).fetchall():
        conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (row[0],))
        if has_vectors:
            conn.execute("DELETE FROM chunks_vec0 WHERE rowid=?", (row[0],))
    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
    conn.execute("DELETE FROM artifacts WHERE source_id=?", (source_id,))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='kc_cards'").fetchone():
        conn.execute("DELETE FROM kc_cards WHERE source_id=?", (source_id,))


def refresh_keywords(conn):
    conn.execute("""UPDATE keywords SET chunk_frequency=(
        SELECT COUNT(*) FROM chunk_keywords ck WHERE ck.keyword_id=keywords.id),
        doc_frequency=(SELECT COUNT(DISTINCT c.source_id) FROM chunk_keywords ck
        JOIN chunks c ON c.id=ck.chunk_id WHERE ck.keyword_id=keywords.id)""")
    conn.execute("DELETE FROM keywords WHERE chunk_frequency=0")


def audit(conn, action, collection_id=None, source_id=None, job_id=None, detail=None):
    insert(
        conn,
        "audit_log",
        dict(
            id=uid(),
            actor="local",
            action=action,
            collection_id=collection_id,
            source_id=source_id,
            job_id=job_id,
            detail_json=json.dumps(detail or {}),
            created_at=now(),
        ),
    )


def collection(conn, database_path: Path) -> dict:
    meta = conn.execute("SELECT * FROM collection_meta LIMIT 1").fetchone()
    if not meta:
        raise RagError("DATABASE_CORRUPT", "Missing collection metadata")
    meta = dict(meta)
    statuses = dict(
        conn.execute("SELECT status,COUNT(*) FROM sources WHERE deleted_at IS NULL GROUP BY status")
    )
    latest = conn.execute(
        "SELECT finished_at FROM jobs WHERE kind='scan' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    card_count = (
        conn.execute(
            """SELECT COUNT(*) FROM kc_cards c JOIN sources s ON s.id=c.source_id
            WHERE s.status='indexed' AND s.deleted_at IS NULL"""
        ).fetchone()[0]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='kc_cards'").fetchone()
        else 0
    )
    return {
        "id": meta["id"],
        "name": meta["name"],
        "description": meta["description"],
        "database_path": str(database_path),
        "managed_root": meta["managed_root"],
        "source_roots": [r[0] for r in conn.execute("SELECT path FROM source_roots ORDER BY created_at")],
        "status": "ready" if meta["embedding_dimensions"] else "initializing",
        "kind": meta["kind"],
        "embedding": dict(
            provider=meta["embedding_provider"],
            model=meta["embedding_model"],
            dimensions=meta["embedding_dimensions"] or 0,
            keep_alive=meta["embedding_keep_alive"],
        ),
        "chunking": dict(
            tokenizer=meta["tokenizer"],
            tokenizer_mode=meta["tokenizer_mode"],
            size_tokens=meta["chunk_size_tokens"],
            overlap_tokens=meta["chunk_overlap_tokens"],
        ),
        "counts": dict(
            sources=sum(statuses.values()),
            indexed_sources=statuses.get("indexed", 0),
            failed_sources=statuses.get("failed", 0),
            chunks=conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            cards=card_count,
        ),
        "last_scan_at": latest[0] if latest else None,
        "created_at": meta["created_at"],
        "updated_at": meta["updated_at"],
    }


def decode_job(row, observed_at: datetime | None = None) -> dict:
    result = dict(row)
    result["params"] = json.loads(result.pop("params_json"))
    result["progress"] = json.loads(result.pop("progress_json"))
    progress = result["progress"]
    processed = sum(progress.get(k, 0) for k in ("completed", "unchanged", "failed", "skipped"))
    total = progress.get("total")
    complete = result["status"] in {"completed", "completed_with_errors"}
    progress["processed"] = processed
    progress["percent"] = (
        min(100.0, 100.0 * processed / total) if total else 100.0 if total == 0 and complete else None
    )
    active = result["status"] in {"queued", "running"}
    if not active:
        progress["phase"] = "finished" if complete else result["status"]
        progress["processing"] = 0

    def timestamp(value):
        return datetime.fromisoformat(value).astimezone(timezone.utc) if value else None

    end = (
        (observed_at or datetime.now(timezone.utc))
        if active
        else timestamp(result.get("finished_at") or result.get("updated_at"))
    )
    start = timestamp(result.get("started_at"))
    elapsed = max(0.0, (end - start).total_seconds()) if end and start else 0.0
    indexing_start = timestamp(progress.get("processing_started_at"))
    eta = None
    if complete:
        eta = 0.0
    elif (
        active and progress.get("phase") == "indexing" and processed and total is not None and indexing_start
    ):
        eta = max(0.0, (end - indexing_start).total_seconds()) / processed * max(0, total - processed)
    result["timing"] = {
        "elapsed_seconds": round(elapsed, 1),
        "estimated_remaining_seconds": round(eta, 1) if eta is not None else None,
        "estimate_basis": "current_attempt_average_file_rate",
    }
    return result
