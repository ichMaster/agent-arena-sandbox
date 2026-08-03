"""ARENA-017 -- chat, game_over, close_room. **The v01 release gate.**

The last test is the DoD verbatim: two raw WS clients connect to one match, alternate
server-validated legal moves, exchange chat, and reach game_over with the room closed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import select

from server import main
from server.handlers import MAX_CHAT_LENGTH
from server.main import API_PREFIX, app
from server.models import ChatMessage

X_WINS = [(0, "x"), (3, "o"), (1, "x"), (4, "o"), (2, "x")]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cg.db'}")
    with TestClient(app) as client:
        yield client


def _match(client: TestClient) -> str:
    match_id: str = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]
    return match_id


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    token: str = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": match_id, "player_name": name, "spectator": spectator},
    ).json()["token"]
    return token


def _chat(ws: Any, message: Any) -> None:
    ws.send_text(json.dumps({"action": "chat", "payload": {"message": message}}))


def _move(ws: Any, cell: int) -> None:
    ws.send_text(json.dumps({"action": "submit_move", "payload": {"move": cell}}))


def _next(ws: Any) -> dict[str, Any]:
    message: dict[str, Any] = json.loads(ws.receive_text())
    return message


# -- chat ------------------------------------------------------------------


def test_chat_reaches_every_socket_including_the_sender(client: TestClient) -> None:
    match_id = _match(client)
    a, b = _join(client, match_id, "Alice"), _join(client, match_id, "Bob")
    with client.websocket_connect(f"/ws/match/{match_id}?token={a}") as one:
        _next(one)
        with client.websocket_connect(f"/ws/match/{match_id}?token={b}") as two:
            _next(two)
            _chat(one, "good luck")
            mine, theirs = _next(one), _next(two)
    for message in (mine, theirs):
        assert message["event"] == "chat_message"
        assert message["payload"] == {"sender": "Alice", "message": "good luck"}


async def test_chat_is_persisted(client: TestClient) -> None:
    match_id = _match(client)
    token = _join(client, match_id, "Alice")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        _next(ws)
        _chat(ws, "hello")
        _next(ws)

    assert main._session_factory is not None
    async with main._session_factory() as session:
        rows = (
            await session.execute(
                select(ChatMessage).where(ChatMessage.match_id == match_id)
            )
        ).scalars().all()
    assert [(r.sender, r.message) for r in rows] == [("Alice", "hello")]


def test_an_observer_may_chat(client: TestClient) -> None:
    """Chat is non-authoritative flavour -- a silent audience is not the point."""
    match_id = _match(client)
    player = _join(client, match_id, "Alice")
    watcher = _join(client, match_id, "W", spectator=True)
    with client.websocket_connect(f"/ws/match/{match_id}?token={player}") as one:
        _next(one)
        with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as w:
            _next(w)
            _chat(w, "nice move")
            seen = _next(one)
    assert seen["event"] == "chat_message"
    assert seen["payload"]["sender"] == "W"


@pytest.mark.parametrize(
    "message", ["", "   ", "\n\t", None, 42, ["hi"], {"text": "hi"}],
    ids=["empty", "blank", "whitespace", "none", "number", "list", "dict"],
)
def test_a_bad_chat_message_is_refused_without_killing_the_connection(
    client: TestClient, message: Any
) -> None:
    match_id = _match(client)
    token = _join(client, match_id, "Alice")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        _next(ws)
        _chat(ws, message)
        refusal = _next(ws)
        assert refusal["event"] == "error"

        _chat(ws, "still here")     # the connection survives
        assert _next(ws)["event"] == "chat_message"


def test_an_overlong_chat_message_is_refused(client: TestClient) -> None:
    """One client must not be able to broadcast unbounded text to the room."""
    match_id = _match(client)
    token = _join(client, match_id, "Alice")
    with client.websocket_connect(f"/ws/match/{match_id}?token={token}") as ws:
        _next(ws)
        _chat(ws, "x" * (MAX_CHAT_LENGTH + 1))
        assert _next(ws)["event"] == "error"
        _chat(ws, "x" * MAX_CHAT_LENGTH)      # exactly at the limit is fine
        assert _next(ws)["event"] == "chat_message"


# -- game over -------------------------------------------------------------


def test_game_over_arrives_after_the_final_state_update(client: TestClient) -> None:
    """Order matters: the result must never precede the board that produced it."""
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            sockets = {"x": x, "o": o}
            for cell, who in X_WINS:
                _move(sockets[who], cell)
                first, second = _next(x), _next(o)

            assert first["event"] == "state_update"
            assert first["payload"]["current_turn"] is None
            final = _next(x)
            assert final["event"] == "game_over"
            assert final["payload"] == {"result": "X"}


def test_game_over_reaches_observers_too(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    watcher = _join(client, match_id, "W", spectator=True)
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as w:
                _next(w)
                sockets = {"x": x, "o": o}
                for cell, who in X_WINS:
                    _move(sockets[who], cell)
                    _next(x), _next(o), _next(w)
                assert _next(w)["event"] == "game_over"


def test_a_draw_announces_draw(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    drawn = [(0, "x"), (1, "o"), (2, "x"), (4, "o"), (3, "x"),
             (5, "o"), (7, "x"), (6, "o"), (8, "x")]
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            sockets = {"x": x, "o": o}
            for cell, who in drawn:
                _move(sockets[who], cell)
                _next(x), _next(o)
            assert _next(x)["payload"] == {"result": "draw"}


def test_the_room_is_closed_after_game_over(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            sockets = {"x": x, "o": o}
            for cell, who in X_WINS:
                _move(sockets[who], cell)
                _next(x), _next(o)
            _next(x)  # game_over

            assert main.manager.sockets(match_id) == [], "the room must be emptied"
            with pytest.raises(WebSocketDisconnect):
                _next(x)


# -- the v01 release gate --------------------------------------------------


def test_the_v01_release_gate(client: TestClient) -> None:
    """roadmap §v01.04 DoD, verbatim.

    Two raw WS clients connect to one match, alternate server-validated legal moves,
    exchange chat, and reach game_over -- with illegal, out-of-turn and no-seat moves
    rejected, and the terminal state_update reporting current_turn: null.
    """
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    watcher = _join(client, match_id, "W", spectator=True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        assert _next(x)["payload"]["symbol"] == "X"
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            assert _next(o)["payload"]["symbol"] == "O"
            with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as w:
                assert _next(w)["payload"]["symbol"] is None

                # every refusal, before any real move
                _move(o, 0)
                assert _next(o)["payload"]["detail"] == "not your turn"
                _move(w, 0)
                assert "seat" in _next(w)["payload"]["detail"]
                _move(x, 99)
                assert _next(x)["payload"]["detail"] == "invalid move"

                _chat(x, "let's play")
                for socket in (x, o, w):
                    assert _next(socket)["event"] == "chat_message"

                sockets = {"x": x, "o": o}
                for cell, who in X_WINS:
                    _move(sockets[who], cell)
                    update = _next(x)
                    _next(o), _next(w)
                    assert update["event"] == "state_update"

                assert update["payload"]["current_turn"] is None
                assert update["payload"]["board"][:3] == ["X", "X", "X"]

                over = _next(x)
                assert over["event"] == "game_over"
                assert over["payload"]["result"] == "X"
                assert _next(o)["event"] == "game_over"
                assert _next(w)["event"] == "game_over"

                assert main.manager.sockets(match_id) == []
