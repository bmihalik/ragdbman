# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Hold real indexing stages open while exercising the overview HTTP routes."""

import asyncio
import os
import sys
import threading
import time

import httpx
import pytest
from conftest import finish, text_pdf

from ragdbman import db
from ragdbman.errors import RagError
from ragdbman.extract.process import run
from ragdbman.web import create_app
from ragdbman.workers import run_async, run_sync


@pytest.mark.parametrize("stage", ["text", "pdf", "chunk", "write"])
async def test_overview_and_cancel_respond_during_indexing(engine, source_dir, monkeypatch, stage):
    await engine.create_collection(name="busy")
    entered, release = threading.Event(), threading.Event()
    owner = threading.get_ident()
    worker_threads = []

    def pause(original):
        def held(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            entered.set()
            if not release.wait(8):
                raise RuntimeError("Test gate timed out: indexing blocked the server")
            return original(*args, **kwargs)

        return held

    if stage == "pdf":
        from pypdf import PdfReader

        text_pdf(source_dir / "paper.pdf", ["Scientific retrieval reference."])
        monkeypatch.setattr(PdfReader, "_initialize_stream", pause(PdfReader._initialize_stream))
    else:
        (source_dir / "paper.txt").write_text("Scientific retrieval reference. Price: EUR 25.")
        if stage == "text":
            import ragdbman.extract as extraction

            monkeypatch.setattr(extraction, "plain", pause(extraction.plain))
        elif stage == "chunk":
            import ragdbman.engine as engine_module

            monkeypatch.setattr(engine_module, "chunk_document", pause(engine_module.chunk_document))
        else:
            # Pause with the write transaction open, not just before it starts.
            monkeypatch.setattr(db, "refresh_keywords", pause(db.refresh_keywords))

    app = create_app(engine, manage_engine=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://testserver") as client:
        response = await client.post("/api/collections/busy/scan", json={"root": str(source_dir)})
        assert response.status_code == 200
        job = response.json()
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            # This also rejects false positives where a blocked loop only resumes
            # after the timeout gate has already expired.
            assert worker_threads and owner not in worker_threads
            assert not engine.tasks[job["id"]].done()
            before = time.monotonic()
            for url in [
                "/",
                "/static/app.js",
                "/api/collections",
                "/api/collections/busy",
                f"/api/collections/busy/jobs/{job['id']}",
            ]:
                response = await asyncio.wait_for(client.get(url), 1)
                assert response.status_code == 200
            assert time.monotonic() - before < 2
            cancelled = await asyncio.wait_for(client.post(f"/api/jobs/{job['id']}/cancel"), 1)
            assert cancelled.status_code == 200
            with pytest.raises(RagError, match="COLLECTION_BUSY"):
                engine.delete_collection("busy", confirm=True)
        finally:
            release.set()
            result = await finish(engine, "busy", job)
        assert result["status"] == "cancelled"
        with engine.connection("busy") as conn:
            assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM chunks_vec0").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 0


async def test_cancelled_sync_worker_is_drained_before_return():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    stop = threading.Event()

    def worker():
        entered.set()
        release.wait(5)
        finished.set()

    task = asyncio.create_task(run_sync(worker, on_cancel=stop.set))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()  # Repeated cancellation must not abandon the worker.
    await asyncio.sleep(0)
    assert stop.is_set() and not task.done() and not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


async def test_async_converter_cancellation_runs_cleanup():
    entered, cleaned = threading.Event(), threading.Event()

    async def converter():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    task = asyncio.create_task(run_async(converter))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert cleaned.is_set()


async def test_shutdown_during_write_rolls_back_before_unlock(engine, source_dir, monkeypatch):
    await engine.create_collection(name="closing")
    path = source_dir / "paper.txt"
    path.write_text("Original indexed evidence.")
    result = await engine.add_file("closing", str(path))
    with engine.connection("closing") as conn:
        original = db.rows(conn, "SELECT id,text FROM chunks")
    path.write_text("Replacement evidence. Price: EUR 25.")
    entered, release = threading.Event(), threading.Event()
    refresh = db.refresh_keywords

    def held(conn):
        entered.set()
        assert release.wait(5)
        refresh(conn)

    monkeypatch.setattr(db, "refresh_keywords", held)
    job = engine.start_scan("closing", str(source_dir))
    assert await asyncio.to_thread(entered.wait, 3)
    shutdown = asyncio.create_task(engine.close())
    try:
        await asyncio.sleep(0.05)
        assert not shutdown.done()
        assert "closing" in engine.active
        with pytest.raises(RagError, match="COLLECTION_BUSY"):
            engine.delete_collection("closing", confirm=True)
    finally:
        release.set()
        await asyncio.wait_for(shutdown, 3)
    assert engine.get_job("closing", job["id"])["status"] == "paused"
    with engine.connection("closing") as conn:
        assert db.rows(conn, "SELECT id,text FROM chunks") == original
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM source_versions WHERE source_id=?", (result["source_id"],)
            ).fetchone()[0]
            == 1
        )


