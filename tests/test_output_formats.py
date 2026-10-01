# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import copy
import json
from functools import partial

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_corpus import ADMIN, QUERY, rpc
from test_knowledge_cards import card
from test_source_graph import indexed

from ragdbman import corpus
from ragdbman.engine import Engine
from ragdbman.formatting import graph_context, inline, render_corpus, render_graph
from ragdbman.graph.query import GraphRequest, MCPGraphRequest
from ragdbman.models import MultiSearchRequest, SearchRequest
from ragdbman.web import create_app

FILES = {
    "src/lib.py": "def helper():\n    return 1\n",
    "src/main.py": "from .lib import helper\n"
    "def parse_config():\n    helper()\n    dynamic_call()\n"
    "def main():\n    parse_config()\n",
}


@pytest.fixture
async def code(engine, source_dir):
    await indexed(engine, source_dir, FILES)
    return engine


async def test_corpus_raw_and_llm_same_evidence_no_extra_calls(code, fake):
    req = corpus.CorpusQuery(query="parse_config", collections=["code"], mode="keyword")
    before = len(fake.calls)
    raw = await corpus.corpus_query(code, req)
    snapshot = copy.deepcopy(raw)
    text = await corpus.corpus_query(code, req.model_copy(update={"format": "llm"}))
    assert text == corpus.render(raw)
    assert raw == snapshot and len(fake.calls) == before
    for expected in (
        "## Result 1 (score:",
        "src/main.py",
        "function:",
        "parse_config()",
        "Calls:",
        "Called by:",
        "imports",
        "[unresolved]",
        "Score policy:",
    ):
        assert expected in text
    assert "```json" not in text
    for hidden in ("parser_version", "content_hash", "chunk_id", "entity_id", "relationship_id"):
        assert hidden not in text
    assert len(text) < len(json.dumps(raw))
    assert "This function reads and validates" not in text  # no generated summary
    off = await corpus.corpus_query(
        code, req.model_copy(update={"format": "llm", "include_graph_context": False})
    )
    assert "Calls:" not in off and "Static source graph context" not in off


@pytest.mark.parametrize(
    "action,symbol",
    [
        ("find", "parse_config"),
        ("callers", "parse_config"),
        ("callees", "parse_config"),
        ("neighbors", "parse_config"),
        ("impact", "parse_config"),
        ("inheritance", "parse_config"),
        ("dependencies", "src/main.py"),
    ],
)
async def test_graph_formats(code, action, symbol):
    req = GraphRequest(collection="code", action=action, symbol=symbol, depth=2)
    raw = await code.corpus_graph(req)
    text = await code.corpus_graph(req.model_copy(update={"format": "llm"}))
    assert isinstance(raw, dict) and text == render_graph(raw)
    assert "best-effort static resolution" in text
    assert "content_hash" not in text and "relationship_id" not in text
    if action == "find":
        assert "Use entity_id=" in text and raw["candidates"][0]["entity_id"] in text
    else:
        assert "entity_id" not in text
    if action == "callees":
        assert "calls" in text and "[unresolved]" in text and "lines " in text


async def test_search_programmatic_and_multi_formats(code, fake):
    for req in (
        SearchRequest(collection="code", query="parse_config", mode="keyword"),
        MultiSearchRequest(collections=["code"], query="parse_config", mode="keyword"),
    ):
        fn = code._query_documents if isinstance(req, SearchRequest) else code._query_many
        before = len(fake.calls)
        assert isinstance(await fn(req), dict)
        text = await fn(req.model_copy(update={"format": "llm"}))
        assert "Source code | Collection:" in text and "code" in text and "Calls:" in text
        assert len(fake.calls) == before


