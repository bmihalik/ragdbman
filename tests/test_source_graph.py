# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from functools import partial

import pytest
from conftest import finish
from fastapi.testclient import TestClient
from test_corpus import ADMIN, QUERY, rpc

from ragdbman import corpus, db
from ragdbman.config import GraphConfig
from ragdbman.engine import Engine
from ragdbman.errors import RagError
from ragdbman.graph.parser import prepare
from ragdbman.graph.query import GraphRequest, enrich
from ragdbman.graph.store import has_outbox
from ragdbman.web import create_app

CASES = [
    (
        "a.py",
        "def helper():\n    return 1\nclass C:\n    def run(self):\n        return helper()\n",
        "C.run",
        "helper",
    ),
    (
        "a.rs",
        "fn helper() {} struct S {} trait T { fn run(&self); } impl T for S { fn run(&self) { helper(); } }",
        "S.run",
        "helper",
    ),
    (
        "a.c",
        "int helper(void) { return 1; } struct S { int x; }; int run(void) { return helper(); }",
        "run",
        "helper",
    ),
    (
        "a.cpp",
        "int helper() { return 1; } namespace N { class C { public: int run() { return helper(); } }; }",
        "N.C.run",
        "helper",
    ),
    ("a.js", "function helper() { return 1; } class C { run() { return helper(); } }", "C.run", "helper"),
    (
        "a.ts",
        "interface I { run(): number; } function helper(): number { return 1; } class C implements I { run(): number { return helper(); } }",
        "C.run",
        "helper",
    ),
    ("a.tsx", "function helper() { return <div/>; } function run() { return helper(); }", "run", "helper"),
    (
        "a.go",
        "package main\nfunc helper() int { return 1 }\ntype S struct { x int }\nfunc (s *S) run() int { return helper() }\n",
        "S.run",
        "helper",
    ),
    (
        "a.java",
        "class C { static int helper() { return 1; } int run() { return helper(); } }",
        "C.run",
        "helper",
    ),
    (
        "a.cs",
        "class C { static int helper() { return 1; } int run() { return helper(); } }",
        "C.run",
        "helper",
    ),
]


@pytest.mark.parametrize("filename,text,owner,target", CASES)
def test_grammar_observations(tmp_path, filename, text, owner, target):
    path = tmp_path / filename
    path.write_text(text)
    snapshot, document = prepare(
        path, "source", hashlib.sha256(path.read_bytes()).hexdigest(), [tmp_path], GraphConfig()
    )
    assert snapshot["status"] == "parsed", snapshot
    assert document.extractor_name == "source_code_ast"
    entities = {e["id"]: e for e in snapshot["entities"]}
    assert any(e["qualified_name"] == owner for e in entities.values())
    assert any(
        e["kind"] == "calls"
        and e["target_name"] == target
        and entities[e["from_id"]]["qualified_name"] == owner
        for e in snapshot["relationships"]
    )


async def indexed(engine, source_dir, files, name="code", kind="source_code"):
    await engine.create_collection(name=name, kind=kind, source_roots=[str(source_dir)])
    records = {}
    for filename, content in files.items():
        path = source_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        records[filename] = await engine.add_file(name, str(path))
    return records


async def test_cross_file_queries_enrichment_and_current_citations(engine, source_dir, fake):
    records = await indexed(
        engine,
        source_dir,
        {
            "lib.py": "def helper():\n    return 1\n",
            "main.py": "from lib import helper as load\ndef run():\n    return load()\n",
        },
    )
    store = engine.graph_store("code")
    assert store.path.is_file()
    assert store.status()["sources"] == 2
    result = await engine.graph(dict(collection="code", symbol="helper", action="callers"))
    assert result["status"] == "ok"
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["from_name"] == "run"
    assert result["relationships"][0]["resolution"] == "import_static"
    assert result["relationships"][0]["provenance"]["chunks"]
    assert str(source_dir) not in json.dumps(result)
    dependencies = await engine.graph(
        dict(collection="code", action="dependencies", source_id=records["main.py"]["source_id"])
    )
    assert any(e["target_entity_id"] for e in dependencies["relationships"])
    impact = await engine.graph(
        dict(collection="code", action="impact", source_id=records["lib.py"]["source_id"])
    )
    assert any(e["kind"] == "depends_on" for e in impact["relationships"])
    calls = len(fake.calls)
    response = await corpus.query(
        engine, corpus.CorpusQuery(query="run", collections=["code"], mode="keyword")
    )
    assert len(fake.calls) == calls
    assert response["results"][0]["graph_context"]["available"]
    assert "Static source graph context" in corpus.render(response)
    disabled = await engine.search(
        dict(collection="code", query="run", mode="keyword", include_graph_context=False)
    )
    assert "graph_context" not in disabled["results"][0]
    assert not list(source_dir.rglob(".ragdbman"))


