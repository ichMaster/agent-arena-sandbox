"""Integration tests for the §5.4 move-authority flow + game_over/close_room (the v01 release gate).
Two real TestClient WS connections against a throwaway DB; no LLM.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/game.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def _join(client: TestClient, match_id: str, name: str, spectator: bool = False) -> str:
    body = {"match_id": match_id, "player_name": name, "spectator": spectator}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def _submit_and_drain(ws_mover: Any, ws_other: Any, move: int) -> tuple[dict[str, Any], dict[str, Any]]:
    ws_mover.send_json({"action": "submit_move", "payload": {"move": move}})
    return ws_mover.receive_json(), ws_other.receive_json()


def test_full_game_x_wins(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        assert ws_x.receive_json()["payload"]["symbol"] == "X"
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            assert ws_o.receive_json()["payload"]["symbol"] == "O"

            su1_x, su1_o = _submit_and_drain(ws_x, ws_o, 0)  # X: top-left
            assert su1_x == su1_o
            assert su1_x["event"] == "state_update"
            assert su1_x["payload"]["board"][0] == "X"
            assert su1_x["payload"]["current_turn"] == "O"
            assert su1_x["payload"]["last_move"] == {"player": "X", "move": 0}

            _submit_and_drain(ws_o, ws_x, 3)  # O: mid-left
            su3_x, su3_o = _submit_and_drain(ws_x, ws_o, 1)  # X: top-mid
            assert su3_x["payload"]["current_turn"] == "O"
            _submit_and_drain(ws_o, ws_x, 4)  # O: center

            terminal_x, terminal_o = _submit_and_drain(ws_x, ws_o, 2)  # X: top-right -> wins
            assert terminal_x == terminal_o
            assert terminal_x["event"] == "state_update"
            assert terminal_x["payload"]["current_turn"] is None  # never invite a move here
            assert terminal_x["payload"]["board"][:3] == ["X", "X", "X"]

            over_x, over_o = ws_x.receive_json(), ws_o.receive_json()
            assert over_x == over_o == {"event": "game_over", "payload": {"result": "X"}}


def test_full_game_draw(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")

    # X: 0,2,3,7,8  O: 1,4,5,6  -> a full board, no line, a genuine draw.
    moves = [("x", 0), ("o", 1), ("x", 2), ("o", 4), ("x", 3), ("o", 5), ("x", 7), ("o", 6), ("x", 8)]

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            ws_o.receive_json()
            sockets = {"x": ws_x, "o": ws_o}
            others = {"x": ws_o, "o": ws_x}

            for who, move in moves[:-1]:
                _submit_and_drain(sockets[who], others[who], move)

            who, move = moves[-1]
            terminal, terminal_other = _submit_and_drain(sockets[who], others[who], move)
            assert terminal["payload"]["current_turn"] is None
            assert "" not in terminal["payload"]["board"]  # the board is full

            over, over_other = sockets[who].receive_json(), others[who].receive_json()
            assert over == over_other == {"event": "game_over", "payload": {"result": "draw"}}


def test_no_moves_accepted_after_game_over(client: TestClient) -> None:
    """The room is closed after game_over -- a further send has nothing listening on the server."""
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            ws_o.receive_json()
            for who_ws, other_ws, move in [(ws_x, ws_o, 0), (ws_o, ws_x, 3), (ws_x, ws_o, 1),
                                            (ws_o, ws_x, 4), (ws_x, ws_o, 2)]:
                _submit_and_drain(who_ws, other_ws, move)
            ws_x.receive_json()  # X's game_over
            ws_o.receive_json()  # O's game_over
        # both `with` blocks exit cleanly even though the server already closed the room.


def test_out_of_turn_move_rejected(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            ws_o.receive_json()
            ws_o.send_json({"action": "submit_move", "payload": {"move": 0}})  # O moves first -- illegal
            response = ws_o.receive_json()
            assert response == {"event": "error", "payload": {"detail": "not your turn"}}


def test_illegal_move_rejected_without_corrupting_state(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            ws_o.receive_json()
            _submit_and_drain(ws_x, ws_o, 4)  # X takes the center

            ws_o.send_json({"action": "submit_move", "payload": {"move": 4}})  # occupied
            response = ws_o.receive_json()
            assert response == {"event": "error", "payload": {"detail": "invalid move"}}

            # State is unchanged -- O can still legally play elsewhere.
            su, _ = _submit_and_drain(ws_o, ws_x, 0)
            assert su["payload"]["board"][4] == "X" and su["payload"]["board"][0] == "O"


def test_no_seat_observer_move_rejected(client: TestClient) -> None:
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_watcher = _join(client, match_id, "Watcher", spectator=True)

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_watcher}") as ws:
        assert ws.receive_json()["payload"]["symbol"] is None
        ws.send_json({"action": "submit_move", "payload": {"move": 0}})
        response = ws.receive_json()
    assert response == {"event": "error", "payload": {"detail": "no seat"}}


def test_third_player_move_rejected(client: TestClient) -> None:
    """Both seats already taken -- a third participant has no seat and can't move."""
    match_id = client.post("/api/v1/lobby/match").json()["match_id"]
    token_x = _join(client, match_id, "Alice")
    token_o = _join(client, match_id, "Bob")
    token_c = _join(client, match_id, "Carol")

    with client.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as ws_x:
        ws_x.receive_json()
        with client.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as ws_o:
            ws_o.receive_json()
            with client.websocket_connect(f"/ws/match/{match_id}?token={token_c}") as ws_c:
                assert ws_c.receive_json()["payload"]["symbol"] is None
                ws_c.send_json({"action": "submit_move", "payload": {"move": 0}})
                response = ws_c.receive_json()
    assert response == {"event": "error", "payload": {"detail": "no seat"}}
