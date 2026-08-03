"""ARENA-016 -- the §5.4 move-authority flow over real WebSockets.

The server is the ultimate authority: these tests are mostly about what a *lying* or
*mistaken* client cannot make it do.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server import main
from server.main import API_PREFIX, app
from server.models import Match, Move


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'mv.db'}")
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


def _send(ws: Any, move: Any, **extra: Any) -> None:
    ws.send_text(json.dumps({"action": "submit_move", "payload": {"move": move, **extra}}))


def _next(ws: Any) -> dict[str, Any]:
    message: dict[str, Any] = json.loads(ws.receive_text())
    return message


# -- a full game -----------------------------------------------------------


def test_two_clients_play_a_full_game_to_a_win(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")

    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        assert _next(x)["payload"]["symbol"] == "X"
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            assert _next(o)["payload"]["symbol"] == "O"

            # X: 0,1,2   O: 3,4  -> X wins on the top row
            for sender, receiver, cell in [
                (x, o, 0), (o, x, 3), (x, o, 1), (o, x, 4), (x, o, 2),
            ]:
                _send(sender, cell)
                update = _next(sender)
                assert update["event"] == "state_update"
                assert _next(receiver)["event"] == "state_update", "both sockets get it"

            final = update["payload"]
            assert final["board"][:3] == ["X", "X", "X"]
            assert final["current_turn"] is None, "§6.2: null on the game-ending move"
            assert final["valid_moves"] == []
            assert final["last_move"] == {"player": "X", "move": 2}


def test_a_drawn_game_reports_no_turn_at_the_end(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    # X O X / X O O / O X X  -- a full board with no line
    order = [(0, "x"), (1, "o"), (2, "x"), (4, "o"), (3, "x"),
             (5, "o"), (7, "x"), (6, "o"), (8, "x")]

    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            sockets = {"x": x, "o": o}
            for cell, who in order:
                _send(sockets[who], cell)
                update = _next(sockets[who])
                _next(sockets["o" if who == "x" else "x"])
            assert update["payload"]["current_turn"] is None
            assert update["payload"]["board"].count(None) == 0


# -- refusals --------------------------------------------------------------


def test_an_out_of_turn_move_is_refused(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            _send(o, 0)  # X moves first
            message = _next(o)
    assert message["event"] == "error"
    assert "turn" in message["payload"]["detail"]


def test_a_client_cannot_claim_another_symbol(client: TestClient) -> None:
    """The symbol comes from the token, never from the message.

    O sends a move claiming to be X. If the server trusted the payload it would accept
    it, because it *is* X's turn.
    """
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            _send(o, 0, symbol="X", player="X")
            message = _next(o)
    assert message["event"] == "error"
    assert "turn" in message["payload"]["detail"]


def test_an_observer_cannot_move(client: TestClient) -> None:
    match_id = _match(client)
    x_token = _join(client, match_id, "X")
    watcher = _join(client, match_id, "W", spectator=True)
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as w:
            _next(w)
            _send(w, 4)
            message = _next(w)
    assert message["event"] == "error"
    assert "seat" in message["payload"]["detail"]


def test_a_player_at_a_full_match_cannot_move(client: TestClient) -> None:
    match_id = _match(client)
    a, b = _join(client, match_id, "A"), _join(client, match_id, "B")
    late = _join(client, match_id, "C")
    with client.websocket_connect(f"/ws/match/{match_id}?token={a}") as one:
        _next(one)
        with client.websocket_connect(f"/ws/match/{match_id}?token={b}") as two:
            _next(two)
            with client.websocket_connect(f"/ws/match/{match_id}?token={late}") as three:
                _next(three)
                _send(three, 4)
                message = _next(three)
    assert message["event"] == "error"
    assert "seat" in message["payload"]["detail"]


@pytest.mark.parametrize(
    "move", [-1, 9, 100, "4", None, 4.0, True, [4], {"cell": 4}],
    ids=["negative", "past-end", "far", "string", "none", "float", "bool", "list", "dict"],
)
def test_an_illegal_move_is_refused(client: TestClient, move: Any) -> None:
    match_id = _match(client)
    x_token = _join(client, match_id, "X")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        _send(x, move)
        message = _next(x)
    assert message["event"] == "error"
    assert message["payload"]["detail"] == "invalid move"


def test_an_occupied_cell_is_refused(client: TestClient) -> None:
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            _send(x, 4)
            _next(x), _next(o)
            _send(o, 4)
            message = _next(o)
    assert message["event"] == "error"
    assert message["payload"]["detail"] == "invalid move"


async def test_a_refused_move_writes_nothing(client: TestClient) -> None:
    """A rejection must leave no trace, or replay would rebuild a board nobody played."""
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            _send(o, 0)     # out of turn
            _next(o)
            _send(x, 99)    # illegal
            _next(x)

            assert main._session_factory is not None
            async with main._session_factory() as session:
                moves = (
                    await session.execute(select(Move).where(Move.match_id == match_id))
                ).scalars().all()
            assert moves == []

            _send(x, 0)     # the next legal move still works
            assert _next(x)["event"] == "state_update"


def test_a_move_into_a_finished_match_is_refused(client: TestClient) -> None:
    """Reached by reconnecting, since ARENA-017 closes the room the moment it ends.

    The original form of this test sent a move on the same socket after game_over.
    That is no longer reachable -- close_room is a stronger guarantee than a refusal --
    so the check moved to the path a client can still take: coming back to a match that
    is already decided.
    """
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            for sender, cell in [(x, 0), (o, 3), (x, 1), (o, 4), (x, 2)]:
                _send(sender, cell)
                _next(x), _next(o)
            _next(x)  # game_over

    with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
        joined = _next(o)
        assert joined["payload"]["current_turn"] is None
        _send(o, 5)
        message = _next(o)
    assert message["event"] == "error"
    assert message["payload"]["detail"] == "this game is over"


# -- persistence -----------------------------------------------------------


async def test_the_match_is_marked_finished_with_its_result(client: TestClient) -> None:
    """§5.4 step 4 -- the move and the result land in the same transaction."""
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            for sender, cell in [(x, 0), (o, 3), (x, 1), (o, 4), (x, 2)]:
                _send(sender, cell)
                _next(x), _next(o)

    assert main._session_factory is not None
    async with main._session_factory() as session:
        match = (
            await session.execute(select(Match).where(Match.match_id == match_id))
        ).scalar_one()
        moves = (
            await session.execute(select(Move).where(Move.match_id == match_id))
        ).scalars().all()
    assert (match.status, match.result) == ("finished", "X")
    assert len(moves) == 5


def test_an_observer_sees_every_move(client: TestClient) -> None:
    """The demo's whole point: a seat-less client watches the game live."""
    match_id = _match(client)
    x_token, o_token = _join(client, match_id, "X"), _join(client, match_id, "O")
    watcher = _join(client, match_id, "W", spectator=True)
    with client.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as x:
        _next(x)
        with client.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as o:
            _next(o)
            with client.websocket_connect(f"/ws/match/{match_id}?token={watcher}") as w:
                _next(w)
                _send(x, 4)
                _next(x), _next(o)
                seen = _next(w)
    assert seen["event"] == "state_update"
    assert seen["payload"]["board"][4] == "X"
