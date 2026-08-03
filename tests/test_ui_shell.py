"""ARENA-029/030/031 -- the static mount, the shell, and app.js.

Served-asset level, consistent with the no-build UI (roadmap §v03.01 Tests).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.main import API_PREFIX, app

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ui.db'}")
    with TestClient(app) as c:
        yield c


# -- ARENA-029: the mount and the no-store rule ----------------------------


def test_the_ui_is_served(client: TestClient) -> None:
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "AgentArena" in response.text


@pytest.mark.parametrize("path", ["/ui/", "/ui/app.js", "/ui/styles.css"])
def test_every_ui_response_is_no_store(client: TestClient, path: str) -> None:
    """Without this a browser serves stale JS and an edit appears to do nothing."""
    assert client.get(path).headers["cache-control"] == "no-store"


def test_non_ui_routes_keep_normal_caching(client: TestClient) -> None:
    """The middleware must not blanket the API."""
    assert "no-store" not in client.get(f"{API_PREFIX}/health").headers.get("cache-control", "")


def test_the_mount_does_not_shadow_the_api_or_ws(client: TestClient) -> None:
    assert client.get(f"{API_PREFIX}/health").status_code == 200
    assert client.post(f"{API_PREFIX}/lobby/match").status_code == 200


# -- ARENA-030: the shell --------------------------------------------------


@pytest.mark.parametrize(
    "element",
    ["id=\"board\"", "id=\"chat-log\"", "id=\"chat-form\"", "id=\"match-id\"",
     "id=\"connection-status\"", "id=\"host-btn\"", "id=\"join-btn\"", "id=\"observe-btn\"",
     "id=\"result-banner\"", "id=\"card-X\"", "id=\"card-O\""],
)
def test_the_shell_carries_its_elements(client: TestClient, element: str) -> None:
    assert element in client.get("/ui/").text


def test_the_board_is_nine_real_buttons(client: TestClient) -> None:
    """Real buttons, so the board is keyboard-reachable."""
    html = client.get("/ui/").text
    assert html.count('class="cell"') == 9
    assert html.count("<button") >= 12


def test_the_page_needs_no_network_to_render(client: TestClient) -> None:
    """No CDN, no external font -- a page that needs the network is not local-first."""
    html = client.get("/ui/").text
    for marker in ("http://", "https://", "//cdn", "googleapis"):
        assert marker not in html, f"external reference: {marker}"


def test_the_stylesheet_is_served(client: TestClient) -> None:
    assert "--bg" in client.get("/ui/styles.css").text


# -- ARENA-031: app.js ------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    ["hostMatch", "promptAndJoin", "spectateMatch", "routeEvent", "setMatchIdDisplay",
     "openSocket", "renderBoard", "handleCellClick", "handleGameOver", "initPlayerCards",
     "renderChat", "resetPlayState"],
)
def test_the_served_js_exposes_the_entry_points(client: TestClient, entry: str) -> None:
    assert entry in client.get("/ui/app.js").text


def test_the_match_id_is_never_truncated(client: TestClient) -> None:
    """It is the string copied into the agent CLI; an ellipsis makes it unusable."""
    js = client.get("/ui/app.js").text
    assert "setMatchIdDisplay" in js
    for truncation in ["slice(0,", "substring(0,", "substr(0,", "…", "..."]:
        assert truncation not in js, f"match id must not be truncated ({truncation})"


def test_route_event_ignores_unknown_events(client: TestClient) -> None:
    js = client.get("/ui/app.js").text
    assert "default:" in js and "routeEvent" in js


def test_exactly_one_socket_is_opened(client: TestClient) -> None:
    js = client.get("/ui/app.js").text
    assert js.count("new WebSocket(") == 1
    assert "if (state.socket) state.socket.close();" in js


def test_a_malformed_frame_does_not_kill_the_connection(client: TestClient) -> None:
    js = client.get("/ui/app.js").text
    assert "JSON.parse(event.data)" in js and "catch" in js


def test_the_ui_holds_no_authoritative_game_state(client: TestClient) -> None:
    """§8: a stateless renderer. The board comes from the server every update."""
    js = client.get("/ui/app.js").text
    assert "function renderBoard(board" in js, "the board must be rendered from the payload"
