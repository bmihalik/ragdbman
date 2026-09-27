# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ragdbman.config import OllamaConfig
from ragdbman.errors import RagError
from ragdbman.ollama import Ollama
from ragdbman.web import create_app


async def test_ollama_batch_keepalive_options():
    requests = []

    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0] for _ in data["input"]]})

    client = Ollama(
        OllamaConfig(embedding_batch_size=2, bge_m3_options={"num_thread": 4}), httpx.MockTransport(handler)
    )
    try:
        assert len(await client.embed(["a", "b", "c"], "bge-m3:567m", 2)) == 3
        assert len(requests) == 2
        assert requests[0]["keep_alive"] == "24h"
        assert requests[0]["options"] == {"num_thread": 4}
        assert requests[0]["truncate"] is False
        await client.embed(["a"], "different", 2)
        assert "options" not in requests[-1]
        assert await client.embed([], "different") == []
    finally:
        await client.close()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"embeddings": []},
        {"embeddings": [[1, 2], [3, 4]]},
        {"embeddings": [[]]},
        {"embeddings": [["bad"]]},
        {"embeddings": [[None]]},
        {"embeddings": [[True]]},
    ],
)
async def test_invalid_embeddings_never_become_zero_vectors(body):
    client = Ollama(OllamaConfig(), httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        with pytest.raises(RagError, match="EMBEDDING_FAILED"):
            await client.embed(["a"], "model")
    finally:
        await client.close()


async def test_nan_and_dimensions():
    client = Ollama(
        OllamaConfig(), httpx.MockTransport(lambda r: httpx.Response(200, text='{"embeddings":[[NaN,1.0]]}'))
    )
    with pytest.raises(RagError, match="EMBEDDING_FAILED"):
        await client.embed(["x"], "model")
    await client.close()
    client = Ollama(
        OllamaConfig(), httpx.MockTransport(lambda r: httpx.Response(200, json={"embeddings": [[1.0, 2.0]]}))
    )
    with pytest.raises(RagError, match="VECTOR_SCHEMA_MISMATCH"):
        await client.embed(["x"], "model", 4)
    await client.close()


async def test_ollama_http_failure_and_unreachable():
    client = Ollama(OllamaConfig(), httpx.MockTransport(lambda r: httpx.Response(500, text="failed")))
    with pytest.raises(RagError, match="EMBEDDING_FAILED"):
        await client.embed(["x"], "model")
    await client.close()

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    client = Ollama(OllamaConfig(), httpx.MockTransport(fail))
    with pytest.raises(RagError, match="OLLAMA_UNAVAILABLE"):
        await client.embed(["x"], "model")
    await client.close()


async def test_rest_full_roundtrip(engine, source_dir):
    p = source_dir / "a.md"
    p.write_text("# Retrieval\n\nprice $25")
    app = create_app(engine, manage_engine=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/health")).json()["daemon_ok"]
        meta = (await c.post("/api/collections", json={"name": "api", "kind": "source_code"})).json()
        assert meta["kind"] == "source_code"
        r = await c.post("/api/collections/api/add_file", json={"path": str(p)})
        assert r.status_code == 200
        source_id = r.json()["source_id"]
        search = await c.post(
            "/api/search", json={"collection": "api", "query": "retrieval", "mode": "keyword"}
        )
        assert search.json()["results"]
        assert (await c.get(f"/api/collections/api/sources/{source_id}")).json()["markdown_path"] is None
        assert (await c.get("/api/collections/api/metadata_fields")).json()["fields"]
        assert (await c.get("/api/collections/api/keywords")).json()
        assert (await c.get("/api/collections/api/manifest")).json()["sources"]
        assert (await c.patch("/api/collections/api", json={"description": "changed"})).json()[
            "description"
        ] == "changed"
        assert (await c.delete(f"/api/collections/api/sources/{source_id}")).status_code == 400
        assert (await c.delete(f"/api/collections/api/sources/{source_id}?confirm=true")).status_code == 200
        assert (await c.post("/api/collections/api/vacuum")).status_code == 200
        assert (await c.delete("/api/collections/api?confirm=true")).status_code == 200
        assert (await c.get("/api/collections/absent")).status_code == 404


async def test_upload_and_request_validation(engine):
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        await c.post("/api/collections", json={"name": "uploads"})
        r = await c.post(
            "/api/collections/uploads/upload",
            files={"file": ("../../test.txt", b"upload retrieval", "text/plain")},
        )
        assert r.status_code == 200, r.text
        source = engine.get_source("uploads", r.json()["source_id"])
        assert source["origin_type"] == "upload"
        assert ".." not in source["managed_relative_path"]
        bad = await c.post("/api/collections", json={"name": "../bad"})
        assert bad.status_code == 422
        bad = await c.post("/api/search", json={"collection": "uploads", "query": "x", "mode": "unknown"})
        assert bad.status_code == 422
        r = await c.post("/api/collections/uploads/add_file", json={"path": "/etc/passwd"})
        assert r.status_code == 403


async def test_host_origin_auth_and_body_limit(engine, monkeypatch):
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/collections", headers={"Host": "evil.example"})).status_code == 403
        assert (
            await c.get("/api/collections", headers={"Origin": "https://evil.example"})
        ).status_code == 403
        assert (await c.get("/api/collections", headers={"Origin": "null"})).status_code == 403
        assert (
            await c.post("/api/collections", content=b"{}", headers={"Content-Length": "9000000000"})
        ).status_code == 413
        engine.config.server.web_auth_mode = "password"
        monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "private-test-secret")
    # Credentials are snapshotted at app creation; changing them requires restart.
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/collections")).status_code == 401
        assert (
            await c.get("/api/collections", headers={"Authorization": "Bearer private-test-secret"})
        ).status_code == 200
        assert (await c.get("/api/collections", auth=("ragdbman", "private-test-secret"))).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/collections",
        "/collections/a",
        "/collections/a/upload",
        "/collections/a/sources",
        "/collections/a/jobs/123",
        "/collections/a/search",
        "/search-multi",
    ],
)
async def test_ui_routes(engine, path):
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        response = await c.get(path)
        assert response.status_code == 200
        assert "ragdbman" in response.text
        assert "/static/app.js" in response.text


async def test_mcp_tool_names_and_flat_search_schema(engine):
    mcp = create_app(engine, False).state.mcp
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"corpus_describe", "corpus_query", "corpus_graph"}
    schema = next(t.inputSchema for t in tools if t.name == "corpus_query")
    assert "collections" in schema["properties"] and "query" in schema["properties"]


def test_mcp_streamable_http_wire_protocol(cfg, fake, source_dir, monkeypatch):
    from ragdbman.engine import Engine

    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "admin-test-token")
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", "query-test-token")
    cfg.server.mcp_admin_enabled = True
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer admin-test-token",
        }
        init = client.post(
            "/mcp/admin",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "ragdbman"
        tools = client.post(
            "/mcp/admin",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert len(tools.json()["result"]["tools"]) == 6
        created = client.post(
            "/mcp/admin",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "corpus_manage",
                    "arguments": {"request": {"action": "create", "name": "mcp"}},
                },
            },
        )
        assert not created.json()["result"].get("isError", False), created.text
        listed = client.post(
            "/mcp/query",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "corpus_describe", "arguments": {}},
            },
        )
        assert "mcp" in listed.text
        rejected = client.post(
            "/mcp/admin",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "corpus_manage",
                    "arguments": {"request": {"action": "delete", "collection": "mcp"}},
                },
            },
        )
        assert rejected.json()["result"]["isError"] is True
