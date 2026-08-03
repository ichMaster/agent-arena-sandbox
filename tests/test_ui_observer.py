"""ARENA-034/035 -- chat and the Observer role. **The v03 release gate.**"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.main import API_PREFIX, app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'o.db'}")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def js(client: TestClient) -> str:
    return client.get("/ui/app.js").text


# -- ARENA-034: chat -------------------------------------------------------


def test_the_form_sends_a_chat_action_and_clears_the_input(js: str) -> None:
    assert 'action: "chat"' in js
    assert 'input.value = ""' in js


def test_an_empty_message_is_not_sent(js: str) -> None:
    assert "!input.value.trim()" in js


def test_messages_are_sender_labelled_with_self_distinguished(js: str) -> None:
    assert 'who.textContent = `${payload.sender}:`' in js
    assert "item.dataset.self" in js


def test_the_message_is_inserted_as_text_never_html(js: str) -> None:
    """Chat is attacker-controlled input; innerHTML here would be stored XSS."""
    assert "document.createTextNode(payload.message" in js
    assert "innerHTML" not in js, "chat must never be written as HTML"


def test_the_log_auto_scrolls(js: str) -> None:
    assert "log.scrollTop = log.scrollHeight" in js


# -- ARENA-035: the observer ----------------------------------------------


def test_spectate_is_a_distinct_action_from_join(js: str) -> None:
    assert "function spectateMatch()" in js
    assert "promptAndJoin(true)" in js
    assert "promptAndJoin(false)" in js


def test_host_and_join_are_not_spectators(js: str) -> None:
    """A default that flipped would turn every player into an observer."""
    assert "joinMatch(matchId, false)" in js
    assert "spectator: Boolean(spectator)" in js


def test_an_observer_never_gets_an_enabled_cell(js: str) -> None:
    assert "state.symbol === null" in js


def test_init_player_cards_survives_a_null_symbol(js: str) -> None:
    assert "function initPlayerCards(symbol)" in js


# -- the v03 release gate --------------------------------------------------


def test_the_v03_release_gate(client: TestClient) -> None:
    """roadmap §v03.03 DoD, against the real server.

    An observer watches without claiming a seat, and a forced submit_move is refused
    server-side -- the client's read-only rendering is a courtesy, not the guarantee.
    """
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]

    def join(name: str, spectator: bool) -> str:
        body = {"match_id": match_id, "player_name": name, "spectator": spectator}
        token: str = client.post(f"{API_PREFIX}/lobby/join", json=body).json()["token"]
        return token

    x, o, watcher = join("X", False), join("O", False), join("W", True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={x}") as sx:
        assert json.loads(sx.receive_text())["payload"]["symbol"] == "X"
        with client.websocket_connect(f"/ws/match/{match_id}?token={o}") as so:
            assert json.loads(so.receive_text())["payload"]["symbol"] == "O"
            with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as sw:
                joined = json.loads(sw.receive_text())["payload"]
                assert joined["symbol"] is None, "an observer holds no seat"
                assert joined["seat_available"] is False, "and never wanted one"

                # The board updates live for the observer.
                sx.send_text(json.dumps({"action": "submit_move", "payload": {"move": 4}}))
                json.loads(sx.receive_text()), json.loads(so.receive_text())
                seen = json.loads(sw.receive_text())
                assert seen["event"] == "state_update"
                assert seen["payload"]["board"][4] == "X"

                # A forced move from the observer is refused by the server.
                sw.send_text(json.dumps({"action": "submit_move", "payload": {"move": 0}}))
                refusal = json.loads(sw.receive_text())
                assert refusal["event"] == "error"
                assert "seat" in refusal["payload"]["detail"]

                # Chat reaches the observer live.
                sx.send_text(json.dumps({"action": "chat", "payload": {"message": "watch this"}}))
                json.loads(sx.receive_text()), json.loads(so.receive_text())
                chat = json.loads(sw.receive_text())
                assert chat["event"] == "chat_message"
                assert chat["payload"]["message"] == "watch this"