async def test_health_probe_is_bounded_when_embedder_is_busy(engine, fake):
    fake.gate = asyncio.Event()
    before = time.monotonic()
    response = await asyncio.wait_for(engine.health_status(), 4)
    assert time.monotonic() - before < 4
    assert response["daemon_ok"] is True
    assert response["ollama_reachable"] is False
    assert "timed out" in response["message"]


async def test_pruning_keeps_overview_responsive_and_cancel_rolls_back(engine, source_dir, monkeypatch):
    await engine.create_collection(name="pruning")
    path = source_dir / "paper.txt"
    path.write_text("Persistent evidence.")
    job = engine.start_scan("pruning", str(source_dir))
    assert (await finish(engine, "pruning", job))["status"] == "completed"
    source = engine.list_sources("pruning")[0]
    path.unlink()
    entered, release = threading.Event(), threading.Event()
    refresh = db.refresh_keywords
    owner = threading.get_ident()
    threads = []

    def held(conn):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(8)
        refresh(conn)

    monkeypatch.setattr(db, "refresh_keywords", held)
    job = engine.start_scan("pruning", str(source_dir), prune_missing=True)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert owner not in threads
        app = create_app(engine, manage_engine=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://testserver"
        ) as client:
            response = await asyncio.wait_for(client.get("/api/collections"), 1)
            assert response.status_code == 200
            assert response.json()[0]["counts"]["chunks"] > 0
            assert (await client.post(f"/api/jobs/{job['id']}/cancel")).status_code == 200
    finally:
        release.set()
        result = await finish(engine, "pruning", job)
    assert result["status"] == "cancelled"
    assert engine.get_source("pruning", source["id"])["status"] == "indexed"
    assert engine.get_collection("pruning")["counts"]["chunks"] > 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX process termination check")
async def test_worker_converter_subprocess_is_reaped_on_cancel(tmp_path):
    marker = tmp_path / "pid.txt"
    code = "import os,time; from pathlib import Path; Path('pid.txt').write_text(str(os.getpid())); time.sleep(60)"
    task = asyncio.create_task(run_async(run, sys.executable, ["-c", code], 60, tmp_path))
    try:
        async with asyncio.timeout(5):
            while not marker.exists():
                await asyncio.sleep(0.01)
        pid = int(marker.read_text())
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_worker_exceptions_propagate():
    def broken():
        raise ValueError("worker failure")

    async def broken_async():
        raise ValueError("converter failure")

    with pytest.raises(ValueError, match="worker failure"):
        await run_sync(broken)
    with pytest.raises(ValueError, match="converter failure"):
        await run_async(broken_async)


async def test_worker_preserves_dependency_log_context():
    import logging

    from ragdbman.diagnostics import DependencySummary, dependency_counts

    async def converter():
        record = logging.LogRecord("pypdf", logging.WARNING, "", 0, "fixture warning", (), None)
        assert not DependencySummary().filter(record)

    with dependency_counts() as counts:
        await run_async(converter)
    assert counts == [1, 0]
