# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Shared application service used by REST, MCP, and the CLI.

SQLite writes are short transactions; extraction and network calls happen
outside transactions. One mutating job owns each collection, with bounded
file workers and one serialized persistent SQLite writer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import mimetypes
import re
import shutil
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import sqlite_vec

from . import db
from .chunking import Tokenizer, chunk_document, tokenizer_path
from .config import GlobalConfig
from .connections import CollectionDatabase
from .diagnostics import VERBOSE, dependency_counts
from .errors import RagError, require_confirmation
from .extract import SUPPORTED, atomic_write, extension, extract
from .extract.sniff import is_text_file
from .metadata import candidate_terms, extract_facts
from .models import CreateCollection, KnowledgeCardSearchRequest, MultiSearchRequest, SearchRequest
from .ollama import Embedder, Ollama
from .scanner import classify, discover, sha256_file
from .search import search
from .workers import _drain, run_async, run_executor, run_sync

log = logging.getLogger(__name__)
PROGRESS = dict(
    discovered=0,
    unchanged=0,
    queued=0,
    processing=0,
    completed=0,
    failed=0,
    skipped=0,
    total=None,
    phase="queued",
    processing_started_at=None,
)


class Engine:
    def __init__(self, config: GlobalConfig, embedder: Embedder | None = None):
        from .knowledge_cards import Settings

        self.kc_settings = Settings.from_env()
        self.config = GlobalConfig.model_validate(config.model_dump())
        self.base = Path(config.storage.data_dir).expanduser().resolve()
        self.registry_path = Path(config.storage.registry_path).expanduser().resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or Ollama(config.ollama)
        self.tasks: dict[str, asyncio.Task] = {}
        self.active: dict[str, str] = {}
        self.cancel_flags: dict[str, threading.Event] = {}
        self.operation_tasks = set()
        self.shutting_down = False
        self.closed = False
        self._databases = {}
        self._database_lock = threading.Lock()
        # PyMuPDF uses process-global native state; do not parse two PDFs in
        # different worker threads at the same time within this engine.
        self.pdf_lock = asyncio.Lock()
        self.locks: dict[str, asyncio.Lock] = {}
        self.registry: dict[str, dict] = {}
        self.repair_registry()
        self.recover()
        log.info(
            "Engine ready collections=%d file_concurrency=%d embedding_concurrency=%d",
            len(self.registry),
            self.config.defaults.max_concurrent_files,
            self.config.ollama.max_concurrent_embedding_requests,
        )

    def _name(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name):
            raise RagError("CONFIG_INVALID", "Invalid collection name")

    def db_path(self, name: str) -> Path:
        self._name(name)
        return self.base / "collections" / name / f"{name}.sqlite"

    @contextmanager
    def connection(self, name: str):
        path = self.db_path(name)
        if name not in self.registry or not path.is_file():
            raise RagError("COLLECTION_NOT_FOUND", name)
        with self._database(name).connection() as conn:
            yield conn

    def _database(self, name):
        with self._database_lock:
            if name not in self._databases:
                self._databases[name] = CollectionDatabase(self.db_path(name))
            return self._databases[name]

    async def _write(self, collection, function, *args, on_cancel=None):
        database = self._database(collection)
        return await run_executor(database.executor, database.write, function, *args, on_cancel=on_cancel)

    def _save_registry(self):
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self.registry_path,
            json.dumps(
                {"schema_version": 1, "collections": list(self.registry.values()), "updated_at": db.now()},
                indent=2,
            ),
        )

    def repair_registry(self):
        self.registry = {}
        for path in sorted((self.base / "collections").glob("*/*.sqlite")):
            try:
                self._name(path.parent.name)
                conn = db.connect(path)
                try:
                    kind_row = conn.execute("SELECT kind FROM collection_meta LIMIT 1").fetchone()
                    db.initialize_schema(conn, kind_row[0] if kind_row else None)
                    collection = db.collection(conn, path)
                    self.registry[collection["name"]] = collection
                finally:
                    conn.close()
            except Exception:
                log.exception("Cannot reconcile collection %s; database left untouched", path)
        self._save_registry()
        return self.list_collections()

    def recover(self):
        for name in self.registry:
            with self.connection(name) as conn, db.transaction(conn):
                interrupted = conn.execute(
                    "SELECT 1 FROM jobs WHERE status IN ('running','queued') LIMIT 1"
                ).fetchone()
                conn.execute(
                    """UPDATE job_items SET stage='retryable',updated_at=? WHERE stage NOT IN
                    ('completed','failed','skipped')""",
                    (db.now(),),
                )
                conn.execute(
                    """UPDATE jobs SET status='paused',finished_at=COALESCE(finished_at,updated_at),
                    updated_at=?,error_summary=?
                    WHERE status IN ('running','queued')""",
                    (db.now(), "Interrupted by daemon restart; explicitly resume this job"),
                )
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=self.config.storage.audit_log_retention_days)
                ).isoformat()
                conn.execute("DELETE FROM audit_log WHERE created_at<?", (cutoff,))
                if interrupted:
                    db.refresh_keywords(conn)
                    log.warning(
                        "Recovered interrupted jobs collection=%s; keyword counts refreshed; explicit resume required",
                        name,
                    )

    def list_collections(self) -> list[dict]:
        return [self.get_collection(n) for n in sorted(self.registry)]

    def get_collection(self, name: str) -> dict:
        with self.connection(name) as conn:
            result = db.collection(conn, self.db_path(name))
            if result["kind"] == "knowledge_cards":
                result["knowledge_cards"] = self.kc_settings.model_dump()
            self.registry[name] = result
            return result

    def _tokenizer(self, collection: dict) -> Tokenizer:
        return Tokenizer(
            tokenizer_path(self.base, collection["embedding"]["model"]),
            self.config.defaults.allow_approximate_tokenizer,
        )

    async def create_collection(self, request: CreateCollection | None = None, **kwargs) -> dict:
        req = request or CreateCollection(**kwargs)
        self._not_busy(req.name)
        self._name(req.name)
        if req.name in self.registry or self.db_path(req.name).exists():
            raise RagError("CONFIG_INVALID", f"Collection {req.name} already exists")
        roots = [str(self.config.checked_path(p)) for p in req.source_roots]
        if any(not Path(p).is_dir() for p in roots):
            raise RagError("PATH_NOT_ALLOWED", "Every source root must be an existing directory")
        defaults = self.config.source_code if req.kind == "source_code" else self.config.defaults
        size = req.chunk_size_tokens if req.chunk_size_tokens is not None else defaults.chunk_size_tokens
        overlap = (
            req.chunk_overlap_tokens
            if req.chunk_overlap_tokens is not None
            else defaults.chunk_overlap_tokens
        )
        if req.kind == "knowledge_cards" and (
            req.chunk_size_tokens is not None or req.chunk_overlap_tokens is not None
        ):
            raise RagError(
                "CONFIG_INVALID", "Knowledge Cards embed whole fields; chunk overrides do not apply"
            )
        if req.kind != "knowledge_cards" and overlap >= size:
            raise RagError("CONFIG_INVALID", "Chunk overlap must be smaller than chunk size")
        model = req.embedding_model or (
            self.config.ollama.source_code_embedding_model
            if req.kind == "source_code"
            else self.config.ollama.embedding_model
        )
        tok = (
            Tokenizer(tokenizer_path(self.base, model), self.config.defaults.allow_approximate_tokenizer)
            if req.kind != "knowledge_cards"
            else None
        )
        if req.kind == "knowledge_cards":
            size, overlap = 0, 0
        # Probe before creating anything. Never publish a half-initialized collection.
        vector = (await self.embedder.embed(["ragdbman dimension probe"], model))[0]
        dimensions = len(vector)
        self._not_busy(req.name)
        # Recheck after yielding to the network: a concurrent request may have won.
        if req.name in self.registry or self.db_path(req.name).exists():
            raise RagError("CONFIG_INVALID", f"Collection {req.name} already exists")
        path = self.db_path(req.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = db.connect(path)
        try:
            db.initialize_schema(conn)
            with db.transaction(conn):
                for folder in ("files", "artifacts", "exports"):
                    (path.parent / folder).mkdir(exist_ok=True)
                timestamp = db.now()
                db.insert(
                    conn,
                    "collection_meta",
                    dict(
                        id=db.uid(),
                        name=req.name,
                        description=req.description,
                        managed_root=str(path.parent / "files"),
                        kind=req.kind,
                        embedding_provider="ollama",
                        embedding_model=model,
                        embedding_dimensions=dimensions,
                        embedding_keep_alive=self.config.ollama.keep_alive,
                        tokenizer=model,
                        tokenizer_mode=tok.mode if tok else "whole_field",
                        chunk_size_tokens=size,
                        chunk_overlap_tokens=overlap,
                        config_json=json.dumps(self.config.model_dump()),
                        created_at=timestamp,
                        updated_at=timestamp,
                    ),
                )
                if req.kind != "knowledge_cards":
                    db.ensure_vectors(conn, dimensions)
                for root in dict.fromkeys(roots):
                    db.insert(
                        conn,
                        "source_roots",
                        dict(id=db.uid(), path=root, recursive=1, status="active", created_at=db.now()),
                    )
                db.audit(conn, "create_collection")
            if req.kind == "knowledge_cards":
                from .knowledge_cards import initialize_schema as initialize_kc_schema

                initialize_kc_schema(conn)
            self.registry[req.name] = db.collection(conn, path)
            self._save_registry()
        except BaseException:
            conn.close()
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
            raise
        finally:
            conn.close()
        return self.get_collection(req.name)

    def _not_busy(self, name):
        if self.shutting_down:
            raise RagError("SERVER_SHUTTING_DOWN", "The daemon is shutting down")
        if name in self.active or self.locks.get(name, asyncio.Lock()).locked():
            raise RagError("COLLECTION_BUSY", f"Collection {name} has an active mutation")

    def update_collection_config(self, name: str, description: str | None = None, rebuild: bool = False):
        if rebuild:
            raise RagError("CONFIG_INVALID", "Use rebuild_collection explicitly")
        self._not_busy(name)
        with self.connection(name) as conn:
            conn.execute("UPDATE collection_meta SET description=?,updated_at=?", (description, db.now()))
        result = self.get_collection(name)
        self._save_registry()
        return result

    def delete_collection(self, name: str, confirm: bool = False, delete_files: bool = False):
        require_confirmation(confirm)
        self.get_collection(name)
        self._not_busy(name)
        path = self.db_path(name)
        # Persist destructive intent outside the database being deleted.
        log_path = self.base / "deletions.jsonl"
        with log_path.open("a") as stream:
            stream.write(
                json.dumps(
                    dict(
                        action="delete_collection", name=name, delete_files=delete_files, created_at=db.now()
                    )
                )
                + "\n"
            )
        database = self._databases.pop(name, None)
        if database:
            database.close()
        if delete_files:
            shutil.rmtree(path.parent)
        else:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        self.registry.pop(name)
        self._save_registry()
        return {"deleted": name}

    def list_source_roots(self, collection: str):
        with self.connection(collection) as conn:
            return db.rows(conn, "SELECT * FROM source_roots ORDER BY created_at")

    def add_source_root(self, collection: str, path: str, recursive: bool = True):
        meta = self.get_collection(collection)
        root = self.config.checked_path(path, meta["managed_root"])
        if not root.is_dir():
            raise RagError("PATH_NOT_ALLOWED", "Source root must be an existing directory")
        with self.connection(collection) as conn:
            existing = conn.execute("SELECT id FROM source_roots WHERE path=?", (str(root),)).fetchone()
            root_id = existing[0] if existing else db.uid()
            if not existing:
                db.insert(
                    conn,
                    "source_roots",
                    dict(
                        id=root_id,
                        path=str(root),
                        recursive=int(recursive),
                        status="active",
                        created_at=db.now(),
                    ),
                )
        return {"root_id": root_id}

    def remove_source_root(self, collection: str, root_id: str):
        self._not_busy(collection)
        with self.connection(collection) as conn, db.transaction(conn):
            conn.execute("UPDATE sources SET root_id=NULL WHERE root_id=?", (root_id,))
            conn.execute("DELETE FROM source_roots WHERE id=?", (root_id,))
        return {"removed": root_id}

    def list_sources(
        self,
        collection: str,
        extension: str | None = None,
        path_prefix: str | None = None,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ):
        clauses, params = ["deleted_at IS NULL"], []
        if extension:
            clauses.append("extension=?")
            params.append(extension.lstrip(".").lower())
        if path_prefix:
            clauses.append("substr(canonical_path,1,length(?))=?")
            params += [path_prefix, path_prefix]
        if status:
            clauses.append("status=?")
            params.append(status)
        with self.connection(collection) as conn:
            result = db.rows(
                conn,
                "SELECT * FROM sources WHERE "
                + " AND ".join(clauses)
                + " ORDER BY original_filename,id LIMIT ? OFFSET ?",
                (*params, max(1, min(limit, 10000)), max(0, offset)),
            )
        for source in result:
            source["collection_id"] = self.registry[collection]["id"]
        return result

    def get_source(self, collection: str, source_id: str):
        with self.connection(collection) as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE id=? AND deleted_at IS NULL", (source_id,)
            ).fetchone()
        if not row:
            raise RagError("SOURCE_NOT_FOUND", source_id)
        return {**dict(row), "collection_id": self.registry[collection]["id"]}

    async def add_file(self, collection: str, path: str, origin: str = "filesystem"):
        self._not_busy(collection)
        task = asyncio.current_task()
        self.operation_tasks.add(task)
        try:
            async with self.locks.setdefault(collection, asyncio.Lock()):
                return await self._index(collection, Path(path), origin=origin)
        finally:
            self.operation_tasks.discard(task)

    async def _index(
        self, collection: str, path: Path, origin="filesystem", root_id=None, job_id=None, meta=None
    ):
        started = time.monotonic()
        log.debug("Index start collection=%s job=%s path=%s", collection, job_id, path)
        meta = meta if meta is not None else self.get_collection(collection)
        path = self.config.checked_path(path, meta["managed_root"])
        if self.config.storage.markdown_sidecar_dir_name in path.parts:
            raise RagError("PATH_NOT_ALLOWED", "Sidecar output is never indexed as an original source")
        if not path.is_file():
            raise RagError("SOURCE_NOT_FOUND", str(path))
        stat = path.stat()
        if stat.st_size > self.config.defaults.max_file_size_mb * 1024 * 1024:
            raise RagError("FILE_TOO_LARGE", path.name)
        digest = await asyncio.to_thread(sha256_file, path)
        ext = extension(path)
        supported = ext in {"yaml", "yml"} if meta["kind"] == "knowledge_cards" else ext in SUPPORTED
        if not supported and meta["kind"] == "source_code":
            supported = await run_sync(is_text_file, path)
        prepared = await self._write(
            collection,
            self._prepare_source,
            collection,
            meta,
            path,
            origin,
            root_id,
            digest,
            ext,
            supported,
            stat,
        )
        source_id, classification = prepared["source_id"], prepared["classification"]
        if prepared["skipped"]:
            log.log(
                VERBOSE,
                "Index skipped collection=%s source=%s reason=%s",
                collection,
                path.name,
                classification,
            )
            return prepared
        try:
            if meta["kind"] == "knowledge_cards":
                from functools import partial

                from .knowledge_cards import fields, persist, read_card, validate_vectors

                raw, card = await run_sync(read_card, path)
                if card is None:
                    vectors = []
                else:
                    card_fields = fields(card)
                    vectors = await self.embedder.embed(
                        list(card_fields.values()),
                        meta["embedding"]["model"],
                        meta["embedding"]["dimensions"],
                        meta["embedding"]["keep_alive"],
                    )
                    validate_vectors(vectors, len(card_fields), meta["embedding"]["dimensions"])
                if await asyncio.to_thread(sha256_file, path) != digest:
                    raise RagError("EXTRACTION_FAILED", "Source changed during indexing; rescan to retry")
                stop = self.cancel_flags[job_id] if job_id else threading.Event()
                await self._write(
                    collection,
                    persist,
                    self.db_path(collection),
                    source_id,
                    path,
                    root_id,
                    digest,
                    stat,
                    raw,
                    card,
                    vectors,
                    stop,
                    partial(self.connection, collection),
                    on_cancel=stop.set,
                )
                log.log(
                    VERBOSE,
                    "Card indexed collection=%s source=%s fields=%d elapsed=%.3fs",
                    collection,
                    path.name,
                    len(vectors),
                    time.monotonic() - started,
                )
                return {
                    "source_id": source_id,
                    "chunks": 0,
                    "classification": classification if card is not None else "not_a_card",
                    "skipped": card is None,
                }
            extracted_at = time.monotonic()
            with dependency_counts() as counts:
                if ext == "pdf" and self.config.media.pdf_backend == "pymupdf":
                    async with self.pdf_lock:
                        document, markdown_path = await run_async(extract, path, self.config, meta["kind"])
                else:
                    document, markdown_path = await run_async(extract, path, self.config, meta["kind"])
            log.debug(
                "Extracted collection=%s source=%s extractor=%s chars=%d elapsed=%.3fs",
                collection,
                path.name,
                document.extractor_name,
                len(document.full_text),
                time.monotonic() - extracted_at,
            )
            if any(counts):
                document.warnings.append(
                    f"Extraction dependencies emitted {counts[0]} warnings and {counts[1]} errors"
                )
            if document.warnings:
                log.warning(
                    "Extraction warnings collection=%s source=%s: %s",
                    collection,
                    path.name,
                    "; ".join(document.warnings)[:2000],
                )
            if not document.full_text.strip():
                raise RagError("EXTRACTION_FAILED", "Extraction produced no text")
            tokenizer, chunks = await run_sync(self._chunk, document, meta)
            log.debug(
                "Chunked collection=%s source=%s chunks=%d tokenizer=%s",
                collection,
                path.name,
                len(chunks),
                tokenizer.mode,
            )
            await self._write(collection, self._source_status, collection, source_id, "embedding", None)
            embeddings = await self.embedder.embed(
                [c.text for c in chunks],
                meta["embedding"]["model"],
                meta["embedding"]["dimensions"],
                meta["embedding"]["keep_alive"],
            )
            if len(embeddings) != len(chunks) or any(
                len(v) != meta["embedding"]["dimensions"] or not all(math.isfinite(n) for n in v)
                for v in embeddings
            ):
                raise RagError("VECTOR_SCHEMA_MISMATCH", "Embedding count/dimension mismatch")
            if job_id and self.cancel_flags[job_id].is_set():
                raise RagError("JOB_CANCELLED", job_id)
            if await asyncio.to_thread(sha256_file, path) != digest:
                raise RagError("EXTRACTION_FAILED", "Source changed during indexing; rescan to retry")
            stop = self.cancel_flags[job_id] if job_id else threading.Event()
            await self._write(
                collection,
                self._persist_index,
                collection,
                meta,
                path,
                source_id,
                root_id,
                digest,
                stat,
                document,
                markdown_path,
                tokenizer.mode,
                chunks,
                embeddings,
                stop,
                job_id is None,
                on_cancel=stop.set,
            )
            log.log(
                VERBOSE,
                "Indexed collection=%s source=%s chunks=%d elapsed=%.3fs",
                collection,
                path.name,
                len(chunks),
                time.monotonic() - started,
            )
            return {
                "source_id": source_id,
                "chunks": len(chunks),
                "classification": classification,
                "skipped": False,
            }
        except BaseException as exc:
            if (
                meta["kind"] == "source_code"
                and ext not in SUPPORTED
                and isinstance(exc, RagError)
                and exc.code == "UNSUPPORTED_MEDIA_TYPE"
            ):
                await self._write(
                    collection, self._source_status, collection, source_id, "unsupported", str(exc)
                )
                return {"source_id": source_id, "chunks": 0, "classification": "unsupported", "skipped": True}
            await self._write(collection, self._index_failure, collection, source_id, job_id, exc)
            raise

    def _source_status(self, collection, source_id, status, detail):
        with self.connection(collection) as conn:
            conn.execute(
                "UPDATE sources SET status=?,status_detail=?,updated_at=? WHERE id=?",
                (status, detail, db.now(), source_id),
            )

    def _index_failure(self, collection, source_id, job_id, exc):
        self._source_status(collection, source_id, "failed", str(exc) or type(exc).__name__)
        with self.connection(collection) as conn:
            db.insert(
                conn,
                "errors",
                dict(
                    id=db.uid(),
                    job_id=job_id,
                    source_id=source_id,
                    error_code=getattr(exc, "code", "EXTRACTION_FAILED"),
                    message=str(exc) or type(exc).__name__,
                    created_at=db.now(),
                ),
            )
        if isinstance(exc, asyncio.CancelledError) or getattr(exc, "code", "") == "JOB_CANCELLED":
            log.debug("Index interrupted collection=%s source=%s", collection, source_id)
        else:
            log.error(
                "Index failed collection=%s source=%s error=%s",
                collection,
                source_id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__) if log.isEnabledFor(logging.DEBUG) else None,
            )

    def _prepare_source(self, collection, meta, path, origin, root_id, digest, ext, supported, stat):
        with self.connection(collection) as conn:
            existing_row = conn.execute(
                "SELECT * FROM sources WHERE canonical_path=? AND deleted_at IS NULL", (str(path),)
            ).fetchone()
            existing = dict(existing_row) if existing_row else None
            classification = classify(existing, digest, supported)
            if classification == "unchanged":
                return {
                    "source_id": existing["id"],
                    "chunks": 0,
                    "classification": "unchanged",
                    "skipped": True,
                }
            source_id = existing["id"] if existing else db.uid()
            if not existing:
                stamp = db.now()
                managed = Path(meta["managed_root"])
                db.insert(
                    conn,
                    "sources",
                    dict(
                        id=source_id,
                        root_id=root_id,
                        origin_type=origin,
                        original_path=str(path),
                        canonical_path=str(path),
                        original_filename=path.name,
                        managed_relative_path=str(path.relative_to(managed))
                        if path.is_relative_to(managed)
                        else None,
                        mime_type=mimetypes.guess_type(path.name)[0],
                        extension=ext,
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        discovered_at=stamp,
                        status="discovered",
                        created_at=stamp,
                        updated_at=stamp,
                    ),
                )
            if not supported:
                conn.execute(
                    "UPDATE sources SET status='unsupported',status_detail=?,updated_at=? WHERE id=?",
                    (
                        f"Unrecognized filename and no supported text detected: {path.name}"
                        if meta["kind"] == "source_code"
                        else f"Unsupported extension: {ext or '(none)'}",
                        db.now(),
                        source_id,
                    ),
                )
                return {"source_id": source_id, "chunks": 0, "classification": "unsupported", "skipped": True}
            conn.execute(
                "UPDATE sources SET status='extracting',updated_at=? WHERE id=?", (db.now(), source_id)
            )
        return {"source_id": source_id, "chunks": 0, "classification": classification, "skipped": False}

    def remove_source(
        self,
        collection: str,
        source_id: str,
        confirm: bool = False,
        delete_original_managed_file: bool = False,
    ):
        require_confirmation(confirm)
        self._not_busy(collection)
        source = self.get_source(collection, source_id)
        to_delete = None
        if delete_original_managed_file:
            managed = Path(self.get_collection(collection)["managed_root"]).resolve()
            candidate = Path(source["canonical_path"]).resolve()
            if not candidate.is_relative_to(managed):
                raise RagError("PATH_NOT_ALLOWED", "Original file deletion is restricted to managed uploads")
            to_delete = candidate
        with self.connection(collection) as conn, db.transaction(conn):
            db.delete_chunks(conn, source_id)
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            db.refresh_keywords(conn)
            db.audit(conn, "remove_source", self.registry[collection]["id"], source_id)
        if to_delete:
            to_delete.unlink(missing_ok=True)
        return {"removed": source_id}

    def start_scan(self, collection: str, root: str, recursive: bool = True, prune_missing: bool = False):
        meta = self.get_collection(collection)
        if collection in self.active:
            return self.get_job(collection, self.active[collection])
        self._not_busy(collection)
        root_path = self.config.checked_path(root, meta["managed_root"])
        if not root_path.is_dir():
            raise RagError("PATH_NOT_ALLOWED", "Scan root must be an existing directory")
        root_id = self.add_source_root(collection, str(root_path), recursive)["root_id"]
        job_id = db.uid()
        with self.connection(collection) as conn:
            db.insert(
                conn,
                "jobs",
                dict(
                    id=job_id,
                    collection_id=meta["id"],
                    kind="scan",
                    status="queued",
                    params_json=json.dumps(
                        dict(
                            root=str(root_path),
                            recursive=recursive,
                            prune_missing=prune_missing,
                            root_id=root_id,
                        )
                    ),
                    progress_json=json.dumps(PROGRESS),
                    created_at=db.now(),
                    updated_at=db.now(),
                ),
            )
        self._launch(collection, job_id)
        return self.get_job(collection, job_id)

    def _launch(self, collection, job_id):
        log.info(
            "Starting job collection=%s job=%s file_concurrency=%d",
            collection,
            job_id,
            self.config.defaults.max_concurrent_files,
        )
        self.active[collection] = job_id
        self.cancel_flags[job_id] = threading.Event()
        self.tasks[job_id] = asyncio.create_task(self._scan(collection, job_id), name=f"scan:{collection}")

    def get_job(self, collection: str, job_id: str):
        with self.connection(collection) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise RagError("JOB_NOT_FOUND", job_id)
            return db.decode_job(row)

    def list_jobs(self, collection: str, status: str | None = None, limit: int = 50):
        with self.connection(collection) as conn:
            query = (
                "SELECT * FROM jobs"
                + (" WHERE status=?" if status else "")
                + " ORDER BY created_at DESC LIMIT ?"
            )
            return [db.decode_job(r) for r in conn.execute(query, (status, limit) if status else (limit,))]

    def _job_update(self, collection, job_id, **fields):
        if "progress" in fields:
            fields["progress_json"] = json.dumps(fields.pop("progress"))
        fields["updated_at"] = db.now()
        with self.connection(collection) as conn:
            conn.execute(
                "UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                (*fields.values(), job_id),
            )

    async def _publish_job(self, collection, job_id, **fields):
        if "progress" in fields:
            fields["progress"] = dict(fields["progress"])
        await self._write(collection, partial(self._job_update, **fields), collection, job_id)

    def _job_item(self, collection, item_id, job_id=None, path=None, **fields):
        with self.connection(collection) as conn:
            if job_id:
                db.insert(
                    conn,
                    "job_items",
                    dict(
                        id=item_id,
                        job_id=job_id,
                        source_path=str(path),
                        stage="hashing",
                        created_at=db.now(),
                        updated_at=db.now(),
                    ),
                )
            else:
                fields["updated_at"] = db.now()
                conn.execute(
                    "UPDATE job_items SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                    (*fields.values(), item_id),
                )

    def _refresh_collection_keywords(self, collection):
        with self.connection(collection) as conn, db.transaction(conn):
            db.refresh_keywords(conn)

    async def _scan(self, collection, job_id):
        job = self.get_job(collection, job_id)
        params = job["params"]
        progress = dict(PROGRESS)
        seen = set()
        terminal = "completed"
        errors = []
        progress["phase"] = "discovering"
        try:
            await self._publish_job(
                collection,
                job_id,
                status="running",
                started_at=db.now(),
                finished_at=None,
                error_summary=None,
                progress=progress,
            )
            async with self.locks.setdefault(collection, asyncio.Lock()):
                scan_meta = self.get_collection(collection)
                if params.get("rebuild"):
                    with self.connection(collection) as conn:
                        paths = [
                            Path(r[0])
                            for r in conn.execute(
                                "SELECT canonical_path FROM sources WHERE deleted_at IS NULL AND canonical_path IS NOT NULL"
                            )
                        ]
                else:
                    yaml_only = scan_meta["kind"] == "knowledge_cards"
                    paths = await asyncio.to_thread(
                        lambda: [
                            p
                            for p in discover(Path(params["root"]), self.config, params["recursive"])
                            if not yaml_only or extension(p) in {"yaml", "yml"}
                        ]
                    )
                paths = await run_sync(lambda: list(dict.fromkeys(p.resolve() for p in paths)))
                progress.update(
                    total=len(paths),
                    discovered=len(paths),
                    phase="indexing",
                    processing_started_at=db.now(),
                )
                progress["queued"] = len(paths)
                await self._publish_job(collection, job_id, progress=progress)
                log.info("Discovered collection=%s job=%s total=%d", collection, job_id, len(paths))
                iterator = iter(paths)
                inflight = {}
                semaphore = asyncio.Semaphore(self.config.defaults.max_concurrent_files)
                last_logged = 0

                async def publish():
                    nonlocal last_logged
                    done = sum(progress[k] for k in ("completed", "unchanged", "failed", "skipped"))
                    progress["processing"] = len(inflight)
                    progress["queued"] = max(0, len(paths) - done - len(inflight))
                    await self._publish_job(
                        collection,
                        job_id,
                        progress=progress,
                        current_item=next(iter(inflight.values()), None),
                    )
                    if done > last_logged and (
                        done - last_logged >= self.config.defaults.scan_batch_size or done == len(paths)
                    ):
                        log.info(
                            "Job progress collection=%s job=%s processed=%d/%d in_flight=%d failed=%d",
                            collection,
                            job_id,
                            done,
                            len(paths),
                            len(inflight),
                            progress["failed"],
                        )
                        last_logged = done

                async def worker():
                    while not self.cancel_flags[job_id].is_set():
                        path = next(iterator, None)
                        if path is None:
                            return
                        async with semaphore:
                            seen.add(str(path))
                            item_id = db.uid()
                            inflight[item_id] = str(path)
                            await self._write(collection, self._job_item, collection, item_id, job_id, path)
                            await publish()
                            try:
                                outcome = await self._index(
                                    collection, path, root_id=params["root_id"], job_id=job_id, meta=scan_meta
                                )
                                key = (
                                    "unchanged"
                                    if outcome["classification"] == "unchanged"
                                    else "skipped"
                                    if outcome["skipped"]
                                    else "completed"
                                )
                                progress[key] += 1
                                await self._write(
                                    collection,
                                    partial(
                                        self._job_item,
                                        stage="skipped" if outcome["skipped"] else "completed",
                                        classification=outcome["classification"],
                                        source_id=outcome["source_id"],
                                    ),
                                    collection,
                                    item_id,
                                )
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                if self.cancel_flags[job_id].is_set() or (
                                    isinstance(exc, RagError) and exc.code == "JOB_CANCELLED"
                                ):
                                    return
                                progress["failed"] += 1
                                errors.append(f"{path.name}: {exc}")
                                await self._write(
                                    collection,
                                    partial(self._job_item, stage="failed", error_message=str(exc)),
                                    collection,
                                    item_id,
                                )
                                log.warning(
                                    "File failed collection=%s job=%s path=%s error=%s",
                                    collection,
                                    job_id,
                                    path,
                                    exc,
                                )
                            finally:
                                inflight.pop(item_id, None)
                            await publish()

                # A fixed number of worker tasks avoids one task per path and TaskGroup
                # drains all child cleanup before releasing collection mutation ownership.
                async with asyncio.TaskGroup() as group:
                    for _ in range(min(len(paths), self.config.defaults.max_concurrent_files)):
                        group.create_task(worker())
                if self.cancel_flags[job_id].is_set():
                    terminal = "cancelled"
                if params.get("prune_missing") and terminal != "cancelled":
                    progress["phase"] = "pruning"
                    await self._publish_job(collection, job_id, progress=progress, current_item=None)
                    stop = self.cancel_flags[job_id]
                    await self._write(
                        collection,
                        self._prune_missing,
                        collection,
                        params["root_id"],
                        seen,
                        job_id,
                        stop,
                        on_cancel=stop.set,
                    )
                if errors and terminal == "completed":
                    terminal = "completed_with_errors"
        except asyncio.CancelledError:
            terminal = "paused" if self.shutting_down else "cancelled"
        except Exception as exc:
            if isinstance(exc, RagError) and exc.code == "JOB_CANCELLED":
                terminal = "cancelled"
            else:
                terminal = "failed"
                errors.append(str(exc))
                log.exception("Scan worker failed")
        finally:
            progress["processing"] = 0
            progress["queued"] = max(
                0,
                (progress["total"] or 0)
                - sum(progress[k] for k in ("completed", "unchanged", "failed", "skipped")),
            )
            progress["phase"] = "finished" if terminal in {"completed", "completed_with_errors"} else terminal

            async def finalize():
                try:
                    if terminal in {"completed", "completed_with_errors"}:
                        progress["phase"] = "finalizing"
                        await self._publish_job(collection, job_id, progress=progress, current_item=None)
                    # Includes partially committed work on cancellation and per-file failures.
                    await self._write(collection, self._refresh_collection_keywords, collection)
                    progress["phase"] = (
                        "finished" if terminal in {"completed", "completed_with_errors"} else terminal
                    )
                    await self._publish_job(
                        collection,
                        job_id,
                        status=terminal,
                        progress=progress,
                        current_item=None,
                        error_summary="\n".join(errors[-20:]) or None,
                        finished_at=db.now(),
                    )
                    self.get_collection(collection)
                    self._save_registry()
                    log.info(
                        "Job finished collection=%s job=%s status=%s completed=%d unchanged=%d failed=%d skipped=%d",
                        collection,
                        job_id,
                        terminal,
                        progress["completed"],
                        progress["unchanged"],
                        progress["failed"],
                        progress["skipped"],
                    )
                except Exception as exc:
                    log.exception(
                        "Job finalization failed collection=%s job=%s; committed source data retained",
                        collection,
                        job_id,
                    )
                    progress["phase"] = "failed"
                    try:
                        await self._publish_job(
                            collection,
                            job_id,
                            status="failed",
                            progress=progress,
                            current_item=None,
                            error_summary=f"Finalization failed: {exc}",
                            finished_at=db.now(),
                        )
                    except Exception:
                        log.exception("Cannot persist final failure collection=%s job=%s", collection, job_id)
                finally:
                    self.active.pop(collection, None)
                    self.cancel_flags.pop(job_id, None)

            await _drain(asyncio.create_task(finalize()))

    def cancel_job(self, job_id: str):
        flag = self.cancel_flags.get(job_id)
        if flag:
            flag.set()
            task = self.tasks.get(job_id)
            if task and not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)
            log.info("Cancellation requested job=%s", job_id)
            return {"cancel_requested": job_id}
        for name in self.registry:
            try:
                self.get_job(name, job_id)
                self._job_update(name, job_id, status="cancelled", finished_at=db.now())
                return {"cancel_requested": job_id}
            except RagError as exc:
                if exc.code != "JOB_NOT_FOUND":
                    raise
        raise RagError("JOB_NOT_FOUND", job_id)

    def resume_job(self, collection: str, job_id: str):
        self._not_busy(collection)
        job = self.get_job(collection, job_id)
        if job["kind"] not in {"scan", "rebuild"} or job["status"] not in {
            "paused",
            "failed",
            "cancelled",
            "completed_with_errors",
        }:
            raise RagError("CONFIG_INVALID", "Only interrupted or failed scan/rebuild jobs can be resumed")
        self._job_update(
            collection,
            job_id,
            status="queued",
            finished_at=None,
            started_at=None,
            current_item=None,
            progress=dict(PROGRESS),
        )
        self._launch(collection, job_id)
        return self.get_job(collection, job_id)

    async def search(self, request: SearchRequest | dict):
        req = SearchRequest.model_validate(request) if isinstance(request, dict) else request
        meta = self.get_collection(req.collection)
        if meta["kind"] == "knowledge_cards":
            from .knowledge_cards import dump_cards

            if req.mode == "structured" or any(req.filters.model_dump().values()):
                raise RagError("CONFIG_INVALID", "Knowledge Cards do not support document structured filters")
            matches = await self.search_knowledge_cards(
                collection=req.collection, query=req.query, mode=req.mode, top_k=req.top_k
            )
            return dict(
                results=[
                    dict(
                        collection_id=meta["id"],
                        collection=req.collection,
                        chunk_id=m["card"]["id"],
                        source_id=m["source_id"],
                        citation_label=m["card"]["title"],
                        text=dump_cards([m["card"]]) if req.include_text else None,
                        score=m["rank_score"] if req.mode == "hybrid" else m["score"],
                        vector_score=m["vector_score"],
                        keyword_score=m["keyword_score"],
                    )
                    for m in matches
                ],
                applied_filters=[],
                skipped_filters=[],
            )
        with self.connection(req.collection) as conn:
            return await search(conn, meta, req, self.config, self.embedder)

    async def search_knowledge_cards(
        self,
        request: KnowledgeCardSearchRequest | dict | None = None,
        diagnostics: dict | None = None,
        **kwargs,
    ):
        from .knowledge_cards import retrieve, validate_vectors

        req = (
            KnowledgeCardSearchRequest.model_validate(request)
            if isinstance(request, dict)
            else request or KnowledgeCardSearchRequest(**kwargs)
        )
        meta = self.get_collection(req.collection)
        if meta["kind"] != "knowledge_cards":
            raise RagError("CONFIG_INVALID", f"{req.collection} is not a Knowledge Cards collection")
        settings = self.kc_settings
        limit = min(req.top_k or settings.default_top_k, self.config.search.max_top_k)
        minimum = settings.min_similarity if req.minimum_similarity is None else req.minimum_similarity
        vector = None
        if diagnostics is not None:
            diagnostics["keyword_fallback"] = False
        if req.mode != "keyword":
            try:
                vectors = await self.embedder.embed(
                    [req.query],
                    meta["embedding"]["model"],
                    meta["embedding"]["dimensions"],
                    meta["embedding"]["keep_alive"],
                )
                validate_vectors(vectors, 1, meta["embedding"]["dimensions"])
                vector = vectors[0]
            except RagError as exc:
                if req.mode != "hybrid" or exc.code != "OLLAMA_UNAVAILABLE":
                    raise
                log.warning("Knowledge Cards hybrid search using keyword fallback: %s", exc)
                if diagnostics is not None:
                    diagnostics["keyword_fallback"] = True
        return await run_sync(
            retrieve,
            self.db_path(req.collection),
            req,
            vector,
            settings,
            minimum,
            limit,
            self.config.search.rrf_k,
            partial(self.connection, req.collection),
        )

    async def search_multi(self, request: MultiSearchRequest | dict):
        req = MultiSearchRequest.model_validate(request) if isinstance(request, dict) else request
        successful, failed, results, applied, skipped = [], [], [], [], []
        for name in dict.fromkeys(req.collections):
            try:
                response = await self.search(
                    SearchRequest(
                        collection=name,
                        **req.model_dump(exclude={"collections", "top_k"}),
                        top_k=self.config.search.max_top_k,
                    )
                )
                successful.append(name)
                applied.extend(response["applied_filters"])
                skipped.extend(response["skipped_filters"])
                for rank, result in enumerate(response["results"], 1):
                    result["score"] = 1 / (self.config.search.rrf_k + rank)
                    results.append(result)
            except Exception as exc:
                failed.append({"collection": name, "reason": str(exc)})
        results.sort(key=lambda r: (-r["score"], r["collection_id"], r["chunk_id"]))
        limit = min(req.top_k or self.config.search.default_top_k, self.config.search.max_top_k)
        return dict(
            results=results[:limit],
            collections_searched=successful,
            collections_failed=failed,
            applied_filters=list(dict.fromkeys(applied)),
            skipped_filters=skipped,
        )

    def list_keywords(self, collection: str, query: str | None = None, limit: int = 50, offset: int = 0):
        with self.connection(collection) as conn:
            return db.rows(
                conn,
                "SELECT * FROM keywords WHERE instr(canonical_form,?)>0 "
                "ORDER BY chunk_frequency DESC,canonical_form LIMIT ? OFFSET ?",
                ((query or "").lower(), min(max(limit, 1), 10000), max(offset, 0)),
            )

    def list_metadata_fields(self, collection: str):
        with self.connection(collection) as conn:
            return db.rows(conn, "SELECT * FROM metadata_fields ORDER BY canonical_name")

    def rebuild_collection(self, collection: str, confirm: bool = False):
        require_confirmation(confirm)
        self._not_busy(collection)
        meta = self.get_collection(collection)
        # Rebuild indexes all existing source paths, including add_file/upload entries
        # which are not necessarily under a registered scan root.
        with self.connection(collection) as conn, db.transaction(conn):
            for source in db.rows(conn, "SELECT id FROM sources"):
                db.delete_chunks(conn, source["id"])
            conn.execute("UPDATE sources SET status='queued',content_hash_sha256=NULL")
            conn.execute("DELETE FROM keywords")
            db.audit(conn, "rebuild_collection", meta["id"])
        job_id = db.uid()
        with self.connection(collection) as conn:
            db.insert(
                conn,
                "jobs",
                dict(
                    id=job_id,
                    collection_id=meta["id"],
                    kind="rebuild",
                    status="queued",
                    params_json=json.dumps(
                        {
                            "root": meta["managed_root"],
                            "root_id": None,
                            "recursive": True,
                            "prune_missing": False,
                            "rebuild": True,
                        }
                    ),
                    progress_json=json.dumps(PROGRESS),
                    created_at=db.now(),
                    updated_at=db.now(),
                ),
            )
        self._launch(collection, job_id)
        return self.get_job(collection, job_id)

    def vacuum_collection(self, collection: str):
        self._not_busy(collection)
        with self.connection(collection) as conn:
            conn.execute("VACUUM")
            db.audit(conn, "vacuum_collection", self.registry[collection]["id"])
        return {"vacuumed": collection}

    def export_collection_manifest(self, collection: str):
        with self.connection(collection) as conn:
            sources = db.rows(conn, "SELECT * FROM sources ORDER BY canonical_path")
        return {"collection": self.get_collection(collection), "sources": sources, "exported_at": db.now()}

    async def health_status(self):
        try:
            vectors = await asyncio.wait_for(
                self.embedder.embed(["health"], self.config.ollama.embedding_model), timeout=3
            )
            reachable, dims, message = True, len(vectors[0]), None
        except TimeoutError:
            reachable, dims, message = False, None, "Ollama health probe timed out; it may be busy indexing"
        except Exception as exc:
            reachable, dims, message = False, None, str(exc)
        with closing(db.connect(":memory:")) as conn:
            vector_ok = bool(conn.execute("SELECT vec_version()").fetchone())
        return dict(
            daemon_ok=True,
            vector_extension_ok=vector_ok,
            ollama_reachable=reachable,
            ollama_model=self.config.ollama.embedding_model,
            ollama_dimensions=dims,
            message=message,
            active_jobs=len(self.active),
            collections=len(self.registry),
        )

    async def close(self):
        if self.closed:
            return
        self.request_shutdown()
        running = [task for task in self.tasks.values() if not task.done()]
        running.extend(
            task for task in self.operation_tasks if task is not asyncio.current_task() and not task.done()
        )
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        close = getattr(self.embedder, "close", None)
        if close:
            await close()
        for database in list(self._databases.values()):
            await asyncio.to_thread(database.close)
        self.closed = True
        log.info("Engine shutdown complete; tasks, clients and collection connections closed")

    def request_shutdown(self):
        if self.shutting_down:
            return
        self.shutting_down = True
        log.info(
            "Shutdown requested jobs=%d active_operations=%d", len(self.active), len(self.operation_tasks)
        )
        for flag in self.cancel_flags.values():
            flag.set()
        for task in list(self.tasks.values()) + list(self.operation_tasks):
            if not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)
        from .extract.process import terminate_all

        terminate_all()

    def _chunk(self, document, meta):
        tokenizer = self._tokenizer(meta)
        chunks = chunk_document(
            document, tokenizer, meta["chunking"]["size_tokens"], meta["chunking"]["overlap_tokens"]
        )
        return tokenizer, chunks

    def _prune_missing(self, collection, root_id, seen, job_id, stop):
        with self.connection(collection) as conn, db.transaction(conn):
            for source in db.rows(conn, "SELECT id,canonical_path FROM sources WHERE root_id=?", (root_id,)):
                if stop.is_set():
                    raise RagError("JOB_CANCELLED", job_id)
                source_path = Path(source["canonical_path"])
                # Only actually missing paths, not files excluded by changed policy.
                if str(source_path) not in seen and not source_path.exists():
                    db.delete_chunks(conn, source["id"])
                    conn.execute(
                        "UPDATE sources SET status='missing',updated_at=? WHERE id=?",
                        (db.now(), source["id"]),
                    )
                    db.audit(conn, "prune_missing", source_id=source["id"], job_id=job_id)
            if stop.is_set():
                raise RagError("JOB_CANCELLED", job_id)

    def _persist_index(
        self,
        collection,
        meta,
        path,
        source_id,
        root_id,
        digest,
        stat,
        document,
        markdown_path,
        tokenizer_mode,
        chunks,
        embeddings,
        stop,
        refresh=True,
    ):
        # The connection is created, used and closed on this worker thread.
        # The event-loop task keeps the collection lock until this returns.
        def check_cancel():
            if stop.is_set():
                raise RagError("JOB_CANCELLED", "Index write cancelled")

        check_cancel()
        log.debug(
            "Preparing index metadata collection=%s source=%s chunks=%d", collection, path.name, len(chunks)
        )
        # Metadata extraction does not hold a SQLite write transaction.
        metadata = [
            (
                extract_facts(c.text, self.config.defaults.locale),
                candidate_terms(c.text + " " + path.name + " " + (c.heading or "")),
            )
            for c in chunks
        ]
        keyword_links = []
        started = time.monotonic()
        with self.connection(collection) as conn, db.transaction(conn):
            db.ensure_vectors(conn, meta["embedding"]["dimensions"])
            db.delete_chunks(conn, source_id)
            artifact_id = None
            if self.config.defaults.store_derived_text:
                artifact_id = db.uid()
                db.insert(
                    conn,
                    "artifacts",
                    dict(
                        id=artifact_id,
                        source_id=source_id,
                        kind="extracted_text",
                        text_content=document.full_text,
                        path=markdown_path,
                        extractor_name=document.extractor_name,
                        extractor_version=document.extractor_version,
                        created_at=db.now(),
                    ),
                )
            fields = {r["canonical_name"]: r["id"] for r in db.rows(conn, "SELECT * FROM metadata_fields")}
            for chunk, vector, (facts, terms) in zip(chunks, embeddings, metadata, strict=True):
                check_cancel()
                chunk_id = db.uid()
                record = asdict(chunk)
                record.update(
                    id=chunk_id,
                    source_id=source_id,
                    artifact_id=artifact_id,
                    language=document.language,
                    embedding_model=meta["embedding"]["model"],
                    embedding_version=1,
                    created_at=db.now(),
                )
                seq = db.insert(conn, "chunks", record).lastrowid
                conn.execute(
                    "INSERT INTO chunks_vec0(rowid,embedding) VALUES (?,?)",
                    (seq, sqlite_vec.serialize_float32(vector)),
                )
                db.insert(conn, "chunk_vectors", dict(chunk_id=chunk_id, seq=seq, dims=len(vector)))
                conn.execute(
                    "INSERT INTO chunks_fts(rowid,text,heading,section_path,filename) VALUES (?,?,?,?,?)",
                    (seq, chunk.text, chunk.heading, chunk.section_path, path.name),
                )
                for fact in facts:
                    db.insert(
                        conn,
                        "chunk_numeric_values",
                        {
                            "id": db.uid(),
                            "chunk_id": chunk_id,
                            "source_id": source_id,
                            "field_id": fields[fact["field"]],
                            **{k: v for k, v in fact.items() if k not in {"field", "kind"}},
                        },
                    )
                keyword_links.append((chunk_id, terms))
            db.batch_keywords(conn, keyword_links)
            if refresh:
                db.refresh_keywords(conn)
            db.insert(
                conn,
                "source_versions",
                dict(
                    id=db.uid(),
                    source_id=source_id,
                    content_hash_sha256=digest,
                    indexed_at=db.now(),
                    created_at=db.now(),
                ),
            )
            conn.execute(
                """UPDATE sources SET status='indexed',status_detail=?,content_hash_sha256=?,
                extraction_hash=?,markdown_path=?,size_bytes=?,modified_at=?,page_count=?,duration_seconds=?,
                language=?,indexed_at=?,updated_at=?,root_id=COALESCE(?,root_id) WHERE id=?""",
                (
                    "\n".join(document.warnings) or None,
                    digest,
                    hashlib.sha256(document.full_text.encode()).hexdigest(),
                    markdown_path,
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    document.page_count,
                    document.duration_seconds,
                    document.language,
                    db.now(),
                    db.now(),
                    root_id,
                    source_id,
                ),
            )
            conn.execute(
                "UPDATE collection_meta SET tokenizer_mode=?,updated_at=?", (tokenizer_mode, db.now())
            )
            check_cancel()
        log.debug(
            "Committed index collection=%s source=%s chunks=%d transaction=%.3fs",
            collection,
            path.name,
            len(chunks),
            time.monotonic() - started,
        )
