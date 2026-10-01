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
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.resources import files
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi import Request as HTTPRequest
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse

from . import __version__
from .engine import Engine
from .errors import RagError
from .mcp_server import create_mcp
from .operations import OPERATIONS, invoke


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
        operation_name = scope["path"].removeprefix("/api/").replace("-", "_")
        readonly_operation = operation_name in OPERATIONS and OPERATIONS[operation_name].readonly
        if self.engine.shutting_down and scope["method"] not in {"GET", "HEAD"} and not readonly_operation:
            return await JSONResponse({"code": "SERVER_SHUTTING_DOWN", "message": "Daemon is stopping"}, 503)(
                scope, receive, send
            )
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
        if admin_route or path == "/api/collection-upload-file":
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

    def register_operation(name, spec):
        async def endpoint(body):
            result = await invoke(engine, name, body.model_dump(), admin=True)
            return PlainTextResponse(result) if isinstance(result, str) else result

        endpoint.__name__ = name
        endpoint.__annotations__ = {"body": spec.model}
        app.add_api_route(
            "/api/" + name.replace("_", "-"),
            endpoint,
            methods=["POST"],
            operation_id=name,
            name=name,
            description=spec.description,
        )

    for name, spec in OPERATIONS.items():
        register_operation(name, spec)

    @app.get("/collections/{name}/jobs/{job_id}/events")
    async def job_events(name: str, job_id: str, request: HTTPRequest):
        engine.scan_job_get(name, job_id)

        async def stream():
            while not engine.shutting_down and not await request.is_disconnected():
                item = engine.scan_job_get(name, job_id)
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
        "/collections/{name}/corpus-query",
        "/collections/{name}/corpus-graph",
        "/corpus-graph",
        "/corpus-query",
    ):
        app.add_api_route(path, ui, methods=["GET"], include_in_schema=False)
    # Both exact transport routes share the parent's auth middleware and lifespan.
    app.router.routes.extend(mcp_app.routes)
    if admin_app:
        app.router.routes.extend(admin_app.routes)
    return app
