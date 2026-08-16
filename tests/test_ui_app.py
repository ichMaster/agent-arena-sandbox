"""app.js -- Host/Join/Observe, WS connect, connection status, routeEvent
skeleton (ARENA-099).

app.js runs in a browser (fetch, WebSocket, DOM) and this repo has no browser
test runner (no build step, per web_ui_specification.md §1) -- so it's verified
two ways: (1) static assertions on the served source for the specific behaviors
the acceptance criteria call out (routeEvent's event coverage, no match-id
truncation, spectator flags), and (2) a real live_server + raw WS client
reproducing the exact REST-then-WS sequence app.js performs for Host, proving
the protocol flow it relies on actually works end to end.
"""

from __future__ import annotations

import json

import httpx
import websockets
from fastapi.testclient import TestClient

from server.main import WEB_DIR, app


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def test_route_event_has_a_case_for_every_server_event() -> None:
    js = _app_js()
    for event in ("joined", "state_update", "chat_message", "game_over", "error"):
        assert f'case "{event}"' in js


def test_route_event_is_exposed() -> None:
    js = _app_js()
    assert "function routeEvent" in js
    assert "window.routeEvent = routeEvent" in js


def test_match_id_is_never_truncated() -> None:
    js = _app_js()
    # No slicing/substring/ellipsis helper is ever applied on the way to display.
    assert ".slice(" not in js
    assert ".substring(" not in js
    assert "…" not in js.split("setMatchIdDisplay")[1].split("}")[0]


def test_host_join_observe_set_spectator_correctly() -> None:
    js = _app_js()
    host_body = js.split("async function host()")[1].split("\n\n")[0]
    join_body = js.split("async function join()")[1].split("\n\n")[0]
    observe_body = js.split("async function observe()")[1].split("\n\n")[0]
    assert "joinMatch(matchId, playerName, false)" in host_body
    assert "joinMatch(matchId, playerName, false)" in join_body
    assert "joinMatch(matchId, playerName, true)" in observe_body


def test_served_app_js_matches_the_file_on_disk() -> None:
    with TestClient(app) as client:
        served = client.get("/ui/app.js").text
    assert served == _app_js()


def test_connect_closes_a_prior_socket_before_opening_a_new_one() -> None:
    """Re-hosting/joining in the same tab (web_ui_specification.md §7) must not
    leak the previous WebSocket -- an abandoned socket the client never closes
    leaves its server-side seat held forever (code review #1, v03.01)."""
    js = _app_js()
    connect_body = js.split("function connect(matchId, token, playerName)")[1].split(
        "\n  function "
    )[0]

    close_index = connect_body.find("state.ws.close()")
    new_ws_index = connect_body.find("new WebSocket(")
    assert close_index != -1, "connect() never closes an existing state.ws"
    assert close_index < new_ws_index, "the prior socket must be closed before the new one opens"


def test_connect_guards_handlers_against_a_stale_socket() -> None:
    """Closing the old socket fires its own close event asynchronously -- every
    handler on the new socket must check it's still the active one, or a stale
    event from the old connection can stomp state set by the new one."""
    js = _app_js()
    connect_body = js.split("function connect(matchId, token, playerName)")[1].split(
        "\n  function "
    )[0]
    for handler in ("open", "close", "error", "message"):
        handler_src = connect_body.split(f'addEventListener("{handler}"')[1].split(");")[0]
        assert "state.ws" in handler_src and "ws" in handler_src


async def test_host_sequence_end_to_end_against_a_real_server(live_server: str) -> None:
    """Reproduces exactly what app.js's host() does: POST /lobby/match, POST
    /lobby/join {spectator:false}, then open the WS and expect `joined` first."""
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Player", "spectator": False},
        )).json()["token"]

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={token}") as ws:
        envelope = json.loads(await ws.recv())
    assert envelope["event"] == "joined"
    assert envelope["payload"]["symbol"] in ("X", "O")


async def test_observe_sequence_yields_a_null_symbol(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
        )).json()["token"]

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={token}") as ws:
        envelope = json.loads(await ws.recv())
    assert envelope["event"] == "joined"
    assert envelope["payload"]["symbol"] is None
