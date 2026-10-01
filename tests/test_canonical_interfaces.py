# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import inspect

import pytest
from fastapi.testclient import TestClient
from test_corpus import ADMIN, QUERY, rpc

from ragdbman.cli import parser
from ragdbman.cli_commands import COMMANDS, contract
from ragdbman.engine import Engine
from ragdbman.operations import OPERATIONS, QUERY_OPERATIONS, invoke
from ragdbman.web import create_app


def test_catalog_names_and_removed_aliases():
    assert {v.replace("-", "_") for v in COMMANDS} == set(OPERATIONS)
    for name in OPERATIONS:
        assert callable(getattr(Engine, name))
    for name in (
        "search",
        "search_multi",
        "search_knowledge_cards",
        "graph",
        "get_collection",
        "create_collection",
        "start_scan",
        "list_sources",
        "repair_registry",
    ):
        assert not hasattr(Engine, name)
    for name in (
        "search",
        "search-multi",
        "search-knowledge-cards",
        "graph",
        "list-collections",
        "registry-repair",
        "get-job",
        "corpus-manage",
    ):
        with pytest.raises(SystemExit):
            parser().parse_args([name])


def test_wire_catalog_schema_and_removed_routes(cfg, fake, source_dir, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)
    cfg.server.mcp_admin_enabled = True
    with TestClient(create_app(Engine(cfg, fake))) as client:
        tools = rpc(client, "", profile="admin", token=ADMIN, method="tools/list").json()["result"]["tools"]
        assert {t["name"] for t in tools} == set(OPERATIONS)
        schema = client.get("/openapi.json", auth=("admin", ADMIN)).json()
        paths = {p for p in schema["paths"] if p.startswith("/api/")}
        assert paths == {"/api/" + name.replace("_", "-") for name in OPERATIONS}
        for tool in tools:
            name = tool["name"]
            assert set(tool["inputSchema"]["properties"]) == set(OPERATIONS[name].model.model_fields)
            assert all(
                type(tool["annotations"][key]) is bool
                for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
            )
            assert schema["paths"]["/api/" + name.replace("_", "-")]["post"]["operationId"] == name
            if name in {"corpus_query", "corpus_graph"}:
                assert tool["inputSchema"]["properties"]["format"]["default"] == "llm"
            if name not in QUERY_OPERATIONS:
                denied = rpc(client, name, {})
                assert denied.json()["result"]["isError"]
        for old in (
            "/api/search",
            "/api/search/multi",
            "/api/knowledge-cards/search",
            "/api/collections",
            "/api/corpus/query",
            "/api/corpus/graph",
        ):
            assert client.post(old, json={}, auth=("admin", ADMIN)).status_code == 404
        for old in ("corpus_manage", "corpus_ingest", "corpus_job"):
            assert rpc(client, old, {}, profile="admin", token=ADMIN).json()["result"]["isError"]
        # The graph contract, like every tool, is flat, not a nested request envelope.
        rejected = rpc(client, "corpus_graph", {"request": {"collection": "code", "action": "find"}})
        assert rejected.json()["result"]["isError"]
        unknown = rpc(client, "corpus_describe", {"unused": True})
        assert unknown.json()["result"]["isError"]
        assert (
            client.post("/api/corpus-describe", json={"unused": True}, auth=("admin", ADMIN)).status_code
            == 422
        )


def test_python_cli_rest_mcp_query_and_graph_parity(cfg, fake, source_dir, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)
    cfg.server.mcp_admin_enabled = True
    cfg.server.mcp_allowed_collections = ["code", "cards"]
    source = source_dir / "a.py"
    source.write_text("def helper():\n    return 1\n\ndef caller():\n    return helper()\n")
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:

        def rest(name, args):
            r = client.post("/api/" + name.replace("_", "-"), json=args, auth=("admin", ADMIN))
            assert r.status_code == 200, r.text
            return r.json()

        rest("collection_create", {"name": "code", "kind": "source_code"})
        added = rest("collection_add_file", {"collection": "code", "path": str(source)})
        assert (
            rest("collection_get_file", {"collection": "code", "source_id": added["source_id"]})["status"]
            == "indexed"
        )
        args = parser().parse_args(
            ["corpus-query", "--collections", "code", "--query", "helper", "--mode", "keyword"]
        )
        op, body = contract(args)
        direct = client.portal.call(invoke, engine, op, body)
        assert rest(op, body) == direct
        assert rpc(client, op, body).json()["result"]["structuredContent"] == direct
        assert client.portal.call(engine.corpus_query, body) == direct
        graph = {"collection": "code", "symbol": "helper", "action": "callers", "format": "raw"}
        assert (
            rest("corpus_graph", graph)
            == rpc(client, "corpus_graph", graph).json()["result"]["structuredContent"]
        )
        # Structured retrieval is part of the same contract, without embedding calls.
        before = len(fake.calls)
        result = rest("corpus_query", {"collections": ["code"], "query": "", "mode": "structured"})
        assert result["results"] and len(fake.calls) == before
        assert result["results"][0]["relevance"]["policy"] == "constant_match"
        assert (
            rest("corpus_describe", {})
            == rpc(client, "corpus_describe", {}).json()["result"]["structuredContent"]
        )
        # Confirmation rules are the same on direct, CLI, REST and MCP paths.
        assert (
            client.post(
                "/api/scan-start",
                json={"collection": "code", "root": str(source_dir), "prune_missing": True},
                auth=("admin", ADMIN),
            ).status_code
            == 400
        )
        assert rpc(client, "collection_delete", {"name": "code"}, profile="admin", token=ADMIN).json()[
            "result"
        ]["isError"]
        with pytest.raises(Exception, match="CONFIRMATION_REQUIRED"):
            engine.scan_start("code", str(source_dir), prune_missing=True)


async def test_query_only_dispatch_cannot_invoke_admin(engine):
    with pytest.raises(Exception, match="PATH_NOT_ALLOWED"):
        await invoke(engine, "collections_list", {}, admin=False)


def test_registered_request_fields_match_python_signatures():
    for name, spec in OPERATIONS.items():
        sig = inspect.signature(getattr(Engine, name))
        if name in {"collection_create", "corpus_query", "corpus_graph"}:
            continue  # Model-or-keyword entry points.
        sig.bind(None, **{field: None for field in spec.model.model_fields})
