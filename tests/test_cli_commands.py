# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import argparse
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

from ragdbman.cli import main, parser
from ragdbman.cli_commands import COMMANDS, contract, emit, endpoint, numeric, remote, table, wait_job
from ragdbman.errors import RagError
from ragdbman.process_lock import DataDirectoryLock

CASES = [
    ("health-status", []),
    ("list-collections", []),
    ("get-collection", ["--name", "docs"]),
    ("create-collection", ["--name", "docs", "--kind", "knowledge_cards"]),
    ("update-collection-config", ["--name", "docs", "--description", "new"]),
    ("delete-collection", ["--name", "docs", "--confirm"]),
    ("list-source-roots", ["--collection", "docs"]),
    ("add-source-root", ["--collection", "docs", "--path", "/data"]),
    ("remove-source-root", ["--collection", "docs", "--root-id", "root"]),
    ("start-scan", ["--collection", "docs", "--root", "/data"]),
    ("add-file", ["--collection", "docs", "--path", "/data/a"]),
    ("remove-source", ["--collection", "docs", "--source-id", "source", "--confirm"]),
    ("get-job", ["--collection", "docs", "--job-id", "job"]),
    ("list-jobs", ["--collection", "docs"]),
    ("cancel-job", ["--job-id", "job"]),
    ("resume-job", ["--collection", "docs", "--job-id", "job"]),
    ("search", ["--collection", "docs", "--query", "text"]),
    ("search-multi", ["--collections", "docs,code", "--query", "text"]),
    ("list-sources", ["--collection", "docs"]),
    ("get-source", ["--collection", "docs", "--source-id", "source"]),
    ("list-keywords", ["--collection", "docs"]),
    ("list-metadata-fields", ["--collection", "docs"]),
    ("export-collection-manifest", ["--collection", "docs"]),
    ("rebuild-collection", ["--collection", "docs", "--confirm"]),
    ("vacuum-collection", ["--collection", "docs"]),
    ("graph", ["--collection", "docs", "--action", "find"]),
    ("search-knowledge-cards", ["--collection", "docs", "--query", "text"]),
]


@pytest.mark.parametrize("command,options", CASES)
def test_contracts_and_routes(command, options):
    args = parser().parse_args(["--config", "/tmp/custom", "--log-level", "debug", command, *options])
    assert args.config == "/tmp/custom" and args.log_level == "debug"
    assert args.format == "json"
    method, kwargs = contract(args)
    assert method == command.replace("-", "_")
    verb, path, params, body = endpoint(args, kwargs)
    assert verb in {"GET", "POST", "PATCH", "DELETE"} and path.startswith("/api/")
    if "request" in kwargs:
        assert body == kwargs["request"].model_dump(by_alias=True)
    assert set(COMMANDS) == {item[0] for item in CASES}


@pytest.mark.parametrize(
    "options",
    [
        ["delete-collection", "--name", "docs"],
        ["remove-source", "--collection", "docs", "--source-id", "s"],
        ["rebuild-collection", "--collection", "docs"],
        ["start-scan", "--collection", "docs", "--root", "/data", "--prune-missing"],
    ],
)
def test_confirmation_before_engine_creation(options, cfg, tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(cfg.model_dump(exclude_none=True)))
    with pytest.raises(SystemExit) as exc:
        main([*options, "--config", str(path)])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().err)["code"] == "CONFIRMATION_REQUIRED"
    assert not Path(cfg.storage.data_dir).exists()


def test_filter_mapping_and_global_overrides():
    args = parser().parse_args(
        [
            "--config",
            "/first",
            "search",
            "--collection",
            "docs",
            "--query",
            "",
            "--mode",
            "structured",
            "--extensions",
            ".pdf,md",
            "--keywords",
            "fee, cost",
            "--source-ids",
            "one,two",
            "--path-prefix",
            "/data",
            "--no-text",
            "--no-links",
            "--numeric",
            "amount greater_than 1000",
            "--numeric",
            "date between 2024-01-01 2024-12-31",
            "--numeric",
            "amount exists",
            "--no-graph-context",
            "--format",
            "llm",
            "--config",
            "/second",
        ]
    )
    assert args.config == "/second"
    req = contract(args)[1]["request"]
    assert req.format == "llm" and req.include_graph_context is False
    assert not req.include_text and not req.include_links
    assert req.filters.source_extensions == [".pdf", "md"]
    assert req.filters.numeric[1].from_ == "2024-01-01"
    assert req.filters.numeric[2].op == "exists"