async def test_reindex_stable_source_and_dynamic_chunk_provenance(engine, source_dir):
    records = await indexed(engine, source_dir, {"main.py": "def helper():\n    return 1\n"})
    old = await engine.graph(dict(collection="code", action="find", symbol="helper"))
    entity = old["candidates"][0]
    old_chunks = {c["chunk_id"] for c in entity["provenance"]["chunks"]}
    stale_hit = (await engine.search(dict(collection="code", query="helper", mode="keyword")))["results"][0]
    path = source_dir / "main.py"
    path.write_text("# changed\n\ndef helper():\n    return 2\n")
    new_source = await engine.add_file("code", str(path))
    assert new_source["source_id"] == records["main.py"]["source_id"]
    new = (await engine.graph(dict(collection="code", action="find", symbol="helper")))["candidates"][0]
    assert new["entity_id"] == entity["entity_id"]
    assert new["provenance"]["line_start"] == 3
    assert not old_chunks.intersection(c["chunk_id"] for c in new["provenance"]["chunks"])
    enrich(partial(engine.connection, "code"), engine.graph_store("code"), [stale_hit], 8)
    assert stale_hit["graph_context"]["status"] == "pending_or_stale"
    engine.remove_source("code", new_source["source_id"], confirm=True)
    assert not (await engine.graph(dict(collection="code", action="find")))["candidates"]
    assert engine.graph_store("code").status()["sources"] == 0


async def test_outbox_failure_replay_and_stale_revision_gate(engine, source_dir, monkeypatch):
    await indexed(engine, source_dir, {"main.py": "def old():\n    return 1\n"})
    store = engine.graph_store("code")
    original = store.apply

    def fail(event):
        raise OSError("simulated graph outage")

    monkeypatch.setattr(store, "apply", fail)
    path = source_dir / "main.py"
    path.write_text("def new():\n    return 2\n")
    await engine.add_file("code", str(path))
    assert not (await engine.graph(dict(collection="code", action="find", symbol="old")))["candidates"]
    with engine.connection("code") as conn:
        assert conn.execute("SELECT count(*) FROM source_graph_outbox").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM sources").fetchone()[0] == "indexed"
    monkeypatch.setattr(store, "apply", original)
    engine._flush_graph("code")
    assert (await engine.graph(dict(collection="code", action="find", symbol="new")))["candidates"]
    with engine.connection("code") as conn:
        assert conn.execute("SELECT count(*) FROM source_graph_outbox").fetchone()[0] == 0


async def test_ack_crash_idempotence_and_restart(engine, source_dir, fake):
    from ragdbman.graph.store import queue

    records = await indexed(engine, source_dir, {"main.py": "def fn():\n    return 1\n"})
    path = source_dir / "main.py"
    snapshot, _ = prepare(
        path,
        records["main.py"]["source_id"],
        hashlib.sha256(path.read_bytes()).hexdigest(),
        [source_dir],
        engine.config.graph,
    )
    with engine.connection("code") as conn, db.transaction(conn):
        queue(conn, snapshot["source_id"], snapshot)
    with engine.connection("code") as conn:
        event = dict(conn.execute("SELECT * FROM source_graph_outbox").fetchone())
    engine.graph_store("code").apply(event)  # graph committed; process dies before ack
    await engine.close()
    restarted = Engine(engine.config, fake)
    try:
        assert list(restarted.registry) == ["code"]  # graph DB is not mistaken for a collection
        with restarted.connection("code") as conn:
            assert conn.execute("SELECT count(*) FROM source_graph_outbox").fetchone()[0] == 0
        result = await restarted.graph(dict(collection="code", action="find", symbol="fn"))
        assert len(result["candidates"]) == 1
    finally:
        await restarted.close()


