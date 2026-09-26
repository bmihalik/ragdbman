# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""FastAPI REST, administrative UI, SSE, and MCP on one port."""

from __future__ import annotations

import asyncio
import base64
import hmac
import ipaddress
import json
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, UploadFile
from fastapi import Request as HTTPRequest
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from . import __version__, corpus, db
from .engine import Engine
from .errors import RagError
from .mcp_server import create_mcp
from .models import CreateCollection, KnowledgeCardSearchRequest, MultiSearchRequest, Request, SearchRequest


class RootBody(Request):
    path: str
    recursive: bool = True


class ScanBody(Request):
    root: str
    recursive: bool = True
    prune_missing: bool = False


class FileBody(Request):
    path: str


class ConfirmBody(Request):
    confirm: bool = False


class UpdateBody(Request):
    description: str | None = None
    rebuild: bool = False


class SecurityMiddleware:
    """Reject DNS rebinding/cross-origin writes and enforce a total body size."""

    def __init__(self, app, engine, admin_secret="", query_secret=""):
        self.app, self.engine = app, engine
        self.admin_secret, self.query_secret = admin_secret, query_secret

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        server = self.engine.config.server
        try:
            host = urlsplit("//" + headers.get("host", "")).hostname or ""
            origin = headers.get("origin")
            same_origin = not origin or (origin != "null" and urlsplit(origin).netloc == headers.get("host"))
        except ValueError:
            host, same_origin = "", False
        allowed = host in {"localhost", "testserver", server.bind}
        try:
            allowed = allowed or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if server.allow_remote_bind:
            allowed = True  # Remote requests still require authentication below.
        if not allowed or not same_origin:
            return await JSONResponse({"code": "PATH_NOT_ALLOWED", "message": "Host/origin rejected"}, 403)(
                scope, receive, send
            )
        path = scope["path"]
        query_path, admin_path = server.mcp_path + "/query", server.mcp_path + "/admin"
        query_route = path == query_path or path.startswith(query_path + "/")
        admin_route = path == admin_path or path.startswith(admin_path + "/")
        if admin_route and not server.mcp_admin_enabled:
            return await JSONResponse({"code": "NOT_FOUND", "message": "Admin MCP is disabled"}, 404)(
                scope, receive, send
            )
        auth = headers.get("authorization", "")
        supplied = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if query_route:
            secrets = [s for s in (self.query_secret, self.admin_secret) if s]
            if not secrets or not any(hmac.compare_digest(s.encode(), supplied.encode()) for s in secrets):
                return await JSONResponse(
                    {"code": "PATH_NOT_ALLOWED", "message": "Query MCP requires an authorized bearer token"},
                    401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
        elif (
            server.web_auth_mode != "local"
            or self.admin_secret
            or self.query_secret
            or server.mcp_admin_enabled
        ):
            # oauth_proxy trusts neither user headers nor a forwarded identity alone:
            # the reverse proxy must supply this secret after its own OAuth check.
            secret = self.admin_secret
            if (
                auth.startswith("Basic ")
                and server.web_auth_mode in {"password", "local"}
                and not admin_route
            ):
                try:
                    supplied = base64.b64decode(auth[6:], validate=True).decode().split(":", 1)[1]
                except (ValueError, IndexError, UnicodeDecodeError):
                    supplied = ""
            if not secret or not hmac.compare_digest(secret.encode(), supplied.encode()):
                response = JSONResponse(
                    {"code": "PATH_NOT_ALLOWED", "message": "Authentication required"},
                    401,
                    headers={"WWW-Authenticate": 'Basic realm="ragdbman"'},
                )
                return await response(scope, receive, send)
        maximum = self.engine.config.defaults.max_file_size_mb * 1024 * 1024 + 1024 * 1024
        if admin_route:
            # Base64 transport overhead; decoded upload limits are checked separately.
            maximum = (
                4 * ((self.engine.config.defaults.max_file_size_mb * 1024 * 1024 + 2) // 3) + 1024 * 1024
            )
        try:
            declared = int(headers.get("content-length", "0"))
        except ValueError:
            declared = maximum + 1
        if declared > maximum:
            return await JSONResponse({"code": "FILE_TOO_LARGE", "message": "Request too large"}, 413)(
                scope, receive, send
            )
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > maximum:
                raise RagError("FILE_TOO_LARGE", "Request too large")
            return message

        await self.app(scope, bounded_receive, send)


def create_app(engine: Engine, manage_engine: bool = True) -> FastAPI:
    admin_secret = os.environ.get("RAGDBMAN_AUTH_TOKEN", "")
    query_secret = os.environ.get("RAGDBMAN_QUERY_TOKEN", "")
    if (query_secret or engine.config.server.mcp_admin_enabled) and not admin_secret:
        raise RagError(
            "CONFIG_INVALID", "MCP access requires RAGDBMAN_AUTH_TOKEN to protect web/REST administration"
        )
    if query_secret and hmac.compare_digest(query_secret.encode(), admin_secret.encode()):
        raise RagError("CONFIG_INVALID", "Query and administrator tokens must differ")
    mcp = create_mcp(engine)
    mcp_app = mcp.streamable_http_app()
    admin_mcp = create_mcp(engine, admin=True) if engine.config.server.mcp_admin_enabled else None
    admin_app = admin_mcp.streamable_http_app() if admin_mcp else None

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(mcp.session_manager.run())
                if admin_mcp:
                    await stack.enter_async_context(admin_mcp.session_manager.run())
                yield
        finally:
            if manage_engine:
                await engine.close()

    app = FastAPI(title="ragdbman", version=__version__, lifespan=lifespan)
    app.state.engine, app.state.mcp = engine, mcp
    app.state.mcp_admin = admin_mcp
    app.add_middleware(
        SecurityMiddleware, engine=engine, admin_secret=admin_secret, query_secret=query_secret
    )

    @app.exception_handler(RagError)
    async def rag_error(request, exc):
        return JSONResponse(exc.as_dict(), exc.status_code)

    @app.get("/api/health")
    async def health():
        return await engine.health_status()

    @app.get("/api/collections")
    async def list_collections():
        return engine.list_collections()

    @app.post("/api/collections")
    async def create_collection(body: CreateCollection):
        return await engine.create_collection(body)

    @app.get("/api/collections/{name}")
    async def get_collection(name: str):
        return engine.get_collection(name)

    @app.patch("/api/collections/{name}")
    async def update_collection(name: str, body: UpdateBody):
        return engine.update_collection_config(name, **body.model_dump())

    @app.delete("/api/collections/{name}")
    async def delete_collection(name: str, confirm: bool = False, delete_files: bool = False):
        return engine.delete_collection(name, confirm, delete_files)

    @app.get("/api/collections/{name}/roots")
    async def list_roots(name: str):
        return engine.list_source_roots(name)

    @app.post("/api/collections/{name}/roots")
    async def add_root(name: str, body: RootBody):
        return engine.add_source_root(name, **body.model_dump())

    @app.delete("/api/collections/{name}/roots/{root_id}")
    async def remove_root(name: str, root_id: str):
        return engine.remove_source_root(name, root_id)

    @app.post("/api/collections/{name}/scan")
    async def scan(name: str, body: ScanBody):
        return engine.start_scan(name, **body.model_dump())

    @app.get("/api/collections/{name}/jobs")
    async def jobs(name: str, status: str | None = None, limit: int = 50):
        return engine.list_jobs(name, status, limit)

    @app.get("/api/collections/{name}/jobs/{job_id}")
    async def job(name: str, job_id: str):
        return engine.get_job(name, job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        return engine.cancel_job(job_id)

    @app.post("/api/collections/{name}/jobs/{job_id}/resume")
    async def resume(name: str, job_id: str):
        return engine.resume_job(name, job_id)

    @app.get("/api/collections/{name}/sources")
    async def sources(
        name: str,
        extension: str | None = None,
        path_prefix: str | None = None,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ):
        return engine.list_sources(name, extension, path_prefix, limit, offset, status)

    @app.get("/api/collections/{name}/sources/{source_id}")
    async def source(name: str, source_id: str):
        return engine.get_source(name, source_id)

    @app.delete("/api/collections/{name}/sources/{source_id}")
    async def remove_source(
        name: str, source_id: str, confirm: bool = False, delete_original_managed_file: bool = False
    ):
        return engine.remove_source(name, source_id, confirm, delete_original_managed_file)

    @app.post("/api/collections/{name}/add_file")
    async def add_file(name: str, body: FileBody):
        return await engine.add_file(name, body.path)

    @app.post("/api/collections/{name}/upload")
    async def upload(name: str, file: UploadFile):
        meta = engine.get_collection(name)
        filename = Path((file.filename or "upload").replace("\\", "/")).name
        filename = re.sub(r"[\x00-\x1f]", "_", filename)
        if filename in {"", ".", ".."}:
            raise RagError("CONFIG_INVALID", "Invalid upload filename")
        target = Path(meta["managed_root"]) / f"{db.uid()}-{filename}"
        maximum = engine.config.defaults.max_file_size_mb * 1024 * 1024
        size = 0
        try:
            with target.open("xb") as stream:
                while data := await file.read(1024 * 1024):
                    size += len(data)
                    if size > maximum:
                        raise RagError("FILE_TOO_LARGE", "Upload exceeds max_file_size_mb")
                    stream.write(data)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        result = await engine.add_file(name, str(target), origin="upload")
        return {**result, "path": str(target)}

    @app.get("/api/collections/{name}/keywords")
    async def keywords(name: str, query: str | None = None, limit: int = 50, offset: int = 0):
        return engine.list_keywords(name, query, limit, offset)

    @app.get("/api/collections/{name}/metadata_fields")
    async def fields(name: str):
        return {"fields": engine.list_metadata_fields(name)}

    @app.post("/api/collections/{name}/rebuild")
    async def rebuild(name: str, body: ConfirmBody):
        return engine.rebuild_collection(name, body.confirm)

    @app.post("/api/collections/{name}/vacuum")
    async def vacuum(name: str):
        return engine.vacuum_collection(name)

    @app.get("/api/collections/{name}/manifest")
    async def manifest(name: str):
        return engine.export_collection_manifest(name)

    @app.post("/api/search")
    async def single_search(body: SearchRequest):
        return await engine.search(body)

    @app.get("/api/corpus")
    async def corpus_catalog():
        return corpus.describe(engine, admin=True)

    @app.post("/api/corpus/query")
    async def corpus_search(body: corpus.CorpusQuery):
        return await corpus.query(engine, body, admin=True)

    @app.post("/api/search/multi")
    async def multi_search(body: MultiSearchRequest):
        return await engine.search_multi(body)

    @app.post("/api/knowledge-cards/search")
    async def knowledge_card_search(body: KnowledgeCardSearchRequest):
        from .knowledge_cards import dump_cards

        results = await engine.search_knowledge_cards(body)
        return {
            "results": [{**match, "yaml": dump_cards([match["card"]])} for match in results],
            "yaml": dump_cards([match["card"] for match in results]),
        }

    @app.get("/collections/{name}/jobs/{job_id}/events")
    async def job_events(name: str, job_id: str, request: HTTPRequest):
        engine.get_job(name, job_id)

        async def stream():
            while not await request.is_disconnected():
                item = engine.get_job(name, job_id)
                yield f"event: progress\ndata: {json.dumps(item)}\n\n"
                if item["status"] not in {"running", "queued"}:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/static/{asset}")
    async def static(asset: str):
        if asset not in {"app.js", "style.css"}:
            return Response(status_code=404)
        return Response(
            files(__package__).joinpath("static", asset).read_text(encoding="utf-8"),
            media_type="text/javascript" if asset.endswith(".js") else "text/css",
        )

    async def ui():
        return HTMLResponse(files(__package__).joinpath("static", "index.html").read_text(encoding="utf-8"))

    for path in (
        "/",
        "/collections",
        "/collections/{name}",
        "/collections/{name}/upload",
        "/collections/{name}/sources",
        "/collections/{name}/jobs/{job_id}",
        "/collections/{name}/search",
        "/search-multi",
    ):
        app.add_api_route(path, ui, methods=["GET"], include_in_schema=False)
    # Both exact transport routes share the parent's auth middleware and lifespan.
    app.router.routes.extend(mcp_app.routes)
    if admin_app:
        app.router.routes.extend(admin_app.routes)
    return app