def test_wire_defaults_raw_parity_and_rest(cfg, fake, source_dir, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", ADMIN)
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", QUERY)
    cfg.server.mcp_admin_enabled = True
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:
        client.portal.call(partial(indexed, engine, source_dir, FILES))
        for profile, token in (("query", QUERY), ("admin", ADMIN)):
            query = {"query": "parse_config", "collections": ["code"], "mode": "keyword"}
            graph = {"collection": "code", "symbol": "parse_config", "action": "callees"}
            for tool, args in (("corpus_query", query), ("corpus_graph", graph)):
                text_result = rpc(client, tool, args, profile=profile, token=token).json()["result"]
                assert not text_result.get("isError") and "structuredContent" not in text_result
                assert len(text_result["content"]) == 1
                raw_args = {**args, "format": "raw"}
                raw = rpc(client, tool, raw_args, profile=profile, token=token).json()["result"]
                assert json.loads(raw["content"][0]["text"]) == raw["structuredContent"]
                assert "content_hash" in raw["content"][0]["text"]
        for route, body in (
            ("/api/corpus-query", query),
            ("/api/corpus-graph", graph),
        ):
            headers = {"Authorization": "Bearer " + ADMIN}
            raw = client.post(route, headers=headers, json=body)
            assert raw.status_code == 200 and raw.headers["content-type"].startswith("application/json")
            explicit_raw = client.post(route, headers=headers, json={**body, "format": "raw"})
            assert explicit_raw.json() == raw.json()
            text = client.post(route, headers=headers, json={**body, "format": "llm"})
            assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
            assert text.text.startswith("# ") and "parse_config()" in text.text
            invalid = client.post(route, headers=headers, json={**body, "format": "xml"})
            assert invalid.status_code == 422
            denied = client.post(
                route, headers={"Authorization": "Bearer " + QUERY}, json={**body, "format": "llm"}
            )
            assert denied.status_code == 401
        schemas = rpc(client, "", method="tools/list").json()["result"]["tools"]
        search = next(t for t in schemas if t["name"] == "corpus_query")
        assert search["inputSchema"]["properties"]["format"]["default"] == "llm"
        assert {t["name"] for t in schemas} == {"corpus_query", "corpus_graph", "corpus_describe"}


@pytest.mark.parametrize(
    "model,args",
    [
        (corpus.CorpusQuery, {"query": "x", "collections": ["code"]}),
        (SearchRequest, {"query": "x", "collection": "code"}),
        (MultiSearchRequest, {"query": "x", "collections": ["code"]}),
        (GraphRequest, {"collection": "code", "action": "find"}),
        (MCPGraphRequest, {"collection": "code", "action": "find"}),
    ],
)
def test_format_validation_and_defaults(model, args):
    assert model(**args).format == ("llm" if model is MCPGraphRequest else "raw")
    for invalid in ("json", "LLM", None, 1):
        with pytest.raises(ValidationError):
            model(**args, format=invalid)


def test_safe_labels_fences_yaml_and_small_scores():
    hostile = "file\n## FAKE\n``` <script>alert(1)</script>\x1b"
    assert "\n" not in inline(hostile) and "\\n" in inline(hostile)
    data = {"title": hostile, "codes": ["x = '```'\n\n\n"], "description": "Literal content"}
    response = {
        "results": [
            {
                "collection": hostile,
                "kind": "knowledge_card",
                "title": hostile,
                "provenance": {"filename": hostile},
                "content": data,
                "relevance": {"score": 0.00000014, "policy": "bm25_strength"},
            }
        ],
        "warnings": [],
    }
    before = copy.deepcopy(response)
    text = render_corpus(response)
    assert "1.4e-07" in text and "\n## FAKE\n" not in text and "Knowledge Card" in text
    payload = text.split("````yaml\n", 1)[1].rsplit("````", 1)[0]
    assert yaml.safe_load(payload)["codes"] == data["codes"]
    assert response == before


@pytest.mark.parametrize(
    "status",
    ["not_indexed", "pending_or_stale", "parse_error", "size_limit", "unsupported_language", "unavailable"],
)
def test_graph_unavailability_visible(status):
    text = graph_context({"available": False, "status": status})
    assert status in text and "unavailable" in text


def test_partial_and_empty_results_and_diagnostics():
    text = graph_context(
        {
            "available": True,
            "entities": [],
            "relationships": [],
            "truncated": True,
            "warnings": ["budget reached"],
        }
    )
    assert "partial/truncated" in text and "budget reached" in text
    text = render_corpus(
        {
            "results": [],
            "warnings": [
                {"collection": "broken", "code": "OLLAMA_UNAVAILABLE", "message": "service unavailable"}
            ],
        }
    )
    assert "No results met" in text and "OLLAMA_UNAVAILABLE" in text
    graph = render_graph(
        {
            "collection": "code",
            "action": "callers",
            "status": "not_found",
            "message": "No current graph entity matched.",
            "truncated": True,
        }
    )
    assert "No current graph entity matched" in graph and "Results truncated" in graph


async def test_ambiguous_graph_retains_selection_ids(code, source_dir):
    path = source_dir / "other.py"
    path.write_text("def parse_config():\n    return 1\n")
    await code.collection_add_file("code", str(path))
    text = await code.corpus_graph(
        dict(collection="code", symbol="parse_config", action="callers", format="llm")
    )
    assert "ambiguous" in text and text.count("Use entity_id=") == 2


@pytest.mark.parametrize("kind", ["general", "knowledge_cards"])
async def test_non_code_search_formats(engine, source_dir, kind):
    files = (
        {"card.yaml": yaml.safe_dump(card())}
        if kind == "knowledge_cards"
        else {"manual.txt": "A queue holds work for a consumer."}
    )
    await indexed(engine, source_dir, files, name="docs", kind=kind)
    response = await engine._query_documents(
        dict(collection="docs", query="queue", mode="keyword", format="llm")
    )
    assert "Calls:" not in response
    if kind == "knowledge_cards":
        assert "Knowledge Card" in response and "```yaml" in response and "confidence_weighted" in response
        multi = await engine._query_many(
            dict(collections=["docs"], query="queue", mode="keyword", format="llm")
        )
        assert "Knowledge Card" in multi and "```yaml" in multi and "reciprocal_collection_rank" in multi
    else:
        assert "Document excerpt" in response and "A queue holds" in response


@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
async def test_llm_does_not_repeat_embedding(code, fake, mode):
    before = len(fake.calls)
    result = await corpus.corpus_query(
        code, corpus.CorpusQuery(query="parse_config", collections=["code"], mode=mode, format="llm")
    )
    assert result.startswith("# Corpus query") and len(fake.calls) == before + 1
