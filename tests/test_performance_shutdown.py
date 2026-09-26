# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import tomli_w
import yaml
from conftest import finish
from pydantic import ValidationError
from test_knowledge_cards import card

from ragdbman import db
from ragdbman.config import GlobalConfig
from ragdbman.diagnostics import TRACE
from ragdbman.errors import RagError
from ragdbman.extract.process import run
from ragdbman.workers import run_async


def test_wal_normal(tmp_path):
    conn = db.connect(tmp_path / "pragmas.sqlite")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    "settings",
    [
        {"server": {"shutdown_timeout_seconds": 0}},
        {"server": {"shutdown_grace_seconds": 31}},
        {"server": {"shutdown_timeout_seconds": float("inf")}},
        {"defaults": {"max_concurrent_files": 0}},
        {"ollama": {"max_concurrent_embedding_requests": 33}},
    ],
)
def test_invalid_runtime_limits(settings):
    with pytest.raises(ValidationError):
        GlobalConfig(**settings)


@pytest.mark.parametrize("count", [0, 30, 1800])
def test_bulk_keyword_lookup_and_deduplication(count):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE keywords(id TEXT PRIMARY KEY,canonical_form TEXT UNIQUE,display_form TEXT);
        CREATE TABLE chunk_keywords(chunk_id TEXT,keyword_id TEXT,PRIMARY KEY(chunk_id,keyword_id));
    """)
    statements = []
    conn.set_trace_callback(statements.append)
    terms = [f"keyword-{i}" for i in range(count)]
    db.batch_keywords(conn, [("first", terms + terms), ("second", terms)])
    selects = [s for s in statements if s.startswith("SELECT id,canonical_form")]
    assert len(selects) == (count + 799) // 800
    assert conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] == count
    assert conn.execute("SELECT COUNT(*) FROM chunk_keywords").fetchone()[0] == count * 2
    db.batch_keywords(conn, [("third", terms)])
    assert conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] == count
    conn.close()


async def test_connections_reused_with_exclusive_reader_leases(engine):
    await engine.create_collection(name="pool")
    with engine.connection("pool") as first:
        with engine.connection("pool") as second:
            assert first is not second
    with engine.connection("pool") as reused:
        assert reused is first

    def writer_identity():
        with engine.connection("pool") as conn:
            return id(conn), threading.get_ident()

    a = await engine._write("pool", writer_identity)
    b = await engine._write("pool", writer_identity)
    assert a == b and a[1] != threading.get_ident()
    assert a[0] != id(first)
    await engine.close()
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")


async def test_new_reader_connection_does_not_block_behind_writer(engine):
    await engine.create_collection(name="readers")
    entered, release = threading.Event(), threading.Event()

    def writer():
        with engine.connection("readers") as conn, db.transaction(conn):
            conn.execute("UPDATE collection_meta SET description='pending'")
            entered.set()
            assert release.wait(4)

    task = asyncio.create_task(engine._write("readers", writer))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        # Lease the existing cached reader so the next read must open a fresh one.
        with engine.connection("readers"):
            before = time.monotonic()
            result = engine.get_collection("readers")
            assert time.monotonic() - before < 1
            assert result["description"] != "pending"
    finally:
        release.set()
        await task
    assert engine.get_collection("readers")["description"] == "pending"


async def test_bounded_concurrency_and_one_refresh(engine, fake, source_dir, monkeypatch):
    await engine.create_collection(name="parallel", kind="source_code")
    engine.config.defaults.max_concurrent_files = 4
    for n in range(12):
        (source_dir / f"source{n}.py").write_text(f"value = {n}\n# shared keyword vocabulary\n")
    original = fake.embed
    active = peak = 0
    saturated, release = asyncio.Event(), asyncio.Event()

    async def controlled(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 4:
            saturated.set()
        try:
            await release.wait()
            await asyncio.sleep(0.01)
            return await original(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(fake, "embed", controlled)
    refresh = db.refresh_keywords
    calls = []

    def counted(conn):
        calls.append(threading.get_ident())
        refresh(conn)

    monkeypatch.setattr(db, "refresh_keywords", counted)
    job = engine.start_scan("parallel", str(source_dir))
    await asyncio.wait_for(saturated.wait(), 4)
    assert peak == 4
    assert engine.get_collection("parallel")["counts"]["chunks"] == 0
    release.set()
    result = await finish(engine, "parallel", job)
    assert result["status"] == "completed" and result["progress"]["completed"] == 12
    assert result["progress"]["processed"] == result["progress"]["total"] == 12
    assert peak == 4 and active == 0
    assert len(calls) == 1 and calls[0] != threading.get_ident()
    with engine.connection("parallel") as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM keywords WHERE chunk_frequency=0").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 12

    def broken_refresh(conn):
        raise RuntimeError("fixture frequency refresh failure")

    monkeypatch.setattr(db, "refresh_keywords", broken_refresh)
    failed = await finish(engine, "parallel", engine.start_scan("parallel", str(source_dir)))
    assert failed["status"] == "failed"
    assert "Finalization failed" in failed["error_summary"]
    assert not engine.active


async def test_scan_does_not_recount_whole_collection_for_every_file(engine, source_dir, monkeypatch):
    await engine.create_collection(name="metadata", kind="source_code")
    for n in range(16):
        (source_dir / f"{n}.py").write_text(f"number = {n}\n")
    original = engine.get_collection
    calls = []

    def counted(name):
        calls.append(name)
        return original(name)

    monkeypatch.setattr(engine, "get_collection", counted)
    job = await finish(engine, "metadata", engine.start_scan("metadata", str(source_dir)))
    assert job["progress"]["completed"] == 16
    assert len(calls) <= 6


async def test_immediate_cancel_and_close_do_not_leave_queued_jobs(engine, source_dir):
    await engine.create_collection(name="cancel-now")
    (source_dir / "a.txt").write_text("Some text")
    job = engine.start_scan("cancel-now", str(source_dir))
    engine.cancel_job(job["id"])
    result = await finish(engine, "cancel-now", job)
    assert result["status"] == "cancelled"
    assert not engine.active
    job = engine.start_scan("cancel-now", str(source_dir))
    await engine.close()
    assert not engine.active
    assert engine.get_job("cancel-now", job["id"])["status"] == "paused"


async def test_concurrent_duplicate_card_ids_are_atomic(engine, source_dir):
    await engine.create_collection(name="cards", kind="knowledge_cards")
    for n in range(4):
        (source_dir / f"{n}.yaml").write_text(yaml.safe_dump(card()))
    job = await finish(engine, "cards", engine.start_scan("cards", str(source_dir)))
    assert job["progress"]["completed"] == 1 and job["progress"]["failed"] == 3
    with engine.connection("cards") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kc_cards").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM kc_embeddings").fetchone()[0] == 4
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_logging_handlers_do_not_block_debug():
    code = """