async def test_unchanged_backfill_without_embeddings_and_read_does_not_build(engine, source_dir, fake):
    await indexed(engine, source_dir, {"main.py": "def fn():\n    return 1\n"})
    engine._reset_graph("code")
    assert (await engine.graph(dict(collection="code", action="find")))["status"] == "not_indexed"
    assert not engine.graph_store("code").path.exists()
    before = len(fake.calls)
    job = await finish(engine, "code", engine.start_scan("code", str(source_dir)))
    assert job["status"] == "completed", job
    assert len(fake.calls) == before
    assert (await engine.graph(dict(collection="code", action="find", symbol="fn")))["candidates"]


async def test_general_and_disabled_do_not_build_graph(engine, source_dir):
    await indexed(engine, source_dir, {"a.py": "def fn():\n    return 1\n"}, kind="general")
    with engine.connection("code") as conn:
        assert not has_outbox(conn)
    assert not engine.graph_store("code").path.exists()
    with pytest.raises(RagError):
        await engine.graph(dict(collection="code", action="find"))
    engine.config.graph.enabled = False
    await indexed(engine, source_dir, {"b.py": "def fn():\n    return 1\n"}, name="disabled")
    assert not engine.graph_store("disabled").path.exists()


async def test_shadowing_ambiguity_cycles_and_limits(engine, source_dir):
    await indexed(
        engine,
        source_dir,
        {
            "lib.py": "def helper():\n    return 1\n",
            "main.py": "from lib import helper\ndef run(helper):\n    return helper()\ndef a():\n    b()\ndef b():\n    a()\n",
            "other.py": "def helper():\n    return 2\n",
        },
    )
    run = await engine.graph(dict(collection="code", symbol="run", action="callees"))
    assert run["relationships"][0]["target_entity_id"] is None
    ambiguous = await engine.graph(dict(collection="code", symbol="helper", action="callers"))
    assert ambiguous["status"] == "ambiguous"
    cycles = await engine.graph(dict(collection="code", symbol="a", action="callees", depth=5))
    assert len(cycles["relationships"]) == 2
    limited = await engine.graph(dict(collection="code", symbol="a", action="callees", depth=5, limit=1))
    assert limited["truncated"]
    with pytest.raises(ValueError):
        GraphRequest(collection="code", symbol="a", depth=6)


@pytest.mark.parametrize(
    "content,status",
    [
        ("def broken(:\n", "parse_error"),
        ("# fake_call()\nmessage = 'other_call()'\n", "parsed"),
    ],
)
def test_comments_strings_and_syntax_errors(tmp_path, content, status):
    path = tmp_path / "a.py"
    path.write_text(content)
    snapshot, _ = prepare(path, "s", "", [tmp_path], GraphConfig())
    assert snapshot["status"] == status
    assert not [e for e in snapshot["relationships"] if e["kind"] == "calls"]


