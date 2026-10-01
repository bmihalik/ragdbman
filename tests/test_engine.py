# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import asyncio
from pathlib import Path

import pytest
from conftest import finish
from tokenizers import Tokenizer as HFTokenizer
from tokenizers.models import WordLevel

from ragdbman import db
from ragdbman.chunking import tokenizer_path
from ragdbman.engine import Engine
from ragdbman.errors import RagError


async def test_scan_rescan_reindex(engine, source_dir):
    await engine.collection_create(name="docs", source_roots=[str(source_dir)])
    path = source_dir / "a.md"
    path.write_text("# Retrieval\n\nPrice $25. Rating 4.5.\n\nPublished 2026-08-22.")
    job = await finish(engine, "docs", engine.scan_start("docs", str(source_dir)))
    assert job["status"] == "completed"
    assert job["progress"]["completed"] == 1
    initial = engine.collection_get("docs")
    source = engine.collection_list_files("docs")[0]
    job = await finish(engine, "docs", engine.scan_start("docs", str(source_dir)))
    assert job["progress"]["unchanged"] == 1
    assert engine.collection_get("docs")["counts"]["chunks"] == initial["counts"]["chunks"]
    path.write_text("# Replacement\n\nBrand-new vocabulary.")
    await engine.collection_add_file("docs", str(path))
    assert engine.collection_list_files("docs")[0]["id"] == source["id"]
    assert not (await engine._query_documents({"collection": "docs", "query": "rating", "mode": "keyword"}))[
        "results"
    ]
    with engine.connection("docs") as conn:
        assert conn.execute("SELECT count(*) FROM source_versions").fetchone()[0] == 2
        assert (
            conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            == conn.execute("SELECT count(*) FROM chunks_vec0").fetchone()[0]
        )


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid", "structured"])
async def test_four_modes(engine, source_dir, mode):
    await engine.collection_create(name="docs")
    path = source_dir / "a.md"
    path.write_text("# Retrieval\n\nPrice €25. Rating 4.5. Published 2026-08-22.")
    await engine.collection_add_file("docs", str(path))
    response = await engine._query_documents({"collection": "docs", "query": "retrieval", "mode": mode})
    assert response["results"]
    result = response["results"][0]
    assert result["source_filename"] == "a.md"
    assert result["metadata_facts"]
    assert response["exhaustive"] is True


@pytest.mark.parametrize(
    "op,value,low,high,expected",
    [
        ("equal", 25, None, None, True),
        ("not_equal", 25, None, None, False),
        ("less_than", 30, None, None, True),
        ("less_than_or_equal", 25, None, None, True),
        ("greater_than", 30, None, None, False),
        ("greater_than_or_equal", 25, None, None, True),
        ("between", None, 20, 30, True),
        ("exists", None, None, None, True),
    ],
)
async def test_numeric_operators(engine, source_dir, op, value, low, high, expected):
    await engine.collection_create(name="n")
    p = source_dir / "n.txt"
    p.write_text("Retrieval price $25")
    await engine.collection_add_file("n", str(p))
    nf = {"field": "price", "op": op, "value": value, "from": low, "to": high}
    result = await engine._query_documents(
        {"collection": "n", "query": "", "mode": "structured", "filters": {"numeric": [nf]}}
    )
    assert bool(result["results"]) == expected


async def test_combined_filters_and_diagnostics(engine, source_dir):
    await engine.collection_create(name="filters")
    p = source_dir / "a.md"
    p.write_text("# Retrieval\n\nPrice €25. Published 2026-08-22.")
    source = await engine.collection_add_file("filters", str(p))
    filters = {
        "source_extensions": ["md"],
        "source_ids": [source["source_id"]],
        "path_prefix": str(source_dir),
        "keywords": ["retrieval"],
        "numeric": [
            {"field": "cost", "op": "less_than", "value": 50, "currency": "EUR"},
            {"field": "published_date", "op": "greater_than", "value": "2026-01-01"},
            {"field": "unknown", "op": "exists"},
        ],
    }
    response = await engine._query_documents(
        {"collection": "filters", "query": "retrieval", "filters": filters}
    )
    assert len(response["results"]) == 1
    assert response["skipped_filters"][0]["field"] == "unknown"
    filters["numeric"][0]["currency"] = "USD"
    assert not (
        await engine._query_documents({"collection": "filters", "query": "retrieval", "filters": filters})
    )["results"]


