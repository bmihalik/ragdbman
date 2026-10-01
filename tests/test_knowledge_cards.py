# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0


import asyncio
import threading
from pathlib import Path

import httpx
import pytest
import sqlite_vec
import yaml
from conftest import finish

from ragdbman.errors import RagError
from ragdbman.knowledge_cards import EMPTY_RESULT, dump_cards, parse
from ragdbman.models import CreateCollection, KnowledgeCardSearchRequest
from ragdbman.web import create_app


def card(card_id="BFS", confidence=1.0, title="Breadth-first search"):
    return {
        "id": card_id,
        "category": "Programming",
        "subcategory": "algorithm",
        "title": title,
        "description": "Explore a graph in layers with a queue.",
        "positive_text": "Use for shortest paths in unweighted graphs.",
        "negative_text": "Avoid for weighted shortest paths.",
        "method_texts": ["Queue driven traversal"],
        "inputs": ["graph"],
        "outputs": ["distances"],
        "costs": {"time": "O(V + E)", "space": "O(V)"},
        "codes": ["def bfs(graph):\n    return distances"],
        "confidence": confidence,
        "source": [{"name": "Introduction to Algorithms", "topic": "BFS"}],
    }


async def create(engine, source_dir, name="cards"):
    await engine.create_collection(
        CreateCollection(name=name, kind="knowledge_cards", source_roots=[str(source_dir)])
    )


async def test_ingestion_field_vectors_and_non_card_skip(engine, source_dir):
    (source_dir / "bfs.yaml").write_text(yaml.safe_dump(card(), sort_keys=False))
    (source_dir / "settings.yml").write_text("theme: dark\n")
    (source_dir / "ignored.txt").write_text("not yaml")
    await create(engine, source_dir)
    completed = await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    assert completed["status"] == "completed"
    assert {
        k: completed["progress"][k]
        for k in ("discovered", "unchanged", "queued", "processing", "completed", "failed", "skipped")
    } == {
        "discovered": 2,
        "unchanged": 0,
        "queued": 0,
        "processing": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 1,
    }
    assert engine.get_collection("cards")["counts"]["cards"] == 1
    with engine.connection("cards") as conn:
        fields = [r[0] for r in conn.execute("SELECT field_type FROM kc_embeddings ORDER BY id")]
        assert fields == ["description", "positive", "negative", "code"]
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


async def test_malformed_card_is_reported_and_old_card_is_atomic(engine, source_dir):
    path = source_dir / "bfs.yaml"
    path.write_text(yaml.safe_dump(card(), sort_keys=False))
    await create(engine, source_dir)
    await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    path.write_text("id: BFS\ncategory: Programming\ntitle: [broken\n")
    failed = await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    assert failed["status"] == "completed_with_errors"
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT title FROM kc_cards").fetchone()[0] == "Breadth-first search"


async def test_duplicate_ids_are_rejected_without_replacing_first(engine, source_dir):
    engine.config.defaults.max_concurrent_files = 1
    (source_dir / "one.yaml").write_text(yaml.safe_dump(card(), sort_keys=False))
    (source_dir / "two.yaml").write_text(yaml.safe_dump(card(title="Duplicate"), sort_keys=False))
    await create(engine, source_dir)
    completed = await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    assert completed["progress"]["completed"] == 1
    assert completed["progress"]["failed"] == 1
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT title FROM kc_cards").fetchone()[0] == "Breadth-first search"


