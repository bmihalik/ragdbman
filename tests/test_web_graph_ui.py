# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

import httpx
import pytest

from ragdbman.web import create_app


@pytest.mark.parametrize("route", ["/corpus-graph", "/collections/code/corpus-graph"])
async def test_graph_ui_routes_and_auth(engine, route, monkeypatch):
    monkeypatch.setenv("RAGDBMAN_AUTH_TOKEN", "ui-admin-test")
    monkeypatch.setenv("RAGDBMAN_QUERY_TOKEN", "ui-query-test")
    app = create_app(engine, False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
        denied = await client.get(route, headers={"Authorization": "Bearer ui-query-test"})
        assert denied.status_code == 401
        allowed = await client.get(route, headers={"Authorization": "Bearer ui-admin-test"})
        assert allowed.status_code == 200
        assert 'href="/corpus-graph"' in allowed.text