async def test_include_flags_and_truncation(engine, source_dir):
    engine.config.search.return_context_chars_per_chunk = 5
    await engine.collection_create(name="short")
    p = source_dir / "a.txt"
    p.write_text("Retrieval content with more text.")
    await engine.collection_add_file("short", str(p))
    response = await engine._query_documents({"collection": "short", "query": "retrieval", "mode": "keyword"})
    result = response["results"][0]
    assert result["truncated"] and len(result["text"]) == 5
    response = await engine._query_documents(
        {
            "collection": "short",
            "query": "retrieval",
            "mode": "keyword",
            "include_text": False,
            "include_links": False,
        }
    )
    assert response["results"][0]["text"] is None
    assert response["results"][0]["source_link"] is None


async def test_collection_kinds_and_multi_search(engine, source_dir, fake):
    await engine.collection_create(name="general")
    await engine.collection_create(name="code", kind="source_code")
    path = source_dir / "functions.py"
    path.write_text("def retrieval():\n    return 42\n")
    await engine.collection_add_file("code", str(path))
    assert not (source_dir / ".ragdbman").exists()
    code = await engine._query_documents({"collection": "code", "query": "retrieval", "mode": "keyword"})
    assert code["results"][0]["line_start"] == 1
    assert code["results"][0]["markdown_path"] is None
    await engine.collection_add_file("general", str(path))
    general = await engine._query_documents(
        {"collection": "general", "query": "retrieval", "mode": "keyword"}
    )
    assert general["results"][0]["line_start"] is None
    assert general["results"][0]["markdown_path"]
    response = await engine._query_many(
        {"collections": ["general", "code", "absent"], "query": "retrieval", "mode": "keyword"}
    )
    assert set(response["collections_searched"]) == {"general", "code"}
    assert response["collections_failed"][0]["collection"] == "absent"
    assert len({r["collection_id"] for r in response["results"]}) == 2
    models = {call[1] for call in fake.calls}
    assert engine.config.ollama.source_code_embedding_model in models


async def test_model_specific_tokenizer(engine, source_dir):
    path = tokenizer_path(engine.base, "org/custom:f16")
    path.parent.mkdir(parents=True, exist_ok=True)
    HFTokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]")).save(str(path))
    engine.config.defaults.allow_approximate_tokenizer = False
    meta = await engine.collection_create(name="exact", embedding_model="org/custom:f16")
    assert meta["chunking"]["tokenizer_mode"] == "exact"
    p = source_dir / "a.txt"
    p.write_text("Embedding document")
    await engine.collection_add_file("exact", str(p))
    assert engine.collection_get("exact")["counts"]["indexed_sources"] == 1


async def test_dimension_failure_atomicity_and_retry(engine, source_dir, fake):
    await engine.collection_create(name="atomic")
    p = source_dir / "a.txt"
    p.write_text("Initial text")
    result = await engine.collection_add_file("atomic", str(p))
    with engine.connection("atomic") as conn:
        old_id = conn.execute("SELECT id FROM chunks").fetchone()[0]
    p.write_text("Changed content")
    fake.dimensions = 4
    with pytest.raises(RagError, match="VECTOR_SCHEMA_MISMATCH"):
        await engine.collection_add_file("atomic", str(p))
    with engine.connection("atomic") as conn:
        assert conn.execute("SELECT id FROM chunks").fetchone()[0] == old_id
    assert engine.collection_get_file("atomic", result["source_id"])["status"] == "failed"
    fake.dimensions = 8
    assert (await engine.collection_add_file("atomic", str(p)))["classification"] == "previously_failed"


