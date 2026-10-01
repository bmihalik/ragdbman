# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""One canonical operation catalog for REST, MCP, CLI and Python dispatch."""

import inspect
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from . import corpus
from .errors import require_confirmation
from .graph.query import GraphRequest
from .models import CreateCollection, Request


class Empty(Request):
    pass


class Describe(Request):
    collections: list[str] | None = None


class Named(Request):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class Collection(Request):
    collection: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ConfigUpdate(Named):
    description: str | None = None


class Delete(Named):
    confirm: bool = False
    delete_files: bool = False


class RootAdd(Collection):
    path: str = Field(min_length=1)
    recursive: bool = True


class RootRemove(Collection):
    root_id: str = Field(min_length=1)
    confirm: bool = False


class AddFile(Collection):
    path: str = Field(min_length=1)


class UploadFile(Collection):
    filename: str = Field(min_length=1)
    content_base64: str


class FileGet(Collection):
    source_id: str = Field(min_length=1)


class RemoveFile(FileGet):
    confirm: bool = False
    delete_original_managed_file: bool = False


class FilesList(Collection):
    extension: str | None = None
    path_prefix: str | None = None
    status: (
        Literal[
            "discovered", "extracting", "embedding", "indexed", "failed", "unsupported", "queued", "missing"
        ]
        | None
    ) = None
    limit: int = Field(50, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class ScanStart(Collection):
    root: str = Field(min_length=1)
    recursive: bool = True
    prune_missing: bool = False
    confirm: bool = False


class JobGet(Collection):
    job_id: str = Field(min_length=1)


class JobCancel(Request):
    job_id: str = Field(min_length=1)


class JobsList(Collection):
    status: (
        Literal["queued", "running", "paused", "completed", "completed_with_errors", "failed", "cancelled"]
        | None
    ) = None
    limit: int = Field(50, ge=1, le=1000)


class KeywordsList(Collection):
    query: str | None = None
    limit: int = Field(50, ge=1, le=10000)
    offset: int = Field(0, ge=0)


class Rebuild(Collection):
    confirm: bool = False


@dataclass(frozen=True)
class Operation:
    model: type[Request]
    description: str
    readonly: bool = True
    destructive: bool = False
    idempotent: bool = True


OPERATIONS = {
    "corpus_query": Operation(
        corpus.CorpusQuery,
        "Query one or more document, source-code or Knowledge Card "
        "collections. Modes: keyword, semantic, hybrid, structured. Expert perspective applies to cards. "
        "Use format=llm for readable evidence or raw for full metadata; structured mode rejects cards.",
    ),
    "corpus_graph": Operation(
        GraphRequest,
        "Read a source-code syntax graph: find, neighbors, callers, "
        "callees, dependencies, inheritance or impact. Static resolution is not a runtime call graph.",
    ),
    "corpus_describe": Operation(
        Describe, "Discover collections or describe selected collections and capabilities."
    ),
    "collections_registry_repair": Operation(
        Empty,
        "Reconstruct the registry from collection databases; "
        "no index rebuild. Reject while indexing is active.",
        False,
        True,
        True,
    ),
    "collections_list": Operation(Empty, "List collection configuration and counts for the administrator."),
    "collection_get": Operation(Named, "Inspect one collection's settings and counts."),
    "collection_create": Operation(
        CreateCollection,
        "Create an empty collection; probes its embedding model. Registering roots does not start scanning.",
        False,
        False,
        False,
    ),
    "collection_config_update": Operation(
        ConfigUpdate,
        "Set the description; omission clears it. Kind, embedding model and chunk settings are immutable.",
        False,
        True,
        True,
    ),
    "collection_delete": Operation(
        Delete,
        "Delete collection indexes with confirm=true. "
        "delete_files also deletes managed originals, never external roots.",
        False,
        True,
        False,
    ),
    "collection_list_files": Operation(
        FilesList, "List tracked files, statuses and source IDs with pagination."
    ),
    "collection_get_file": Operation(FileGet, "Inspect file metadata and diagnostics by source ID."),
    "collection_add_file": Operation(
        AddFile, "Index one allowed existing file; wait for completion.", False, True, False
    ),
    "collection_upload_file": Operation(
        UploadFile, "Upload base64 content to managed storage and index it.", False, False, False
    ),
    "collection_remove_file": Operation(
        RemoveFile,
        "Remove source index data with confirm=true; optional original deletion is limited to managed files.",
        False,
        True,
        False,
    ),
    "collection_list_roots": Operation(Collection, "List registered roots and their IDs."),
    "collection_add_root": Operation(
        RootAdd, "Register an allowed directory without scanning.", False, False, True
    ),
    "collection_remove_root": Operation(
        RootRemove, "Unregister a root with confirm=true; keep files and indexes.", False, True, True
    ),
    "scan_start": Operation(
        ScanStart,
        "Start incremental directory indexing. Missing-file pruning requires confirm=true.",
        False,
        True,
        False,
    ),
    "scan_jobs_list": Operation(JobsList, "List indexing jobs by collection and optional status."),
    "scan_job_get": Operation(JobGet, "Inspect one job's progress, timing and errors."),
    "scan_job_cancel": Operation(
        JobCancel, "Request cooperative cancellation by globally unique job ID.", False, True, True
    ),
    "scan_job_resume": Operation(
        JobGet, "Resume paused or failed/partial work, resetting attempt counters.", False, True, False
    ),
    "collection_list_keywords": Operation(KeywordsList, "List canonical keyword vocabulary and frequencies."),
    "collection_list_metadata_fields": Operation(Collection, "List supported numeric/date filter fields."),
    "collection_export_manifest": Operation(
        Collection, "Return collection and source metadata, not a database backup."
    ),
    "collection_rebuild": Operation(
        Rebuild,
        "Clear derived indexes then reindex tracked files; confirm=true required.",
        False,
        True,
        False,
    ),
    "collection_vacuum": Operation(
        Collection, "Reclaim unused primary SQLite pages; does not reindex.", False, False, True
    ),
    "health_status": Operation(Empty, "Check engine, vector extension and configured Ollama service."),
}
QUERY_OPERATIONS = frozenset({"corpus_query", "corpus_graph", "corpus_describe"})
JOB_OPERATIONS = frozenset({"scan_start", "scan_job_resume", "collection_rebuild"})


def validate(operation, values):
    req = OPERATIONS[operation].model.model_validate(values)
    if operation in {
        "collection_delete",
        "collection_remove_file",
        "collection_rebuild",
        "collection_remove_root",
    }:
        require_confirmation(req.confirm)
    if operation == "scan_start" and req.prune_missing:
        require_confirmation(req.confirm)
    return req


async def invoke(engine, operation, values, *, admin=True):
    """Validated dispatch, shared by transports; query credentials cannot select admin operations."""
    from .errors import RagError

    if not admin and operation not in QUERY_OPERATIONS:
        raise RagError("PATH_NOT_ALLOWED", "Operation requires administrative access")
    req = validate(operation, values)
    if operation == "corpus_query":
        return await corpus.corpus_query(engine, req, admin=admin)
    if operation == "corpus_describe":
        return corpus.corpus_describe(engine, req.collections, admin=admin)
    if operation == "corpus_graph":
        corpus.scope(engine, [req.collection], admin=admin)
        return await engine.corpus_graph(req)
    if operation == "collection_create":
        return await engine.collection_create(req)
    result = getattr(engine, operation)(**req.model_dump())
    return await result if inspect.isawaitable(result) else result


def signature(operation, *, mcp=False):
    """Flatten one shared request model into a callable schema for MCP discovery."""
    params = []
    for name, field in OPERATIONS[operation].model.model_fields.items():
        default = (
            inspect.Parameter.empty
            if field.is_required()
            else (field.default_factory() if field.default_factory else field.default)
        )
        if mcp and name == "format":
            default = "llm"
        params.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=field.rebuild_annotation()
            )
        )
    return inspect.Signature(params)
