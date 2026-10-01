# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Actual MCP discovery and stateless teardown, not just local tool-manager lists."""

import logging
import tomllib
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import requires
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.server.streamable_http import StreamableHTTPServerTransport
from packaging.requirements import Requirement

from ragdbman.engine import Engine
from ragdbman.web import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def wire(cfg, fake, source_dir, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "cap-admin-test")
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", "cap-query-test")
    cfg.server.mcp_admin_enabled = True
    engine = Engine(cfg, fake)
    with TestClient(create_app(engine)) as client:
        yield client


def post(client, profile, method, params=None, identifier=1):
    return client.post(
        f"/mcp/{profile}",
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer cap-" + profile + "-test",
        },
        json={
            "jsonrpc": "2.0",
            "id": identifier,
            "method": method,
            **({"params": params} if params is not None else {}),
        },
    )


@pytest.mark.parametrize("profile,count", [("query", 3), ("admin", 6)])
def test_initialize_advertises_only_used_capabilities(wire, profile, count):
    response = post(
        wire,
        profile,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "capability-aware-client", "version": "1"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["result"]
    assert body["serverInfo"]["name"] == "ragdbman"
    assert "tools" in body["capabilities"]
    assert "prompts" not in body["capabilities"]
    assert "resources" not in body["capabilities"]
    assert "mcp-session-id" not in response.headers
    tools = post(wire, profile, "tools/list").json()["result"]["tools"]
    assert len(tools) == count
    assert all(t["name"].startswith("corpus_") for t in tools)
    assert not {t["name"] for t in tools} & {"list_prompts", "get_prompt", "list_resources", "read_resource"}
    described = post(wire, profile, "tools/call", {"name": "corpus_describe", "arguments": {}})
    assert not described.json()["result"].get("isError"), described.text


@pytest.mark.parametrize("profile", ["query", "admin"])
@pytest.mark.parametrize(
    "method,params",
    [
        ("prompts/list", {}),
        ("prompts/get", {"name": "unused"}),
        ("resources/list", {}),
        ("resources/templates/list", {}),
        ("resources/read", {"uri": "file:///must-not-be-read"}),
        ("resources/subscribe", {"uri": "file:///must-not-be-read"}),
        ("resources/unsubscribe", {"uri": "file:///must-not-be-read"}),
    ],
)
def test_unused_operations_are_unsupported_on_wire(wire, profile, method, params):
    response = post(wire, profile, method, params)
    assert response.status_code == 200, response.text
    assert response.json()["error"]["code"] == -32601, response.text
    assert "result" not in response.json()


@pytest.mark.parametrize("profile", ["query", "admin"])
def test_repeated_and_concurrent_stateless_pings(wire, profile, caplog):
    caplog.set_level(logging.DEBUG, logger="mcp.server.streamable_http")
    for identifier in range(10):
        result = post(wire, profile, "ping", identifier=identifier)
        assert result.status_code == 200
        assert result.json() == {"jsonrpc": "2.0", "id": identifier, "result": {}}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda identifier: post(wire, profile, "ping", identifier=identifier), range(10, 30))
        )
    assert all(r.status_code == 200 and r.json()["result"] == {} for r in results)
    assert all("mcp-session-id" not in r.headers for r in results)
    assert not [r for r in caplog.records if r.name.startswith("mcp.server") and r.levelno >= logging.ERROR]
    assert len(post(wire, profile, "tools/list").json()["result"]["tools"]) == (
        3 if profile == "query" else 6
    )


async def test_expected_terminated_stream_closure_is_not_an_error(caplog):
    caplog.set_level(logging.DEBUG, logger="mcp.server.streamable_http")
    transport = StreamableHTTPServerTransport(mcp_session_id=None, is_json_response_enabled=True)
    async with transport.connect():
        # Close before the scheduled router starts receiving: the reported race.
        await transport.terminate()
    assert any(r.getMessage() == "Read stream closed by client" for r in caplog.records)
    assert not [
        r for r in caplog.records if r.name == "mcp.server.streamable_http" and r.levelno >= logging.ERROR
    ]


async def test_unexpected_stream_closure_remains_visible(caplog):
    caplog.set_level(logging.DEBUG, logger="mcp.server.streamable_http")
    transport = StreamableHTTPServerTransport(mcp_session_id=None, is_json_response_enabled=True)
    async with transport.connect():
        # Intentionally inject a real unexpected closure without terminating.
        await transport._write_stream_reader.aclose()
    errors = [
        r for r in caplog.records if r.name == "mcp.server.streamable_http" and r.levelno >= logging.ERROR
    ]
    assert errors and "Unexpected closure" in errors[0].getMessage()
    assert isinstance(errors[0].exc_info[1], anyio.ClosedResourceError)


def test_dependency_floor_and_lock_are_consistent():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "mcp>=1.30.0,<2" in project["dependencies"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    sdk = next(p for p in lock["package"] if p["name"] == "mcp")
    assert sdk["version"] == "1.30.0"


def test_installed_package_requires_supported_sdk():
    dependencies = [Requirement(value) for value in requires("ragdbman")]
    sdk = next(value for value in dependencies if value.name == "mcp")
    assert sdk.specifier.contains("1.30.0")
    assert not sdk.specifier.contains("1.29.99")
    assert not sdk.specifier.contains("2.0.0")


@pytest.mark.parametrize("profile", ["query", "admin"])
def test_tools_list_declares_all_four_boolean_hints(wire, profile):
    readonly_names = {"corpus_describe", "corpus_query", "corpus_graph"}
    mutation_names = {"corpus_manage", "corpus_ingest", "corpus_job"}
    response = post(wire, profile, "tools/list")
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == (
        readonly_names | mutation_names if profile == "admin" else readonly_names
    )
    for tool in tools:
        readonly = tool["name"] in readonly_names
        expected = {
            "readOnlyHint": readonly,
            "destructiveHint": not readonly,
            "idempotentHint": readonly,
            "openWorldHint": False,
        }
        annotations = tool["annotations"]
        for key, value in expected.items():
            assert key in annotations, (tool["name"], annotations)
            assert type(annotations[key]) is bool, (tool["name"], key, annotations)
            assert annotations[key] is value, (tool["name"], key, annotations)