@pytest.mark.parametrize(
    "text",
    [
        "amount",
        "amount equals 1",
        "amount exists 1",
        "date between 2024",
        "amount greater_than 1 2",
        '"unterminated',
    ],
)
def test_bad_numeric_filters(text):
    with pytest.raises(argparse.ArgumentTypeError):
        numeric(text)


@pytest.mark.parametrize(
    "options",
    [
        ["search", "--collection", "docs"],
        ["list-jobs", "--collection", "docs", "--status", "bogus"],
        ["list-sources", "--collection", "docs", "--offset", "-1"],
        ["search", "--collection", "../x", "--query", "a"],
        ["search-multi", "--collections", "a,,b", "--query", "a"],
        ["list-jobs", "--collection", "docs", "--limit", "0"],
        ["list-collections", "--server-url", ""],
        ["get-source", "--collection", "docs", "--source-id", ""],
    ],
)
def test_argument_errors(options):
    with pytest.raises(SystemExit) as exc:
        parser().parse_args(options)
    assert exc.value.code == 2


def test_lock_contention_and_release(cfg):
    with DataDirectoryLock(cfg):
        with pytest.raises(RagError, match="DATA_DIRECTORY_BUSY"):
            with DataDirectoryLock(cfg):
                pass
    with DataDirectoryLock(cfg):
        pass


def test_tables_empty_diagnostics_and_escaped_controls():
    assert table("list-jobs", []) == "(no rows)"
    result = table(
        "search-multi",
        {
            "results": [{"source_filename": "bad\n\x1b[31m", "score": 0.5, "text": "long" * 80}],
            "collections_failed": [{"collection": "missing", "reason": "not found"}],
            "skipped_filters": [{"field": "bad", "reason": "unknown"}],
        },
    )
    assert "\\n" in result and "\x1b" not in result and "collections_failed" in result
    assert "skipped_filters" in result and "..." in result


def test_manifest_output_refuses_overwrite(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    args = parser().parse_args(["export-collection-manifest", "--collection", "docs", "--output", str(path)])
    emit(args, {"value": "árvíz"})
    assert json.loads(path.read_text()) == {"value": "árvíz"} and not capsys.readouterr().out
    with pytest.raises(FileExistsError):
        emit(args, {"value": "changed"})
    assert json.loads(path.read_text())["value"] == "árvíz"


async def test_watch_json_lines_and_poll_interval(monkeypatch, capsys):
    args = parser().parse_args(["get-job", "--collection", "docs", "--job-id", "j", "--watch"])
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    records = iter([dict(id="j", status="running"), dict(id="j", status="paused")])

    async def getter(job_id):
        assert job_id == "j"
        return next(records)

    result = await wait_job(args, getter, dict(id="j", status="queued"), watch=True)
    emit(args, result, snapshot=True)
    assert sleeps == [2, 2]
    assert [json.loads(line)["status"] for line in capsys.readouterr().out.splitlines()] == [
        "queued",
        "running",
        "paused",
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://u:secret@example.com",
        "https://example.com?token=secret",
        "file:///tmp/x",
    ],
)
async def test_remote_refuses_unsafe_url(url):
    args = parser().parse_args(["list-collections", "--server-url", url])
    with pytest.raises(RagError, match="CONFIG_INVALID"):
        await remote(args, {})


async def test_remote_transport_no_local_fallback(monkeypatch, tmp_path):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer test-admin-token"
        return httpx.Response(403, json={"code": "PATH_NOT_ALLOWED", "message": "denied"})

    original = httpx.AsyncClient
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "test-admin-token")
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    args = parser().parse_args(["list-collections", "--server-url", "http://127.0.0.1:8765"])
    with pytest.raises(RagError, match="PATH_NOT_ALLOWED"):
        await remote(args, {})