import logging
from ragdbman.diagnostics import configure_logging, TRACE, VERBOSE
logging.basicConfig(level=logging.ERROR)
configure_logging('trace')
log=logging.getLogger('ragdbman.fixture')
log.log(TRACE,'trace-event')
log.debug('debug-event')
log.log(VERBOSE,'verbose-event')
log.info('info-event')
log.warning('warning-event')
log.error('error-event')
logging.getLogger('mcp').debug('PRIVATE_MCP_PAYLOAD')
logging.getLogger('httpx').debug('PRIVATE_HTTP_HEADERS')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    for level in ("trace", "debug", "verbose", "info", "warning", "error"):
        assert f"{level}-event" in result.stderr
    assert "PRIVATE_MCP_PAYLOAD" not in result.stderr
    assert "PRIVATE_HTTP_HEADERS" not in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Console watchdog process-exit check")
def test_shutdown_deadline_exits_even_with_noncooperative_thread():
    code = """
import signal, threading, time, uvicorn
from types import SimpleNamespace
from ragdbman.server import ManagedServer
engine=SimpleNamespace(config=SimpleNamespace(server=SimpleNamespace(shutdown_timeout_seconds=.3)),
                       request_shutdown=lambda:None)
server=ManagedServer(uvicorn.Config('unused:app'),engine)
threading.Thread(target=lambda:time.sleep(60)).start()
server.handle_exit(signal.SIGINT,None)
time.sleep(60)
"""
    before = time.monotonic()
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=4)
    assert result.returncode == 130
    assert time.monotonic() - before < 4
    assert "Shutdown deadline reached" in result.stderr


async def test_pipeline_debug_messages_without_payloads(engine, source_dir, caplog):
    caplog.set_level(TRACE, logger="ragdbman")
    await engine.create_collection(name="logs")
    path = source_dir / "paper.txt"
    path.write_text("PRIVATE_DOCUMENT_SENTINEL")
    await engine.add_file("logs", str(path))
    for text in ("Index start", "Extracted", "Chunked", "Keyword batch", "Committed index", "Indexed"):
        assert text in caplog.text
    assert "PRIVATE_DOCUMENT_SENTINEL" not in caplog.text