async def test_rest_card_validation_and_duplicate_are_not_server_errors(engine, source_dir, monkeypatch):
    monkeypatch.delenv("RAGDBMAN_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("RAGDBMAN_QUERY_TOKEN", raising=False)
    await create(engine, source_dir)
    malformed = source_dir / "bad.yaml"
    malformed.write_text("id: BROKEN\ncategory: Programming\ntitle: [broken\n")
    original = source_dir / "first.yaml"
    original.write_text(yaml.safe_dump(card()))
    duplicate = source_dir / "duplicate.yaml"
    duplicate.write_text(yaml.safe_dump(card(title="Must not replace the original")))
    app = create_app(engine)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        route = "/api/collections/cards/add_file"
        response = await client.post(route, json={"path": str(malformed)})
        assert response.status_code == 422
        assert response.json()["code"] == "KNOWLEDGE_CARD_INVALID"
        response = await client.post(route, json={"path": str(original)})
        assert response.status_code == 200
        response = await client.post(route, json={"path": str(duplicate)})
        assert response.status_code == 409
        assert response.json()["code"] == "KNOWLEDGE_CARD_DUPLICATE"
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT title FROM kc_cards").fetchone()[0] == "Breadth-first search"


async def test_confidence_threshold_and_keyword_only_avoids_embedder(engine, fake, source_dir):
    path = source_dir / "low.yaml"
    path.write_text(yaml.safe_dump(card(confidence=0.1), sort_keys=False))
    await create(engine, source_dir)
    await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    calls = len(fake.calls)
    results = await engine.search_knowledge_cards(
        KnowledgeCardSearchRequest(
            collection="cards", query="queue graph", mode="keyword", minimum_similarity=0.2
        )
    )
    assert results == []
    assert len(fake.calls) == calls
    results = await engine.search_knowledge_cards(
        KnowledgeCardSearchRequest(
            collection="cards", query="queue graph", mode="keyword", minimum_similarity=0
        )
    )
    assert results[0]["card"]["id"] == "BFS"


def test_yaml_output_hides_only_id_and_preserves_types():
    text = dump_cards([card(), card("DFS", title="Depth-first search")])
    assert text.count("---") == 2
    documents = list(yaml.safe_load_all(text))
    assert all("id" not in item for item in documents)
    assert documents[0]["codes"][0].startswith("def bfs")
    assert documents[0]["costs"]["time"] == "O(V + E)"
    assert dump_cards([]) == EMPTY_RESULT


@pytest.mark.parametrize(
    "raw",
    [
        "id: a\nid: b\ncategory: c\ntitle: t\ndescription: d\nconfidence: 1\n",
        "id: a\ncategory: c\ntitle: t\ndescription: d\nconfidence: .nan\n",
        "id: &x a\ncategory: c\ntitle: *x\ndescription: d\nconfidence: 1\n",
    ],
)
def test_hardened_yaml_rejects_ambiguous_or_nonfinite_cards(raw):
    with pytest.raises(RagError):
        parse(raw)


def test_environment_validation(monkeypatch, cfg, fake):
    from ragdbman.engine import Engine

    monkeypatch.setenv("RAGDBMAN_KC_MIN_SIMILARITY", "nan")
    with pytest.raises(RagError, match="Invalid Knowledge Cards environment"):
        Engine(cfg, fake)


@pytest.mark.parametrize("missing", [None, "positive_text", "negative_text", "both"])
async def test_exact_vector_formula_and_fallback(engine, source_dir, monkeypatch, missing):
    data = card(confidence=0.8)
    for key in ("positive_text", "negative_text"):
        if missing in (key, "both"):
            data.pop(key)
    path = source_dir / "card.yml"
    path.write_text(yaml.safe_dump(data))
    await create(engine, source_dir)
    await engine.add_file("cards", str(path))
    # q=(1,0); description=(.6,.8), positive=(1,0), negative=(0,1).
    vectors = {"description": [0.6, 0.8], "positive": [1.0, 0.0], "negative": [0.0, 1.0]}
    with engine.connection("cards") as conn:
        for field, value in vectors.items():
            conn.execute(
                "UPDATE kc_embeddings SET embedding=? WHERE field_type=?",
                (sqlite_vec.serialize_float32(value + [0.0] * 6), field),
            )

    async def query_embed(*args):
        return [[1.0, 0.0] + [0.0] * 6]

    monkeypatch.setattr(engine.embedder, "embed", query_embed)
    for query_type, expected in (("general", 0.48), ("expert", 0.48 if missing else 0.896)):
        result = await engine.search_knowledge_cards(
            collection="cards",
            query="unweighted",
            mode="vector",
            query_type=query_type,
            minimum_similarity=0,
        )
        assert result[0]["score"] == pytest.approx(expected, abs=1e-6)
    pruned = await engine.search_knowledge_cards(
        collection="cards",
        query="unweighted",
        mode="vector",
        query_type="general",
        minimum_similarity=0.5,
    )
    assert pruned == []


async def test_card_replacement_rebuild_prune_and_restart(engine, source_dir, cfg, fake):
    from ragdbman.engine import Engine

    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    first = await engine.add_file("cards", str(path))
    same = await engine.add_file("cards", str(path))
    assert same["classification"] == "unchanged"
    path.write_text(yaml.safe_dump(card("new-id", title="Replacement")))
    await engine.add_file("cards", str(path))
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT id FROM kc_cards").fetchone()[0] == "new-id"
        assert conn.execute("SELECT COUNT(*) FROM kc_fts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM kc_embeddings").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == 2
    rebuilt = await finish(engine, "cards", engine.rebuild_collection("cards", confirm=True))
    assert rebuilt["status"] == "completed"
    restored = Engine(cfg, fake)
    try:
        assert restored.get_collection("cards")["counts"]["cards"] == 1
    finally:
        await restored.close()
    # Scan assigns the registered root even to a previously manually added source.
    path.write_text(yaml.safe_dump(card("new-id", title="Root-bound replacement")))
    await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    path.unlink()
    await finish(engine, "cards", engine.start_scan("cards", str(source_dir), prune_missing=True))
    with engine.connection("cards") as conn:
        for table in ("kc_cards", "kc_fts", "kc_embeddings"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    engine.remove_source("cards", first["source_id"], confirm=True)
    assert engine.get_collection("cards")["counts"]["sources"] == 0


async def test_non_card_replacement_removes_stale_vectors(engine, source_dir):
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    await engine.add_file("cards", str(path))
    path.write_text("unrelated: config\n")
    result = await engine.add_file("cards", str(path))
    assert result["skipped"]
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kc_embeddings").fetchone()[0] == 0


async def test_no_tokenizer_or_sidecars_and_isolated_schemas(engine, source_dir):
    engine.config.defaults.allow_approximate_tokenizer = False
    await create(engine, source_dir)
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await engine.add_file("cards", str(path))
    assert not list(source_dir.rglob(".ragdbman"))
    assert engine.get_collection("cards")["chunking"]["tokenizer_mode"] == "whole_field"
    engine.config.defaults.allow_approximate_tokenizer = True
    await engine.create_collection(name="normal")
    with engine.connection("normal") as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'kc_%'").fetchall()
    with pytest.raises(RagError, match="not a Knowledge Cards"):
        await engine.search_knowledge_cards(collection="normal", query="test")
    with pytest.raises(RagError, match="chunk overrides"):
        await engine.create_collection(name="bad", kind="knowledge_cards", chunk_size_tokens=20)


async def test_hybrid_fallback_and_literal_fts_query(engine, source_dir, fake):
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    await engine.add_file("cards", str(path))
    fake.failure = True
    matches = await engine.search_knowledge_cards(collection="cards", query='queue OR "graph": *')
    assert matches[0]["card"]["id"] == "BFS"
    assert matches[0]["vector_score"] is None
    with pytest.raises(RagError, match="test outage"):
        await engine.search_knowledge_cards(collection="cards", query="graph", mode="vector")


async def test_rest_mcp_yaml_and_multi_search(engine, source_dir):
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    await engine.add_file("cards", str(path))
    app = create_app(engine, False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        result = await client.post(
            "/api/knowledge-cards/search", json={"collection": "cards", "query": "queue", "mode": "keyword"}
        )
        assert result.status_code == 200
        payload = result.json()
        assert "id" not in yaml.safe_load(payload["yaml"])
        assert yaml.safe_load(payload["results"][0]["yaml"])["codes"] == card()["codes"]
        invalid = await client.post(
            "/api/knowledge-cards/search",
            json={"collection": "cards", "query": "queue", "minimum_similarity": 2},
        )
        assert invalid.status_code == 422
        for mode in ("keyword", "hybrid", "vector"):
            result = await client.post(
                "/api/search/multi", json={"collections": ["cards"], "query": "queue", "mode": mode}
            )
            assert result.status_code == 200
            assert result.json()["collections_failed"] == []
    blocks = await app.state.mcp.call_tool(
        "corpus_query", {"collections": ["cards"], "query": "queue", "mode": "keyword"}
    )
    # Default MCP output is text-only; raw mode remains explicitly available.
    assert blocks.structuredContent is None
    assert "```yaml" in blocks.content[0].text
    raw = await app.state.mcp.call_tool(
        "corpus_query", {"collections": ["cards"], "query": "queue", "mode": "keyword", "format": "raw"}
    )
    assert "id" not in raw.structuredContent["results"][0]["content"]
    empty = await app.state.mcp.call_tool(
        "corpus_query", {"collections": ["cards"], "query": "nonexistentword", "mode": "keyword"}
    )
    assert empty.structuredContent is None
    assert "No results met" in empty.content[0].text


async def test_card_parse_does_not_block_overview(engine, source_dir, monkeypatch):
    import ragdbman.knowledge_cards as kc

    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    entered, release = threading.Event(), threading.Event()
    original = kc.read_card

    def slow_read(path):
        entered.set()
        assert release.wait(5)
        return original(path)

    monkeypatch.setattr(kc, "read_card", slow_read)
    job = engine.start_scan("cards", str(source_dir))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        app = create_app(engine, False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as c:
            result = await asyncio.wait_for(c.get("/api/collections"), 0.5)
            assert result.status_code == 200
    finally:
        release.set()
        await finish(engine, "cards", job)


async def test_cancel_before_card_commit(engine, source_dir, fake):
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))
    await create(engine, source_dir)
    fake.entered.clear()
    fake.gate = asyncio.Event()
    job = engine.start_scan("cards", str(source_dir))
    await asyncio.wait_for(fake.entered.wait(), 3)
    engine.cancel_job(job["id"])
    fake.gate.set()
    complete = await finish(engine, "cards", job)
    assert complete["status"] == "cancelled"
    assert engine.get_collection("cards")["counts"]["cards"] == 0
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kc_embeddings").fetchone()[0] == 0


@pytest.mark.parametrize("vector", [[0.0] * 8, [float("nan")] * 8, [1.0] * 7, [float("inf")] * 8])
async def test_invalid_embeddings_fail_without_partial_card(engine, source_dir, monkeypatch, vector):
    await create(engine, source_dir)
    path = source_dir / "card.yaml"
    path.write_text(yaml.safe_dump(card()))

    async def invalid(texts, *args):
        return [vector for _ in texts]

    monkeypatch.setattr(engine.embedder, "embed", invalid)
    with pytest.raises(RagError, match="finite, nonzero"):
        await engine.add_file("cards", str(path))
    assert engine.get_collection("cards")["counts"]["cards"] == 0


async def test_highest_similarity_low_confidence_pruned_in_all_modes(engine, source_dir, monkeypatch):
    await create(engine, source_dir)
    for name, confidence in (("high", 1.0), ("low", 0.1)):
        path = source_dir / f"{name}.yaml"
        path.write_text(yaml.safe_dump(card(name, confidence)))
        await engine.add_file("cards", str(path))
    vector = [1.0] + [0.0] * 7
    with engine.connection("cards") as conn:
        conn.execute("UPDATE kc_embeddings SET embedding=?", (sqlite_vec.serialize_float32(vector),))

    async def embed(*args):
        return [vector]

    monkeypatch.setattr(engine.embedder, "embed", embed)
    for mode in ("keyword", "vector", "hybrid"):
        matches = await engine.search_knowledge_cards(
            collection="cards", query="queue", mode=mode, minimum_similarity=0.65
        )
        assert [m["card"]["id"] for m in matches] == ["high"]
    result = await engine.search_knowledge_cards(collection="cards", query="queue", minimum_similarity=0)
    assert result[0]["rank_score"] == pytest.approx(2 / (engine.config.search.rrf_k + 1))
    assert result[1]["rank_score"] == pytest.approx(2 / (engine.config.search.rrf_k + 2))


@pytest.mark.parametrize(
    "override",
    [
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": True},
        {"title": " "},
        {"codes": "not-a-list"},
        {"source": [{"name": 7}]},
    ],
)
def test_invalid_known_field_types(override):
    with pytest.raises(RagError):
        parse(yaml.safe_dump({**card(), **override}))


async def test_managed_upload_and_structured_filter_rejection(engine, source_dir):
    await create(engine, source_dir)
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
        response = await c.post(
            "/api/collections/cards/upload",
            files={"file": ("upload.yaml", yaml.safe_dump(card()), "application/yaml")},
        )
        assert response.status_code == 200, response.text
        source_id = response.json()["source_id"]
        for request in (
            {"mode": "structured"},
            {"mode": "keyword", "filters": {"source_ids": [source_id]}},
        ):
            response = await c.post("/api/search", json={"collection": "cards", "query": "queue", **request})
            assert response.status_code == 400
        engine.remove_source("cards", source_id, confirm=True, delete_original_managed_file=True)
        assert not list(Path(engine.get_collection("cards")["managed_root"]).glob("*.yaml"))


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_top_k(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KnowledgeCardSearchRequest(collection="cards", query="queue", top_k=value)


def test_blank_query():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KnowledgeCardSearchRequest(collection="cards", query="  ")
