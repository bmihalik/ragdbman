# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Action-specific management contracts; no arbitrary command or method dispatch."""

import base64
import binascii
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import Field

from . import db
from .errors import RagError, require_confirmation
from .models import CreateCollection, Request
from .workers import run_sync


class Create(CreateCollection):
    action: Literal["create"]


class Inspect(Request):
    action: Literal["inspect", "manifest", "vacuum", "roots"]
    collection: str


class Health(Request):
    action: Literal["health"]


class Update(Request):
    action: Literal["update"]
    collection: str
    description: str


class Delete(Request):
    action: Literal["delete"]
    collection: str
    confirm: bool = False
    delete_files: bool = False


class RegisterRoot(Request):
    action: Literal["register_root"]
    collection: str
    path: str
    recursive: bool = True


class UnregisterRoot(Request):
    action: Literal["unregister_root"]
    collection: str
    root_id: str
    confirm: bool = False


class Sources(Request):
    action: Literal["sources"]
    collection: str
    limit: int = Field(50, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class Source(Request):
    action: Literal["source"]
    collection: str
    source_id: str


Manage = Annotated[
    Union[Create, Inspect, Health, Update, Delete, RegisterRoot, UnregisterRoot, Sources, Source],
    Field(discriminator="action"),
]


class AddFile(Request):
    action: Literal["add_file"]
    collection: str
    path: str


class Upload(Request):
    action: Literal["upload"]
    collection: str
    filename: str = Field(min_length=1)
    content_base64: str


class Scan(Request):
    action: Literal["scan"]
    collection: str
    root: str
    recursive: bool = True
    prune_missing: bool = False
    confirm: bool = False


class Rebuild(Request):
    action: Literal["rebuild"]
    collection: str
    confirm: bool = False


class RemoveSource(Request):
    action: Literal["remove_source"]
    collection: str
    source_id: str
    confirm: bool = False
    delete_original_managed_file: bool = False


Ingest = Annotated[Union[AddFile, Upload, Scan, Rebuild, RemoveSource], Field(discriminator="action")]


class ListJobs(Request):
    action: Literal["list"]
    collection: str
    status: str | None = None
    limit: int = Field(50, ge=1, le=1000)


class Job(Request):
    action: Literal["inspect", "cancel", "resume"]
    collection: str
    job_id: str


Jobs = Annotated[Union[ListJobs, Job], Field(discriminator="action")]


async def manage(engine, req):
    if isinstance(req, Create):
        return await engine.create_collection(CreateCollection(**req.model_dump(exclude={"action"})))
    if isinstance(req, Health):
        return await engine.health_status()
    if isinstance(req, Update):
        return engine.update_collection_config(req.collection, req.description)
    if isinstance(req, Delete):
        return engine.delete_collection(req.collection, req.confirm, req.delete_files)
    if isinstance(req, RegisterRoot):
        return engine.add_source_root(req.collection, req.path, req.recursive)
    if isinstance(req, UnregisterRoot):
        require_confirmation(req.confirm)
        return engine.remove_source_root(req.collection, req.root_id)
    if isinstance(req, Sources):
        return engine.list_sources(req.collection, limit=req.limit, offset=req.offset)
    if isinstance(req, Source):
        return engine.get_source(req.collection, req.source_id)
    return {
        "inspect": engine.get_collection,
        "manifest": engine.export_collection_manifest,
        "vacuum": engine.vacuum_collection,
        "roots": engine.list_source_roots,
    }[req.action](req.collection)


async def ingest(engine, req):
    if isinstance(req, AddFile):
        return await engine.add_file(req.collection, req.path)
    if isinstance(req, Rebuild):
        return engine.rebuild_collection(req.collection, req.confirm)
    if isinstance(req, RemoveSource):
        return engine.remove_source(
            req.collection, req.source_id, req.confirm, req.delete_original_managed_file
        )
    if isinstance(req, Scan):
        if req.prune_missing:
            require_confirmation(req.confirm)
        return engine.start_scan(req.collection, req.root, req.recursive, req.prune_missing)
    if req.filename in {".", ".."} or any(c in req.filename for c in "/\\\0"):
        raise RagError("PATH_NOT_ALLOWED", "Upload filename must be a single filename")
    maximum = engine.config.defaults.max_file_size_mb * 1024 * 1024
    if len(req.content_base64) > 4 * ((maximum + 2) // 3):
        raise RagError("FILE_TOO_LARGE", "Upload exceeds configured limit")
    try:
        data = await run_sync(lambda: base64.b64decode(req.content_base64, validate=True))
    except (ValueError, binascii.Error) as exc:
        raise RagError("CONFIG_INVALID", "Invalid base64 upload") from exc
    if len(data) > maximum:
        raise RagError("FILE_TOO_LARGE", "Upload exceeds configured limit")
    meta = engine.get_collection(req.collection)
    engine._not_busy(req.collection)
    target = Path(meta["managed_root"]) / f"{db.uid()}-{req.filename}"
    engine.config.checked_path(target, meta["managed_root"])
    await run_sync(target.write_bytes, data)
    # Keep a failed upload for source diagnostics and retry, like the REST uploader.
    return await engine.add_file(req.collection, str(target), origin="upload")


def jobs(engine, req):
    if isinstance(req, ListJobs):
        return engine.list_jobs(req.collection, req.status, req.limit)
    engine.get_job(req.collection, req.job_id)  # Bind cancellation to the specified collection.
    if req.action == "cancel":
        return engine.cancel_job(req.job_id)
    if req.action == "resume":
        return engine.resume_job(req.collection, req.job_id)
    return engine.get_job(req.collection, req.job_id)
