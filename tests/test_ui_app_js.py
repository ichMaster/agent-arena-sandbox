"""Integration tests for app.js's lobby actions, WS connection, routeEvent skeleton (ARENA-064).

No headless browser is part of this repo's toolchain (no build step, per architecture.md §8) —
these tests inspect the served source text, consistent with how v01.03 tested served-JS structure.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_the_documented_entry_points() -> None:
    js = _app_js()
    for name in (
        "routeEvent",
        "hostMatch",
        "joinMatch",
        "connectWebSocket",
        "setMatchIdDisplay",
        "setConnectionStatus",
    ):
        assert re.search(rf"\bfunction\s+{name}\b", js), f"{name} not defined"


def test_set_match_id_display_never_truncates() -> None:
    js = _app_js()
    match = re.search(r"function setMatchIdDisplay\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "setMatchIdDisplay body not found"
    body = match.group(1)
    for truncator in ("slice", "substring", "substr"):
        assert truncator not in body, f"{truncator} found in setMatchIdDisplay — must show the full id"


def test_host_match_creates_then_joins_non_spectator() -> None:
    js = _app_js()
    match = re.search(r"async function hostMatch\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "hostMatch body not found"
    body = match.group(1)
    assert "createMatch" in body
    assert "joinLobby" in body
    assert re.search(r"joinLobby\([^,]+,\s*false\)", body), "hostMatch must join as spectator:false"


def test_join_match_threads_spectator_parameter() -> None:
    js = _app_js()
    match = re.search(r"async function joinMatch\(spectator\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "joinMatch body not found"
    body = match.group(1)
    assert re.search(r"joinLobby\([^,]+,\s*spectator\)", body)


def test_route_event_handles_joined_and_stores_symbol() -> None:
    js = _app_js()
    assert "mySymbol = payload.symbol" in js


def test_join_lobby_checks_response_status_before_use() -> None:
    """Regression test for code review #1 (v03.01): a failed join (e.g. an unknown
    match id) must not silently proceed to a doomed WebSocket connection."""
    js = _app_js()
    match = re.search(r"async function joinLobby\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "joinLobby body not found"
    body = match.group(1)
    assert "response.ok" in body
    assert "return null" in body


def test_host_and_join_match_guard_against_a_null_token() -> None:
    js = _app_js()
    for fn_name in ("hostMatch", "joinMatch"):
        match = re.search(
            rf"async function {fn_name}\([^)]*\)\s*\{{(.*?)\n\}}", js, re.DOTALL
        )
        assert match, f"{fn_name} body not found"
        body = match.group(1)
        assert "if (!token) return;" in body
