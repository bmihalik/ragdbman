# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import base64

import httpx
import pytest
import yaml
from conftest import finish
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_knowledge_cards import card

from ragdbman import corpus
from ragdbman.engine import Engine
from ragdbman.errors import RagError
from ragdbman.operations import OPERATIONS, invoke, validate
from ragdbman.web import create_app

ADMIN = "admin-secret-for-testing"
QUERY = "query-secret-for-testing"


def rpc(client, name, arguments=None, profile="query", token=QUERY, method="tools/call"):
    return client.post(
        "/mcp/" + profile,
        headers={"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + token},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {"name": name, "arguments": arguments or {}} if method == "tools/call" else {},
        },
    )


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)


def test_wire_profiles_and_no_admin_bypass(cfg, fake, source_dir, secrets):
    cfg.server.mcp_admin_enabled = True
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:
        query_tools = rpc(client, "", method="tools/list").json()["result"]["tools"]
        assert {t["name"] for t in query_tools} == {"corpus_describe", "corpus_query", "corpus_graph"}
        admin_tools = rpc(client, "", profile="admin", token=ADMIN, method="tools/list").json()["result"][
            "tools"
        ]
        assert {t["name"] for t in admin_tools} == set(OPERATIONS)
        for name in ("corpus_manage", "corpus_ingest", "corpus_job", "collection_create"):
            rejected = rpc(client, name, {"request": {"action": "create", "name": "forbidden"}})
            assert rejected.json()["result"]["isError"]
        assert rpc(client, "corpus_describe", profile="admin").status_code == 401
        for token in (QUERY, ""):
            headers = {"Authorization": "Bearer " + token} if token else {}
            for path in ("/api/collections", "/api/collections/forbidden/rebuild", "/api/corpus/query"):
                assert client.post(path, headers=headers, json={}).status_code == 401
            assert client.get("/", headers=headers).status_code == 401
        created = rpc(client, "collection_create", {"name": "ok"}, profile="admin", token=ADMIN)
        assert not created.json()["result"].get("isError"), created.text
        assert client.post("/api/collections-list", json={}, auth=("admin", ADMIN)).status_code == 200
        assert client.get("/", auth=("admin", ADMIN)).status_code == 200
        assert client.post("/mcp", headers={"Authorization": "Bearer " + ADMIN}, json={}).status_code == 404
        assert engine.collection_get("ok")
        query = rpc(client, "corpus_query", {"query": "anything", "collections": ["ok"], "mode": "keyword"})
        answer = query.json()["result"]
        assert "structuredContent" not in answer
        assert "No results met" in answer["content"][0]["text"]
        scan = rpc(
            client, "scan_start", {"collection": "ok", "root": str(source_dir)}, profile="admin", token=ADMIN
        )
        assert not scan.json()["result"].get("isError"), scan.text
        job_id = scan.json()["result"]["structuredContent"]["id"]
        inspected = rpc(
            client, "scan_job_get", {"collection": "ok", "job_id": job_id}, profile="admin", token=ADMIN
        )
        assert not inspected.json()["result"].get("isError"), inspected.text


def test_admin_hidden_but_web_still_works(cfg, fake, source_dir, secrets):
    with TestClient(create_app(Engine(cfg, fake))) as client:
        assert rpc(client, "", profile="admin", token=ADMIN, method="tools/list").status_code == 404
        assert rpc(client, "", method="tools/list").status_code == 200
        assert (
            client.post("/api/collection-create", json={**{"name": "web"}}, auth=("admin", ADMIN)).status_code
            == 200
        )


def test_mcp_requires_token_even_in_local_mode(cfg, fake, source_dir, monkeypatch):
    with TestClient(create_app(Engine(cfg, fake))) as client:
        assert rpc(client, "", token="", method="tools/list").status_code == 401
        assert client.get("/").status_code == 200
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    with TestClient(create_app(Engine(cfg, fake))) as client:
        assert client.get("/").status_code == 401
        assert client.get("/", auth=("admin", ADMIN)).status_code == 200
        assert rpc(client, "", token=ADMIN, method="tools/list").status_code == 200


@pytest.mark.parametrize("same", [False, True])
def test_unsafe_token_configuration_rejected(engine, monkeypatch, same):
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)
    if same:
        monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", QUERY)
    else:
        monkeypatch.delenv("RAGDBMAN_AUTH_TOKEN", raising=False)
    with pytest.raises(RagError):
        create_app(engine, False)


@pytest.fixture
async def mixed(engine, source_dir):
    for name, kind in (("docs", "general"), ("code", "source_code"), ("cards", "knowledge_cards")):
        await engine.collection_create(name=name, kind=kind)
    text = source_dir / "queue.txt"
    text.write_text("A queue for graph traversal. Price: EUR 25.")
    await engine.collection_add_file("docs", str(text))
    await engine.collection_add_file("code", str(text))
    path = source_dir / "card.yaml"
    data = card()
    data["codes"] = ["def queue():\n    return '``` nested fence'\n"]
    path.write_text(yaml.safe_dump(data))
    await engine.collection_add_file("cards", str(path))
    return engine