async def test_delete_cascades_and_preserves_original(engine, source_dir):
    await engine.collection_create(name="delete")
    p = source_dir / "a.txt"
    p.write_text("Keyword price $25")
    source = await engine.collection_add_file("delete", str(p))
    with pytest.raises(RagError, match="CONFIRMATION_REQUIRED"):
        engine.collection_remove_file("delete", source["source_id"])
    with pytest.raises(RagError, match="PATH_NOT_ALLOWED"):
        engine.collection_remove_file("delete", source["source_id"], True, True)
    engine.collection_remove_file("delete", source["source_id"], True)
    assert p.exists()
    with engine.connection("delete") as conn:
        for table in [
            "sources",
            "chunks",
            "chunk_vectors",
            "chunks_vec0",
            "chunks_fts",
            "chunk_numeric_values",
            "chunk_keywords",
            "keywords",
            "source_versions",
            "artifacts",
        ]:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
        assert (
            conn.execute("SELECT count(*) FROM audit_log WHERE action='collection_remove_file'").fetchone()[0]
            == 1
        )


async def test_delete_managed_file_and_collection(engine):
    meta = await engine.collection_create(name="uploads")
    p = Path(meta["managed_root"]) / "u.txt"
    p.write_text("upload text")
    source = await engine._add_file("uploads", str(p), "upload")
    engine.collection_remove_file("uploads", source["source_id"], True, True)
    assert not p.exists()
    p.write_text("preserved")
    engine.collection_delete("uploads", True)
    assert p.exists()
    assert not Path(meta["database_path"]).exists()
    assert engine.collections_list() == []


async def test_scan_busy_cancel_resume(engine, source_dir, fake):
    await engine.collection_create(name="jobs")
    for i in range(4):
        (source_dir / f"{i}.txt").write_text(f"Document {i}")
    fake.entered.clear()
    fake.gate = asyncio.Event()
    job = engine.scan_start("jobs", str(source_dir))
    assert engine.scan_start("jobs", str(source_dir))["id"] == job["id"]
    with pytest.raises(RagError, match="COLLECTION_BUSY"):
        engine.collection_delete("jobs", True)
    await asyncio.wait_for(fake.entered.wait(), 10)
    engine.scan_job_cancel(job["id"])
    fake.gate.set()
    result = await finish(engine, "jobs", job)
    assert result["status"] == "cancelled"
    resumed = engine.scan_job_resume("jobs", job["id"])
    result = await finish(engine, "jobs", resumed)
    assert result["status"] == "completed"
    assert engine.collection_get("jobs")["counts"]["indexed_sources"] == 4


async def test_worker_contains_failures(engine, source_dir, monkeypatch):
    await engine.collection_create(name="worker")
    (source_dir / "a.txt").write_text("x")
    (source_dir / "b.txt").write_text("y")
    from ragdbman import engine as module

    original = module.extract

    async def broken(path, *args):
        if path.name == "a.txt":
            raise RuntimeError("deliberate extractor crash")
        return await original(path, *args)

    monkeypatch.setattr(module, "extract", broken)
    result = await finish(engine, "worker", engine.scan_start("worker", str(source_dir)))
    assert result["status"] == "completed_with_errors"
    assert result["progress"]["failed"] == 1 and result["progress"]["completed"] == 1


async def test_recover_interrupted_jobs(engine, source_dir, cfg, fake):
    await engine.collection_create(name="recover")
    (source_dir / "a.txt").write_text("content")
    fake.entered.clear()
    fake.gate = asyncio.Event()
    job = engine.scan_start("recover", str(source_dir))
    await asyncio.wait_for(fake.entered.wait(), 10)
    await engine.close()
    replacement = Engine(cfg, fake)
    try:
        assert replacement.scan_job_get("recover", job["id"])["status"] == "paused"
        with replacement.connection("recover") as conn:
            stages = [r[0] for r in conn.execute("SELECT stage FROM job_items")]
            assert "retryable" in stages
        fake.gate = None
        result = await finish(replacement, "recover", replacement.scan_job_resume("recover", job["id"]))
        assert result["status"] == "completed"
    finally:
        await replacement.close()


async def test_prune_missing(engine, source_dir):
    await engine.collection_create(name="prune")
    p = source_dir / "a.txt"
    p.write_text("remove me")
    await finish(engine, "prune", engine.scan_start("prune", str(source_dir)))
    p.unlink()
    await finish(
        engine, "prune", engine.scan_start("prune", str(source_dir), prune_missing=True, confirm=True)
    )
    assert engine.collection_list_files("prune")[0]["status"] == "missing"
    assert engine.collection_get("prune")["counts"]["chunks"] == 0


