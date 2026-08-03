"""Integration tests for the served app.js wiring (ARENA-OPUS-SONNET-027). Served-asset level; no
LLM. The no-build UI is validated by GETting the asset and asserting its entry points and wire
contract — consistent with the vanilla-JS, no-transpile design.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/ui.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def test_app_js_served(client: TestClient) -> None:
    resp = client.get("/ui/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert resp.headers.get("cache-control") == "no-store"


def test_app_js_exposes_entry_points(client: TestClient) -> None:
    js = client.get("/ui/app.js").text
    for fn in ("hostMatch", "joinMatch", "spectateMatch", "routeEvent", "setMatchIdDisplay"):
        assert fn in js
    assert "window.arena" in js


def test_app_js_uses_real_wire_contract(client: TestClient) -> None:
    js = client.get("/ui/app.js").text
    for ev in ("joined", "state_update", "chat_message", "game_over", "error"):
        assert ev in js
    assert "/api/v1/lobby/match" in js
    assert "/api/v1/lobby/join" in js
    assert "/ws/match/" in js
    assert "payload.symbol" in js
    assert "isGameActive = true" in js and "isGameActive = false" in js


def test_app_js_never_truncates_match_id(client: TestClient) -> None:
    """The match id is copied into the agent CLI verbatim — any truncation would 404 it (§4.1)."""
    js = client.get("/ui/app.js").text
    assert "slice(" not in js
    assert "substring" not in js
    assert "substr(" not in js