async def test_catalog_scope_defaults_and_private_paths(mixed):
    mixed.config.server.mcp_allowed_collections = ["cards", "docs"]
    mixed.config.server.mcp_default_collections = ["cards"]
    result = corpus.corpus_describe(mixed)
    assert [c["name"] for c in result["collections"]] == ["cards", "docs"]
    assert "database_path" not in str(result)
    assert "managed_root" not in str(result)
    assert "source_roots" not in str(result)
    details = corpus.corpus_describe(mixed, ["cards"])["collections"][0]
    assert "codes" in details["fields"]
    response = await corpus.corpus_query(mixed, corpus.CorpusQuery(query="queue", mode="keyword"))
    assert response["collections_searched"] == ["cards"]
    with pytest.raises(RagError, match="scope"):
        await corpus.corpus_query(mixed, corpus.CorpusQuery(query="queue", collections=["code"]))
    with pytest.raises(RagError, match="scope"):
        corpus.corpus_describe(mixed, ["code"])
    assert len(corpus.corpus_describe(mixed, admin=True)["collections"]) == 3


async def test_explicit_scope_required(engine):
    with pytest.raises(RagError, match="Specify collections"):
        await corpus.corpus_query(engine, corpus.CorpusQuery(query="something"))


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
@pytest.mark.parametrize("perspective", ["general", "expert"])
async def test_unified_query_mixed_kinds(mixed, mode, perspective):
    response = await corpus.corpus_query(
        mixed,
        corpus.CorpusQuery(
            query="queue graph",
            collections=["cards", "code", "docs"],
            mode=mode,
            perspective=perspective,
            limit=3,
            minimum_score=0,
        ),
    )
    assert set(response["collections_searched"]) == {"cards", "code", "docs"}
    assert len(response["results"]) == 3
    assert {r["kind"] for r in response["results"]} == {"knowledge_card", "source_code", "document"}
    assert [r["rank"] for r in response["results"]] == [1, 2, 3]
    card_result = next((r for r in response["results"] if r["kind"] == "knowledge_card"))
    assert "id" not in card_result["content"]
    rendered = corpus.render(response)
    assert "Knowledge Card" in rendered and "````yaml" in rendered
    assert "    return '``` nested fence'" in rendered
    if perspective == "expert":
        assert len(response["warnings"]) == 2


async def test_bad_filters_are_reported_not_ignored(mixed):
    request = corpus.CorpusQuery(
        query="queue",
        collections=["docs", "cards"],
        mode="keyword",
        filters={"numeric": [{"field": "missing_field", "op": "exists"}]},
    )
    response = await corpus.corpus_query(mixed, request)
    assert response["collections_searched"] == []
    assert len(response["warnings"]) == 2
    assert not response["results"]


async def test_partial_failures_threshold_and_fallback(mixed, fake):
    fake.failure = True
    response = await corpus.corpus_query(
        mixed, corpus.CorpusQuery(query="queue", collections=["cards", "docs", "absent"], minimum_score=0)
    )
    assert response["collections_searched"] == ["cards"]
    assert {w["code"] for w in response["warnings"]} == {
        "KEYWORD_FALLBACK",
        "OLLAMA_UNAVAILABLE",
        "COLLECTION_NOT_FOUND",
    }
    response = await corpus.corpus_query(
        mixed, corpus.CorpusQuery(query="queue", collections=["docs"], mode="keyword", minimum_score=1)
    )
    assert response["results"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "create", "name": "bad", "confirm": True},
        {"action": "delete", "collection": "bad", "path": "/tmp"},
        {"action": "execute", "collection": "bad"},
    ],
)
def test_action_specific_management_validation(payload):
    with pytest.raises(ValidationError):
        validate("collection_create", payload)


async def test_management_ingestion_and_jobs(engine, source_dir):
    await invoke(engine, "collection_create", {"name": "cards", "kind": "knowledge_cards"})
    await invoke(engine, "collection_config_update", {"description": "Curated", "name": "cards"})
    assert (await invoke(engine, "collection_get", {"name": "cards"}))["description"] == "Curated"
    root = await invoke(engine, "collection_add_root", {"collection": "cards", "path": str(source_dir)})
    with pytest.raises(RagError):
        await invoke(engine, "collection_remove_root", {"collection": "cards", "root_id": root["root_id"]})
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    scan = await invoke(engine, "scan_start", {"collection": "cards", "root": str(source_dir)})
    assert (await finish(engine, "cards", scan))["status"] == "completed"
    job = await invoke(engine, "scan_job_get", {"collection": "cards", "job_id": scan["id"]})
    assert job["status"] == "completed"
    assert await invoke(engine, "scan_jobs_list", {"collection": "cards"})
    with pytest.raises(RagError):
        await invoke(engine, "collection_rebuild", {"collection": "cards"})
    rebuild = await invoke(engine, "collection_rebuild", {"collection": "cards", "confirm": True})
    await finish(engine, "cards", rebuild)
    encoded = base64.b64encode(yaml.safe_dump(card("uploaded")).encode()).decode()
    upload = await invoke(
        engine,
        "collection_upload_file",
        {"collection": "cards", "filename": "card.yaml", "content_base64": encoded},
    )
    await invoke(
        engine,
        "collection_remove_file",
        {"collection": "cards", "source_id": upload["source_id"], "confirm": True},
    )
    await invoke(engine, "collection_vacuum", {"collection": "cards"})
    await invoke(engine, "collection_export_manifest", {"collection": "cards"})
    with pytest.raises(RagError):
        await invoke(engine, "collection_delete", {"name": "cards"})
    await invoke(engine, "collection_delete", {"confirm": True, "name": "cards"})