def alive(pid):
    stat = Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().split(") ", 1)[1][0] not in {"Z", "X"}
    except (FileNotFoundError, ProcessLookupError):
        return False  # procfs can disappear while a killed descendant is reaped.


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX group cleanup verified via procfs")
@pytest.mark.parametrize("cancel", [True, False])
async def test_exited_converter_parent_cannot_leave_pipe_holding_child(tmp_path, cancel):
    marker = tmp_path / "child.pid"
    code = (
        "import subprocess,sys; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"target=Path({str(marker)!r}); temporary=target.with_suffix('.tmp'); "
        "temporary.write_text(str(p.pid)); temporary.replace(target)"
    )
    task = asyncio.create_task(
        run_async(run, sys.executable, ["-c", code], 0.7 if not cancel else 60, tmp_path)
    )
    async with asyncio.timeout(4):
        while not marker.exists():
            await asyncio.sleep(0.01)
    child = int(marker.read_text())
    await asyncio.sleep(0.1)  # The direct parent has exited; its child still owns the pipe.
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 4)
    else:
        with pytest.raises(RagError, match="timed out"):
            await asyncio.wait_for(task, 4)
    assert not alive(child)


@pytest.mark.skipif(sys.platform != "linux", reason="Real console signal and process-group regression")
def test_serve_sigint_exits_with_open_sse_and_converter_descendant(tmp_path):
    class Embed(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"embeddings": [[1.0, 0.0] for _ in data["input"]]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ollama = ThreadingHTTPServer(("127.0.0.1", 0), Embed)
    threading.Thread(target=ollama.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "book.pdf").write_bytes(b"%PDF-1.7 fixture")
    child_file = tmp_path / "child.pid"
    converter = tmp_path / "mineru"
    converter.write_text(
        f"#!{sys.executable}\nimport subprocess,sys\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        f"target=Path({str(child_file)!r})\ntemporary=target.with_suffix('.tmp')\n"
        "temporary.write_text(str(p.pid))\ntemporary.replace(target)\n"
    )
    converter.chmod(0o755)
    config = GlobalConfig(
        server={"port": port, "shutdown_grace_seconds": 1, "shutdown_timeout_seconds": 6},
        storage={
            "data_dir": str(tmp_path / "data"),
            "registry_path": str(tmp_path / "registry.json"),
            "allowed_source_roots": [str(sources)],
        },
        defaults={"allow_approximate_tokenizer": True},
        ollama={"base_url": f"http://127.0.0.1:{ollama.server_port}"},
        media={"pdf_backend": "mineru", "mineru_command": str(converter), "pdf_fallback": False},
    )
    settings = tmp_path / "config.toml"
    settings.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"RAGDBMAN_AUTH_TOKEN", "RAGDBMAN_QUERY_TOKEN", "RAGDBMAN_LOG"}
    }
    log_path = tmp_path / "server.log"
    with log_path.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "ragdbman", "serve", "--config", str(settings), "--log-level", "debug"],
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                deadline = time.monotonic() + 8
                while True:
                    try:
                        if client.get("/api/collections").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline and process.poll() is None, log_path.read_text()
                    time.sleep(0.02)
                assert client.post("/api/collections", json={"name": "signal"}).status_code == 200
                job = client.post("/api/collections/signal/scan", json={"root": str(sources)}).json()
                while not child_file.exists():
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                with client.stream("GET", f"/collections/signal/jobs/{job['id']}/events") as stream:
                    assert next(stream.iter_lines()).startswith("event: progress")
                    start = time.monotonic()
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=5)
                    assert time.monotonic() - start < 5
                    assert process.returncode in (0, -signal.SIGINT, 130)
            assert not alive(int(child_file.read_text()))
            logs = log_path.read_text()
            assert "Shutdown deadline reached" not in logs
            assert "Engine shutdown complete" in logs
            conn = sqlite3.connect(tmp_path / "data/collections/signal/signal.sqlite")
            assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "paused"
            conn.close()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if child_file.exists() and alive(int(child_file.read_text())):
                os.kill(int(child_file.read_text()), signal.SIGKILL)
            ollama.shutdown()
            ollama.server_close()
