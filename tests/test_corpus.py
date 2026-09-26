# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import base64

import httpx
import pytest
import yaml
from conftest import finish
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from test_knowledge_cards import card

from ragdbman import corpus, corpus_admin
from ragdbman.engine import Engine
from ragdbman.errors import RagError
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
        assert {t["name"] for t in query_tools} == {"corpus_describe", "corpus_query"}
        admin_tools = rpc(client, "", profile="admin", token=ADMIN, method="tools/list").json()["result"][
            "tools"
        ]
        assert {t["name"] for t in admin_tools} == {
            "corpus_describe",
            "corpus_query",
            "corpus_manage",
            "corpus_ingest",
            "corpus_job",
        }
        for name in ("corpus_manage", "corpus_ingest", "corpus_job", "create_collection"):
            rejected = rpc(client, name, {"request": {"action": "create", "name": "forbidden"}})
            assert rejected.json()["result"]["isError"]
        assert rpc(client, "corpus_describe", profile="admin").status_code == 401
        for token in (QUERY, ""):
            headers = {"Authorization": "Bearer " + token} if token else {}
            for path in ("/api/collections", "/api/collections/forbidden/rebuild", "/api/corpus/query"):
                assert client.post(path, headers=headers, json={}).status_code == 401
            assert client.get("/", headers=headers).status_code == 401
        created = rpc(
            client,
            "corpus_manage",
            {"request": {"action": "create", "name": "ok"}},
            profile="admin",
            token=ADMIN,
        )
        assert not created.json()["result"].get("isError"), created.text
        assert client.get("/api/collections", auth=("admin", ADMIN)).status_code == 200
        assert client.get("/", auth=("admin", ADMIN)).status_code == 200
        assert client.post("/mcp", headers={"Authorization": "Bearer " + ADMIN}, json={}).status_code == 404
        assert engine.get_collection("ok")
        query = rpc(client, "corpus_query", {"query": "anything", "collections": ["ok"], "mode": "keyword"})
        answer = query.json()["result"]
        assert answer["structuredContent"]["results"] == []
        assert "No results met" in answer["content"][0]["text"]
        scan = rpc(
            client,
            "corpus_ingest",
            {
                "request": {
                    "action": "scan",
                    "collection": "ok",
                    "root": str(source_dir),
                }
            },
            profile="admin",
            token=ADMIN,
        )
        assert not scan.json()["result"].get("isError"), scan.text
        job_id = scan.json()["result"]["structuredContent"]["result"]["id"]
        inspected = rpc(
            client,
            "corpus_job",
            {
                "request": {
                    "action": "inspect",
                    "collection": "ok",
                    "job_id": job_id,
                }
            },
            profile="admin",
            token=ADMIN,
        )
        assert not inspected.json()["result"].get("isError"), inspected.text


def test_admin_hidden_but_web_still_works(cfg, fake, source_dir, secrets):
    with TestClient(create_app(Engine(cfg, fake))) as client:
        assert rpc(client, "", profile="admin", token=ADMIN, method="tools/list").status_code == 404
        assert rpc(client, "", method="tools/list").status_code == 200
        assert client.post("/api/collections", auth=("admin", ADMIN), json={"name": "web"}).status_code == 200


def test_mcp_requires_token_even_in_local_mode(cfg, fake, source_dir, monkeypatch):
    with TestClient(create_app(Engine(cfg, fake))) as client:
        assert rpc(client, "", token="", method="tools/list").status_code == 401
        assert client.get("/").status_code == 200  # Standalone loopback UI, no MCP credentials configured.
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
        await engine.create_collection(name=name, kind=kind)
    text = source_dir / "queue.txt"
    text.write_text("A queue for graph traversal. Price: EUR 25.")
    await engine.add_file("docs", str(text))
    await engine.add_file("code", str(text))
    path = source_dir / "card.yaml"
    data = card()
    data["codes"] = ["def queue():\n    return '``` nested fence'\n"]
    path.write_text(yaml.safe_dump(data))
    await engine.add_file("cards", str(path))
    return engine


async def test_catalog_scope_defaults_and_private_paths(mixed):
    mixed.config.server.mcp_allowed_collections = ["cards", "docs"]
    mixed.config.server.mcp_default_collections = ["cards"]
    result = corpus.describe(mixed)
    assert [c["name"] for c in result["collections"]] == ["cards", "docs"]
    assert "database_path" not in str(result)
    assert "managed_root" not in str(result)
    assert "source_roots" not in str(result)
    details = corpus.describe(mixed, ["cards"])["collections"][0]
    assert "codes" in details["fields"]
    response = await corpus.query(mixed, corpus.CorpusQuery(query="queue", mode="keyword"))
    assert response["collections_searched"] == ["cards"]
    with pytest.raises(RagError, match="scope"):
        await corpus.query(mixed, corpus.CorpusQuery(query="queue", collections=["code"]))
    with pytest.raises(RagError, match="scope"):
        corpus.describe(mixed, ["code"])
    assert len(corpus.describe(mixed, admin=True)["collections"]) == 3