def test_unicode_unsupported_and_budget(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("def café():\n    return 'árvíz'\ndef main():\n    café()\n")
    snapshot, document = prepare(path, "s", "", [tmp_path], GraphConfig())
    assert snapshot["status"] == "parsed"
    assert any(e["name"] == "café" for e in snapshot["entities"])
    assert document.blocks[-1].line_end == 4
    limited, _ = prepare(path, "s", "", [tmp_path], GraphConfig(max_entities_per_file=1))
    assert limited["status"] == "truncated"
    unsupported, doc = prepare(tmp_path / "LICENSE", "s", "", [tmp_path], GraphConfig())
    assert unsupported["status"] == "unsupported_language" and doc is None


async def test_prune_rebuild_and_delete(engine, source_dir):
    await indexed(engine, source_dir, {"main.py": "def fn():\n    return 1\n"})
    job = await finish(engine, "code", engine.start_scan("code", str(source_dir)))
    assert job["status"] == "completed"
    (source_dir / "main.py").unlink()
    await finish(engine, "code", engine.start_scan("code", str(source_dir), prune_missing=True))
    assert not (await engine.graph(dict(collection="code", action="find")))["candidates"]
    (source_dir / "main.py").write_text("def again():\n    return 1\n")
    await engine.add_file("code", str(source_dir / "main.py"))
    await finish(engine, "code", engine.rebuild_collection("code", confirm=True))
    assert (await engine.graph(dict(collection="code", action="find", symbol="again")))["candidates"]
    path = engine.graph_store("code").path
    engine.delete_collection("code", confirm=True)
    assert not path.exists()


def test_graph_wire_scope_and_rest_auth(cfg, fake, source_dir, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)
    cfg.server.mcp_allowed_collections = ["allowed"]
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:
        rejected = rpc(client, "corpus_graph", {"request": {"collection": "secret", "action": "find"}})
        assert rejected.json()["result"]["isError"]
        assert (
            client.post(
                "/api/corpus/graph",
                headers={"Authorization": "Bearer " + QUERY},
                json={"collection": "secret", "action": "find"},
            ).status_code
            == 401
        )
        tools = rpc(client, "", method="tools/list").json()["result"]["tools"]
        graph = next(t for t in tools if t["name"] == "corpus_graph")
        assert graph["annotations"]["readOnlyHint"] and not graph["annotations"]["destructiveHint"]
        client.portal.call(
            partial(indexed, engine, source_dir, {"a.py": "def fn():\n    return 1\n"}, name="allowed")
        )
        request = {"collection": "allowed", "action": "find", "symbol": "fn"}
        answer = rpc(client, "corpus_graph", {"request": {**request, "format": "raw"}}).json()["result"]
        assert not answer.get("isError"), answer
        assert answer["structuredContent"]["candidates"][0]["name"] == "fn"
        rest = client.post("/api/corpus/graph", headers={"Authorization": "Bearer " + ADMIN}, json=request)
        assert rest.status_code == 200 and rest.json()["candidates"][0]["name"] == "fn"
        response = rpc(
            client,
            "corpus_query",
            {
                "collections": ["allowed"],
                "query": "fn",
                "mode": "keyword",
                "include_graph_context": True,
                "format": "raw",
            },
        ).json()["result"]
        assert response["structuredContent"]["results"][0]["graph_context"]["available"]
        assert "graph_context" in response["content"][0]["text"]


@pytest.mark.parametrize(
    "files,symbol,action,kind",
    [
        (
            {
                "pkg/base.py": "class Base:\n    pass\n",
                "pkg/child.py": "from .base import Base\nclass Child(Base):\n    pass\n",
            },
            "Child",
            "inheritance",
            "inherits",
        ),
        (
            {
                "lib.js": "export function helper() { return 1; }",
                "main.js": "import {helper as load} from './lib.js'; function run() { load(); }",
            },
            "helper",
            "callers",
            "calls",
        ),
        (
            {
                "src/lib.rs": "mod util; use crate::util::{helper as load}; fn run() { load(); }",
                "src/util.rs": "pub fn helper() {}",
            },
            "helper",
            "callers",
            "calls",
        ),
        (
            {"api.h": "struct S { int x; };", "main.c": '#include "api.h"\nint run(void) { return 1; }\n'},
            "main.c",
            "dependencies",
            "depends_on",
        ),
        (
            {"a.ts": "interface I { run(): void; } class C implements I { run() {} }"},
            "C",
            "inheritance",
            "implements",
        ),
        ({"a.rs": "trait T {} struct S {} impl T for S {}"}, "S", "inheritance", "implements"),
        ({"a.cs": "interface I {} class C : I {}"}, "C", "inheritance", "implements"),
    ],
)
async def test_static_relation_fixtures(engine, source_dir, files, symbol, action, kind):
    await indexed(engine, source_dir, files)
    result = await engine.graph(dict(collection="code", symbol=symbol, action=action))
    if result["status"] == "ambiguous":
        selected = next(e for e in result["candidates"] if e["kind"] != "implementation")
        result = await engine.graph(dict(collection="code", entity_id=selected["entity_id"], action=action))
    assert result["status"] == "ok", result
    assert any(e["kind"] == kind and e["target_entity_id"] for e in result["relationships"]), result


async def test_receiver_shadow_and_python_class_scope(engine, source_dir):
    await indexed(
        engine,
        source_dir,
        {
            "a.py": "class C:\n    def helper(self):\n        pass\n"
            "    def run(self):\n        helper()\n        self.helper()\n"
            "def outer(C):\n    C.helper()\n"
        },
    )
    run = await engine.graph(dict(collection="code", symbol="C.run", action="callees"))
    edges = {e["target_name"]: e for e in run["relationships"]}
    assert edges["helper"]["target_entity_id"] is None
    assert edges["C.helper"]["target_entity_id"] is not None
    outer = await engine.graph(dict(collection="code", symbol="outer", action="callees"))
    assert outer["relationships"][0]["target_entity_id"] is None


async def test_graph_failure_does_not_fail_search_or_index(engine, source_dir, monkeypatch):
    await indexed(engine, source_dir, {"a.py": "def fn():\n    return 1\n"})
    import ragdbman.graph.query as query

    def broken(*args):
        raise OSError("test read failure")

    monkeypatch.setattr(query, "enrich", broken)
    response = await engine.search(dict(collection="code", query="fn", mode="keyword"))
    assert response["results"][0]["graph_context"]["status"] == "unavailable"
    import ragdbman.graph.parser as parser

    monkeypatch.setattr(parser, "prepare", broken)
    (source_dir / "a.py").write_text("def fresh():\n    return 2\n")
    await engine.add_file("code", str(source_dir / "a.py"))
    with engine.connection("code") as conn:
        assert conn.execute("SELECT status FROM sources").fetchone()[0] == "indexed"
    assert not (await engine.graph(dict(collection="code", action="find")))["candidates"]


async def test_parser_error_and_unknown_source_status(engine, source_dir):
    await indexed(engine, source_dir, {"bad.py": "def invalid(:\n", "LICENSE": "Copyright text\n"})
    with engine.graph_store("code").pool.connection() as conn:
        statuses = dict(conn.execute("SELECT path,status FROM graph_sources"))
    assert statuses == {"bad.py": "parse_error", "LICENSE": "unsupported_language"}
    response = await engine.search(dict(collection="code", query="Copyright", mode="keyword"))
    assert response["results"][0]["graph_context"]["status"] == "unsupported_language"


def test_file_size_and_node_budgets(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("#" + "a" * 1024 * 1024)
    graph, doc = prepare(path, "s", "h", [tmp_path], GraphConfig(max_file_size_mb=1))
    assert graph["status"] == "size_limit" and doc is None
    path.write_text("x = 1\n" * 100)
    graph, _ = prepare(path, "s", "h", [tmp_path], GraphConfig(max_parse_nodes=100))
    assert graph["status"] == "truncated"


async def test_imports_do_not_bind_to_unrelated_languages(engine, source_dir):
    await indexed(
        engine,
        source_dir,
        {
            "lib.js": "export function helper() {}",
            "main.py": "from lib import helper\ndef run():\n    helper()\n",
        },
    )
    result = await engine.graph(dict(collection="code", symbol="run", action="callees"))
    assert result["relationships"][0]["target_entity_id"] is None


async def test_qualified_bases_and_metaclasses(engine, source_dir):
    await indexed(
        engine,
        source_dir,
        {
            "lib.py": "class Base:\n    pass\n",
            "main.py": "import lib\nclass Base:\n    pass\nclass Meta:\n    pass\n"
            "class Child(lib.Base, metaclass=Meta):\n    pass\n",
        },
    )
    result = await engine.graph(dict(collection="code", symbol="Child", action="inheritance"))
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["target_name"] == "lib.Base"
    target = result["relationships"][0]["target_entity_id"]
    entity = next(e for e in result["entities"] if e["entity_id"] == target)
    assert entity["provenance"]["source_path"] == "lib.py"
