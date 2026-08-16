"""Observer role hardening: chat suppression + the v03 release-gate checks
(ARENA-104, web_ui_specification.md §4.3-4.4, §5; roadmap.md §v03.03 DoD).
"""

from __future__ import annotations

import json

import httpx
import websockets

from agent.agent import join_match
from server.main import WEB_DIR


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def _function_body(js: str, signature: str) -> str:
    return js.split(signature)[1].split("\n  function ")[0]


# ---- Client-side: chat suppressed by role, not just connection state ----


def test_update_chat_enabled_requires_a_symbol_not_just_an_open_socket() -> None:
    js = _app_js()
    body = _function_body(js, "function updateChatEnabled()")
    assert "state.mySymbol !== null" in body
    assert "WebSocket.OPEN" in body


def test_set_connected_no_longer_gates_chat_on_connection_alone() -> None:
    """The pre-ARENA-104 shape (chatInput.disabled = !connected) would enable
    chat for an Observer the instant the socket opens -- setConnected must
    delegate to the role-aware gate instead."""
    js = _app_js()
    body = _function_body(js, "function setConnected(connected)")
    assert "updateChatEnabled()" in body
    assert "chatInput.disabled = !connected" not in body


def test_joined_rechecks_chat_enablement_once_the_role_is_known() -> None:
    js = _app_js()
    joined_case = js.split('case "joined":')[1].split('case "state_update":')[0]
    assert "updateChatEnabled()" in joined_case


def test_reset_clears_my_symbol_before_the_new_socket_opens() -> None:
    """Without this, a same-tab re-host could briefly gate chat on the
    *previous* match's role instead of defaulting to disabled."""
    js = _app_js()
    body = _function_body(js, "function resetBoardAndCards()")
    assert "state.mySymbol = null" in body


# ---- Client-side: restating the v03.02 Observer guarantees at this phase's level ----


def test_observer_is_excluded_from_is_my_turn() -> None:
    js = _app_js()
    body = _function_body(js, "function renderBoard(")
    assert "mySymbol !== null" in body


def test_init_player_cards_null_branch_never_derefs_my_symbol() -> None:
    js = _app_js()
    body = _function_body(js, "function initPlayerCards(mySymbol)")
    assert "mySymbol.toLowerCase" not in body
    assert "mySymbol.toUpperCase" not in body


# ---- Client-side: Observe is a genuinely distinct action from Host/Join ----


def test_only_observe_sends_spectator_true() -> None:
    js = _app_js()
    host_body = js.split("async function host()")[1].split("\n\n")[0]
    join_body = js.split("async function join()")[1].split("\n\n")[0]
    observe_body = js.split("async function observe()")[1].split("\n\n")[0]
    assert "joinMatch(matchId, playerName, false)" in host_body
    assert "joinMatch(matchId, playerName, false)" in join_body
    assert "joinMatch(matchId, playerName, true)" in observe_body


# ---- Server-side, real connection: the actual release-gate line ----


async def test_a_spectators_submit_move_is_refused_server_side(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        spectator_token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
        )).json()["token"]

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={spectator_token}") as ws:
        joined = json.loads(await ws.recv())
        assert joined["payload"]["symbol"] is None

        await ws.send(json.dumps({"action": "submit_move", "payload": {"move": 0}}))
        reply = json.loads(await ws.recv())
        assert reply["event"] == "error"
        assert reply["payload"]["detail"] == "no seat"


async def test_observe_join_yields_a_null_symbol_and_no_seat(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
        )).json()["token"]

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={token}") as ws:
        joined = json.loads(await ws.recv())
    assert joined["payload"]["symbol"] is None


async def test_host_and_join_still_default_to_non_spectator(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = await join_match(live_server, match_id, "Alice", client)

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={token}") as ws:
        joined = json.loads(await ws.recv())
    assert joined["payload"]["symbol"] in ("X", "O")