async def test_rest_corpus_contract(mixed):
    app = create_app(mixed, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.post("/api/corpus-describe", json={})).status_code == 200
        response = await c.post(
            "/api/corpus-query", json={**{"query": "queue", "collections": ["cards"], "mode": "keyword"}}
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["kind"] == "knowledge_card"
        assert (
            await c.post("/api/corpus-query", json={**{"query": " ", "collections": ["cards"]}})
        ).status_code == 422


@pytest.mark.parametrize(
    "filename,content",
    [
        ("../escape.yaml", "aGVsbG8="),
        ("bad\\name", "aGVsbG8="),
        ("card.yaml", "not base64!"),
        (".", "aGVsbG8="),
    ],
)
async def test_upload_validation(engine, filename, content):
    await engine.collection_create(name="upload", kind="knowledge_cards")
    with pytest.raises(RagError):
        await invoke(
            engine,
            "collection_upload_file",
            {"collection": "upload", "filename": filename, "content_base64": content},
        )
    assert engine.collection_get("upload")["counts"]["sources"] == 0


async def test_remaining_admin_actions_and_cancel_resume(engine, fake, source_dir):
    import asyncio

    await engine.collection_create(name="cards", kind="knowledge_cards")
    path = source_dir / "file.yaml"
    path.write_text(yaml.safe_dump(card()))
    source = await invoke(engine, "collection_add_file", {"collection": "cards", "path": str(path)})
    assert (
        await invoke(engine, "collection_get_file", {"collection": "cards", "source_id": source["source_id"]})
    )["id"] == source["source_id"]
    assert await invoke(engine, "collection_list_files", {"collection": "cards"})
    assert (await invoke(engine, "health_status", {}))["daemon_ok"]
    root = engine.collection_add_root("cards", str(source_dir))
    await invoke(
        engine, "collection_remove_root", {"collection": "cards", "root_id": root["root_id"], "confirm": True}
    )
    with pytest.raises(RagError):
        await invoke(
            engine, "scan_start", {"collection": "cards", "root": str(source_dir), "prune_missing": True}
        )
    path.write_text(yaml.safe_dump(card("changed")))
    fake.entered.clear()
    fake.gate = asyncio.Event()
    scan = engine.scan_start("cards", str(source_dir))
    await asyncio.wait_for(fake.entered.wait(), 3)
    await invoke(engine, "scan_job_cancel", {"job_id": scan["id"]})
    fake.gate.set()
    assert (await finish(engine, "cards", scan))["status"] == "cancelled"
    resumed = await invoke(engine, "scan_job_resume", {"collection": "cards", "job_id": scan["id"]})
    assert (await finish(engine, "cards", resumed))["status"] == "completed"


def test_render_preserves_trailing_code_newlines():
    data = card()
    data.pop("id")
    data["codes"] = ["hello\n\n\n"]
    code = data.pop("codes")
    data["codes"] = code
    response = dict(
        results=[
            dict(rank=1, kind="knowledge_card", title="Card", collection="cards", provenance={}, content=data)
        ],
        warnings=[],
    )
    rendered = corpus.render(response)
    raw = rendered.split("```yaml\n", 1)[1].rsplit("```", 1)[0]
    assert yaml.safe_load(raw)["codes"] == ["hello\n\n\n"]


@pytest.mark.parametrize(
    "values",
    [
        {"query": " "},
        {"query": "x", "collections": []},
        {"query": "x", "limit": 0},
        {"query": "x", "minimum_score": float("nan")},
        {"query": "x", "mode": "expert"},
    ],
)
def test_query_contract_validation(values):
    with pytest.raises(ValidationError):
        corpus.CorpusQuery(**values)


@pytest.mark.parametrize("path", ["/", "/api", "/mcp/", "/mcp/../api", "/mcp%2fadmin", "/mcp?x", "/static"])
def test_reserved_mcp_paths_rejected(path):
    from ragdbman.config import GlobalConfig

    with pytest.raises(ValidationError):
        GlobalConfig(server={"mcp_path": path})


def test_default_scope_must_be_allowed():
    from ragdbman.config import GlobalConfig

    with pytest.raises(ValidationError):
        GlobalConfig(server={"mcp_allowed_collections": ["one"], "mcp_default_collections": ["two"]})