async def test_explicit_scope_required(engine):
    with pytest.raises(RagError, match="Specify collections"):
        await corpus.query(engine, corpus.CorpusQuery(query="something"))


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
@pytest.mark.parametrize("perspective", ["general", "expert"])
async def test_unified_query_mixed_kinds(mixed, mode, perspective):
    response = await corpus.query(
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
    card_result = next(r for r in response["results"] if r["kind"] == "knowledge_card")
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
    response = await corpus.query(mixed, request)
    assert response["collections_searched"] == []
    assert len(response["warnings"]) == 2
    assert not response["results"]


async def test_partial_failures_threshold_and_fallback(mixed, fake):
    fake.failure = True
    response = await corpus.query(
        mixed,
        corpus.CorpusQuery(
            query="queue",
            collections=["cards", "docs", "absent"],
            minimum_score=0,
        ),
    )
    assert response["collections_searched"] == ["cards"]
    assert {w["code"] for w in response["warnings"]} == {
        "KEYWORD_FALLBACK",
        "OLLAMA_UNAVAILABLE",
        "COLLECTION_NOT_FOUND",
    }
    response = await corpus.query(
        mixed,
        corpus.CorpusQuery(
            query="queue",
            collections=["docs"],
            mode="keyword",
            minimum_score=1,
        ),
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
        TypeAdapter(corpus_admin.Manage).validate_python(payload)


async def test_management_ingestion_and_jobs(engine, source_dir):
    async def manage(data):
        return await corpus_admin.manage(engine, TypeAdapter(corpus_admin.Manage).validate_python(data))

    async def ingest(data):
        return await corpus_admin.ingest(engine, TypeAdapter(corpus_admin.Ingest).validate_python(data))

    await manage({"action": "create", "name": "cards", "kind": "knowledge_cards"})
    await manage({"action": "update", "collection": "cards", "description": "Curated"})
    assert (await manage({"action": "inspect", "collection": "cards"}))["description"] == "Curated"
    root = await manage({"action": "register_root", "collection": "cards", "path": str(source_dir)})
    with pytest.raises(RagError):
        await manage({"action": "unregister_root", "collection": "cards", "root_id": root["root_id"]})
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    scan = await ingest({"action": "scan", "collection": "cards", "root": str(source_dir)})
    assert (await finish(engine, "cards", scan))["status"] == "completed"
    job = corpus_admin.jobs(engine, corpus_admin.Job(action="inspect", collection="cards", job_id=scan["id"]))
    assert job["status"] == "completed"
    assert corpus_admin.jobs(engine, corpus_admin.ListJobs(action="list", collection="cards"))
    with pytest.raises(RagError):
        await ingest({"action": "rebuild", "collection": "cards"})
    rebuild = await ingest({"action": "rebuild", "collection": "cards", "confirm": True})
    await finish(engine, "cards", rebuild)
    encoded = base64.b64encode(yaml.safe_dump(card("uploaded")).encode()).decode()
    upload = await ingest(
        {"action": "upload", "collection": "cards", "filename": "card.yaml", "content_base64": encoded}
    )
    await ingest(
        {"action": "remove_source", "collection": "cards", "source_id": upload["source_id"], "confirm": True}
    )
    await manage({"action": "vacuum", "collection": "cards"})
    await manage({"action": "manifest", "collection": "cards"})
    with pytest.raises(RagError):
        await manage({"action": "delete", "collection": "cards"})
    await manage({"action": "delete", "collection": "cards", "confirm": True})


async def test_rest_corpus_contract(mixed):
    app = create_app(mixed, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        assert (await c.get("/api/corpus")).status_code == 200
        response = await c.post(
            "/api/corpus/query", json={"query": "queue", "collections": ["cards"], "mode": "keyword"}
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["kind"] == "knowledge_card"
        assert (
            await c.post("/api/corpus/query", json={"query": " ", "collections": ["cards"]})
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
    await engine.create_collection(name="upload", kind="knowledge_cards")
    with pytest.raises(RagError):
        await corpus_admin.ingest(
            engine,
            corpus_admin.Upload(
                action="upload",
                collection="upload",
                filename=filename,
                content_base64=content,
            ),
        )
    assert engine.get_collection("upload")["counts"]["sources"] == 0


async def test_remaining_admin_actions_and_cancel_resume(engine, fake, source_dir):
    import asyncio

    await engine.create_collection(name="cards", kind="knowledge_cards")
    path = source_dir / "file.yaml"
    path.write_text(yaml.safe_dump(card()))
    source = await corpus_admin.ingest(
        engine, corpus_admin.AddFile(action="add_file", collection="cards", path=str(path))
    )
    assert (
        await corpus_admin.manage(
            engine, corpus_admin.Source(action="source", collection="cards", source_id=source["source_id"])
        )
    )["id"] == source["source_id"]
    assert await corpus_admin.manage(engine, corpus_admin.Sources(action="sources", collection="cards"))
    assert (await corpus_admin.manage(engine, corpus_admin.Health(action="health")))["daemon_ok"]
    root = engine.add_source_root("cards", str(source_dir))
    await corpus_admin.manage(
        engine,
        corpus_admin.UnregisterRoot(
            action="unregister_root", collection="cards", root_id=root["root_id"], confirm=True
        ),
    )
    with pytest.raises(RagError):
        await corpus_admin.ingest(
            engine,
            corpus_admin.Scan(action="scan", collection="cards", root=str(source_dir), prune_missing=True),
        )
    path.write_text(yaml.safe_dump(card("changed")))
    fake.entered.clear()
    fake.gate = asyncio.Event()
    scan = engine.start_scan("cards", str(source_dir))
    await asyncio.wait_for(fake.entered.wait(), 3)
    corpus_admin.jobs(engine, corpus_admin.Job(action="cancel", collection="cards", job_id=scan["id"]))
    fake.gate.set()
    assert (await finish(engine, "cards", scan))["status"] == "cancelled"
    resumed = corpus_admin.jobs(
        engine, corpus_admin.Job(action="resume", collection="cards", job_id=scan["id"])
    )
    assert (await finish(engine, "cards", resumed))["status"] == "completed"


def test_render_preserves_trailing_code_newlines():
    data = card()
    data.pop("id")
    data["codes"] = ["hello\n\n\n"]
    # Put codes last to exercise YAML's keep-chomping indicator at document end.
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