async def test_unsupported_and_oversized(engine, source_dir):
    await engine.collection_create(name="unsupported")
    (source_dir / "a.weird").write_text("unknown format")
    outcome = await engine.collection_add_file("unsupported", str(source_dir / "a.weird"))
    assert outcome["classification"] == "unsupported"
    engine.config.defaults.max_file_size_mb = 1
    (source_dir / "big.txt").write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(RagError, match="FILE_TOO_LARGE"):
        await engine.collection_add_file("unsupported", str(source_dir / "big.txt"))


async def test_roots_maintenance_rebuild_and_manifest(engine, source_dir):
    meta = await engine.collection_create(name="maintenance", description="Before")
    root_id = engine.collection_add_root("maintenance", str(source_dir))["root_id"]
    assert engine.collection_list_roots("maintenance")[0]["id"] == root_id
    p = source_dir / "a.txt"
    p.write_text("retrieval price $25")
    await engine.collection_add_file("maintenance", str(p))
    engine.collection_remove_root("maintenance", root_id, confirm=True)
    assert engine.collection_list_roots("maintenance") == []
    assert engine.collection_config_update("maintenance", "After")["description"] == "After"
    assert engine.collection_list_keywords("maintenance", "retrieval")
    assert engine.collection_list_metadata_fields("maintenance")
    engine.collection_vacuum("maintenance")
    manifest = engine.collection_export_manifest("maintenance")
    assert manifest["collection"]["id"] == meta["id"] and len(manifest["sources"]) == 1
    job = await finish(engine, "maintenance", engine.collection_rebuild("maintenance", True))
    assert job["status"] == "completed"
    assert engine.collection_get("maintenance")["counts"]["indexed_sources"] == 1
    assert (
        await engine._query_documents({"collection": "maintenance", "query": "retrieval", "mode": "keyword"})
    )["results"]


async def test_degraded_health_and_keyword_without_ollama(engine, source_dir, fake):
    await engine.collection_create(name="offline")
    p = source_dir / "a.txt"
    p.write_text("offline retrieval")
    await engine.collection_add_file("offline", str(p))
    fake.failure = True
    assert not (await engine.health_status())["ollama_reachable"]
    assert (
        await engine._query_documents({"collection": "offline", "query": "retrieval", "mode": "keyword"})
    )["results"]
    with pytest.raises(RagError):
        await engine._query_documents({"collection": "offline", "query": "retrieval"})


async def test_restart_preserves_indexed_data_and_search(engine, source_dir, cfg, fake):
    await engine.collection_create(name="persistent")
    p = source_dir / "a.txt"
    p.write_text("persistent retrieval price $25")
    result = await engine.collection_add_file("persistent", str(p))
    with engine.connection("persistent") as conn:
        chunk_id = conn.execute("SELECT id FROM chunks").fetchone()[0]
        vectors = db.rows(conn, "SELECT rowid,embedding FROM chunks_vec0")
    await engine.close()
    replacement = Engine(cfg, fake)
    try:
        assert replacement.collection_get_file("persistent", result["source_id"])["status"] == "indexed"
        with replacement.connection("persistent") as conn:
            assert db.rows(conn, "SELECT rowid,embedding FROM chunks_vec0") == vectors
        search = await replacement._query_documents(
            {"collection": "persistent", "query": "retrieval", "mode": "keyword"}
        )
        assert search["results"][0]["chunk_id"] == chunk_id
        assert (
            await replacement._query_documents(
                {"collection": "persistent", "query": "retrieval", "mode": "vector"}
            )
        )["results"]
    finally:
        await replacement.close()


async def test_config_update_rejects_schema_rebuild_flag(engine):
    await engine.collection_create(name="settings")
    with pytest.raises(TypeError):
        engine.collection_config_update("settings", rebuild=True)


async def test_single_file_busy(engine, source_dir, fake):
    await engine.collection_create(name="busy")
    p = source_dir / "a.txt"
    p.write_text("slow embedding")
    fake.entered.clear()
    fake.gate = asyncio.Event()
    task = asyncio.create_task(engine.collection_add_file("busy", str(p)))
    await asyncio.wait_for(fake.entered.wait(), 10)
    with pytest.raises(RagError, match="COLLECTION_BUSY"):
        await engine.collection_add_file("busy", str(p))
    fake.gate.set()
    await task