def test_connection_failure_never_constructs_engine(monkeypatch, cfg, tmp_path, capsys):
    async def handler(request):
        raise httpx.ConnectError("offline")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    path = tmp_path / "remote.toml"
    path.write_text(tomli_w.dumps(cfg.model_dump(exclude_none=True)))
    with pytest.raises(SystemExit) as exc:
        main(["list-collections", "--config", str(path), "--server-url", "http://127.0.0.1:8765"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert not captured.out and "DAEMON_UNAVAILABLE" in captured.err
    assert not Path(cfg.storage.data_dir).exists() and not Path(cfg.storage.registry_path).exists()


@pytest.fixture
def cli_env(cfg, source_dir, tmp_path):
    state = {"delay": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(state["delay"])
            texts = data.get("input", [])
            if isinstance(texts, str):
                texts = [texts]
            payload = json.dumps({"embeddings": [[1.0, 0.0, 0.0, 0.0] for _ in texts]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    cfg.ollama.base_url = f"http://127.0.0.1:{server.server_port}"
    cfg.storage.markdown_sidecar_enabled = False
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        cfg.server.port = sock.getsockname()[1]
    path = tmp_path / "cli.toml"
    path.write_text(tomli_w.dumps(cfg.model_dump(exclude_none=True)))
    env = {**os.environ, "RAGDBMAN_AUTH_TOKEN": "", "RAGDBMAN_QUERY_TOKEN": ""}
    prefix = [sys.executable, "-m", "ragdbman", "--config", str(path)]

    def run(*args, code=0):
        result = subprocess.run(
            [*prefix, *args], cwd="/tmp", env=env, text=True, capture_output=True, timeout=45
        )
        assert result.returncode == code, (args, result.stdout, result.stderr)
        return result

    yield cfg, source_dir, run, prefix, env, state
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)


def test_real_cli_collection_scan_search_and_maintenance(cli_env, tmp_path):
    cfg, root, run, prefix, env, state = cli_env
    (root / "a.py").write_text("def parse_config():\n    return 1\n")
    assert json.loads(run("health-status").stdout)["ollama_reachable"]
    created = json.loads(
        run(
            "create-collection", "--name", "code", "--kind", "source_code", "--source-roots", str(root)
        ).stdout
    )
    assert created["kind"] == "source_code"
    job = json.loads(run("start-scan", "--collection", "code", "--root", str(root)).stdout)
    assert job["status"] == "completed" and job["progress"]["completed"] == 1
    assert (
        json.loads(run("get-job", "--collection", "code", "--job-id", job["id"]).stdout)["status"]
        == "completed"
    )
    cancelled = run("cancel-job", "--job-id", job["id"], code=1)
    assert "CONFIG_INVALID" in cancelled.stderr
    assert (
        json.loads(run("get-job", "--collection", "code", "--job-id", job["id"]).stdout)["status"]
        == "completed"
    )
    assert json.loads(run("list-jobs", "--collection", "code", "--status", "completed").stdout)
    assert "source_code" in run("list-collections", "--format", "table").stdout
    result = json.loads(
        run("search", "--collection", "code", "--query", "parse_config", "--mode", "keyword").stdout
    )
    assert result["results"][0]["graph_context"]["available"]
    llm = run(
        "search", "--collection", "code", "--query", "parse_config", "--mode", "keyword", "--format", "llm"
    )
    assert "function:" in llm.stdout
    assert json.loads(
        run("graph", "--collection", "code", "--action", "find", "--symbol", "parse_config").stdout
    )["candidates"]
    mixed = json.loads(
        run(
            "search-multi", "--collections", "code,missing", "--query", "parse_config", "--mode", "keyword"
        ).stdout
    )
    assert mixed["collections_searched"] == ["code"] and mixed["collections_failed"]
    run("search-multi", "--collections", "missing", "--query", "anything", "--mode", "keyword", code=3)
    sources = json.loads(run("list-sources", "--collection", "code", "--extension", ".py").stdout)
    assert len(sources) == 1
    assert (
        json.loads(run("get-source", "--collection", "code", "--source-id", sources[0]["id"]).stdout)[
            "status"
        ]
        == "indexed"
    )
    assert json.loads(run("list-keywords", "--collection", "code").stdout)
    assert json.loads(run("list-metadata-fields", "--collection", "code").stdout)
    manifest = tmp_path / "manifest.json"
    run("export-collection-manifest", "--collection", "code", "--output", str(manifest))
    assert json.loads(manifest.read_text())["sources"][0]["id"] == sources[0]["id"]
    assert (
        json.loads(run("rebuild-collection", "--collection", "code", "--confirm").stdout)["status"]
        == "completed"
    )
    run("vacuum-collection", "--collection", "code")
    run("remove-source", "--collection", "code", "--source-id", sources[0]["id"], "--confirm")
    assert (root / "a.py").exists()
    run("delete-collection", "--name", "code", "--confirm")
    assert json.loads(run("list-collections").stdout) == []


@pytest.mark.skipif(sys.platform != "linux", reason="console signal integration checked on Linux")
def test_foreground_scan_signal_cleanup_and_resume(cli_env):
    cfg, root, run, prefix, env, state = cli_env
    (root / "a.txt").write_text("queue example")
    run("create-collection", "--name", "docs")
    state["delay"] = 3
    proc = subprocess.Popen(
        [*prefix, "start-scan", "--collection", "docs", "--root", str(root)],
        cwd="/tmp",
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    dbpath = Path(cfg.storage.data_dir) / "collections/docs/docs.sqlite"
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with sqlite3.connect(dbpath) as conn:
                row = conn.execute("SELECT id,status FROM jobs LIMIT 1").fetchone()
            if row and row[1] == "running":
                break
            time.sleep(0.05)
        else:
            pytest.fail("CLI scan did not start")
        busy = run("list-collections", code=1)
        assert "DATA_DIRECTORY_BUSY" in busy.stderr
        proc.send_signal(signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 130, (stdout, stderr)
        state["delay"] = 0
        job = json.loads(run("get-job", "--collection", "docs", "--job-id", row[0], code=3).stdout)
        assert job["status"] == "paused"
        resumed = json.loads(run("resume-job", "--collection", "docs", "--job-id", row[0]).stdout)
        assert resumed["status"] == "completed"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="Daemon process control uses POSIX signals")
def test_daemon_commands_watch_cancel_and_ownership(cli_env):
    cfg, root, run, prefix, env, state = cli_env
    env["RAGDBMAN_AUTH_TOKEN"] = "daemon-admin-test-token"
    server = subprocess.Popen(
        [*prefix, "serve"], cwd="/tmp", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    url = f"http://127.0.0.1:{cfg.server.port}"
    try:
        deadline = time.monotonic() + 12
        with httpx.Client(
            timeout=1, headers={"Authorization": "Bearer " + env["RAGDBMAN_AUTH_TOKEN"]}
        ) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get(url + "/api/collections").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("daemon did not start")
        assert "DATA_DIRECTORY_BUSY" in run("list-collections", code=1).stderr
        run("create-collection", "--name", "docs", "--server-url", url)
        (root / "a.txt").write_text("queue")
        state["delay"] = 3
        job = json.loads(
            run("start-scan", "--collection", "docs", "--root", str(root), "--server-url", url).stdout
        )
        assert job["status"] == "queued"
        run("cancel-job", "--job-id", job["id"], "--server-url", url)
        watched = run(
            "get-job", "--collection", "docs", "--job-id", job["id"], "--watch", "--server-url", url, code=3
        )
        assert json.loads(watched.stdout.splitlines()[-1])["status"] == "cancelled"
        assert env["RAGDBMAN_AUTH_TOKEN"] not in watched.stdout + watched.stderr
        state["delay"] = 0
        resumed = json.loads(
            run(
                "resume-job", "--collection", "docs", "--job-id", job["id"], "--server-url", url, "--wait"
            ).stdout
        )
        assert resumed["status"] == "completed"
        llm = run(
            "search",
            "--collection",
            "docs",
            "--query",
            "queue",
            "--mode",
            "keyword",
            "--format",
            "llm",
            "--server-url",
            url,
        )
        assert "Document excerpt" in llm.stdout
    finally:
        server.send_signal(signal.SIGINT)
        server.wait(timeout=15)
    assert json.loads(run("list-collections").stdout)[0]["name"] == "docs"
