"""submit_move: the full move authority flow, end to end (ARENA-086, architecture.md §5.4).

This is the v01 release gate: two raw WS clients play a full, server-validated game
with chat, to game over.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.main import app


def _create_match(client: TestClient) -> str:
    match_id: str = client.post("/api/v1/lobby/match").json()["match_id"]
    return match_id


def _join(client: TestClient, match_id: str, player_name: str, spectator: bool = False) -> str:
    resp = client.post(
        "/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": player_name, "spectator": spectator},
    )
    token: str = resp.json()["token"]
    return token


def test_full_game_to_a_win_with_chat_then_room_closes() -> None:
    with TestClient(app) as client:
        match_id = _create_match(client)
        token_a = _join(client, match_id, "Alice")
        token_b = _join(client, match_id, "Bob")

        with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
            joined_a = ws_a.receive_json()["payload"]
            with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
                joined_b = ws_b.receive_json()["payload"]

                symbols = {joined_a["symbol"], joined_b["symbol"]}
                assert symbols == {"X", "O"}
                x_ws = ws_a if joined_a["symbol"] == "X" else ws_b
                o_ws = ws_b if x_ws is ws_a else ws_a

                # X wins the top row (0,1,2): X 0, O 3, X 1, O 4, X 2.
                x_ws.send_json({"action": "submit_move", "payload": {"move": 0}})
                update1_x = x_ws.receive_json()
                update1_o = o_ws.receive_json()
                assert update1_x == update1_o
                assert update1_x["event"] == "state_update"
                assert update1_x["payload"]["board"][0] == "X"
                assert update1_x["payload"]["current_turn"] == "O"

                # chat mid-game
                o_ws.send_json({"action": "chat", "payload": {"message": "nice"}})
                chat_x = x_ws.receive_json()
                chat_o = o_ws.receive_json()
                assert chat_x == chat_o == {
                    "event": "chat_message", "payload": {"sender": "Bob", "message": "nice"},
                }

                o_ws.send_json({"action": "submit_move", "payload": {"move": 3}})
                x_ws.receive_json()
                o_ws.receive_json()

                x_ws.send_json({"action": "submit_move", "payload": {"move": 1}})
                x_ws.receive_json()
                o_ws.receive_json()

                o_ws.send_json({"action": "submit_move", "payload": {"move": 4}})
                x_ws.receive_json()
                o_ws.receive_json()

                # winning move
                x_ws.send_json({"action": "submit_move", "payload": {"move": 2}})
                final_update_x = x_ws.receive_json()
                final_update_o = o_ws.receive_json()
                assert final_update_x == final_update_o
                assert final_update_x["payload"]["current_turn"] is None
                assert final_update_x["payload"]["board"][:3] == ["X", "X", "X"]

                game_over_x = x_ws.receive_json()
                game_over_o = o_ws.receive_json()
                assert game_over_x == game_over_o == {
                    "event": "game_over", "payload": {"result": "X"},
                }

                # room is closed: the next receive should see the connection close.
                with pytest.raises(WebSocketDisconnect):
                    x_ws.receive_json()


def test_full_game_to_a_draw() -> None:
    with TestClient(app) as client:
        match_id = _create_match(client)
        token_a = _join(client, match_id, "Alice")
        token_b = _join(client, match_id, "Bob")

        with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
            joined_a = ws_a.receive_json()["payload"]
            with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
                joined_b = ws_b.receive_json()["payload"]
                x_ws = ws_a if joined_a["symbol"] == "X" else ws_b
                o_ws = ws_b if x_ws is ws_a else ws_a

                moves = [
                    (x_ws, 0), (o_ws, 1), (x_ws, 3), (o_ws, 4),
                    (x_ws, 2), (o_ws, 5), (x_ws, 7), (o_ws, 6), (x_ws, 8),
                ]
                last_update = None
                for mover, move in moves:
                    mover.send_json({"action": "submit_move", "payload": {"move": move}})
                    last_update = x_ws.receive_json()
                    o_ws.receive_json()

                assert last_update is not None
                assert last_update["payload"]["current_turn"] is None

                game_over_x = x_ws.receive_json()
                game_over_o = o_ws.receive_json()
                assert game_over_x == game_over_o == {
                    "event": "game_over", "payload": {"result": "draw"},
                }


def test_out_of_turn_move_yields_error_and_state_unchanged() -> None:
    with TestClient(app) as client:
        match_id = _create_match(client)
        token_a = _join(client, match_id, "Alice")
        token_b = _join(client, match_id, "Bob")

        with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
            joined_a = ws_a.receive_json()["payload"]
            with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
                ws_b.receive_json()  # joined
                x_ws = ws_a if joined_a["symbol"] == "X" else ws_b
                o_ws = ws_b if x_ws is ws_a else ws_a

                # O tries to move first -- it's X's turn.
                o_ws.send_json({"action": "submit_move", "payload": {"move": 0}})
                reply = o_ws.receive_json()
                assert reply["event"] == "error"

                # state genuinely unchanged: X can still legally play cell 0.
                x_ws.send_json({"action": "submit_move", "payload": {"move": 0}})
                update = x_ws.receive_json()
                assert update["event"] == "state_update"
                assert update["payload"]["board"][0] == "X"


def test_illegal_move_yields_error_and_state_unchanged() -> None:
    with TestClient(app) as client:
        match_id = _create_match(client)
        token_a = _join(client, match_id, "Alice")
        token_b = _join(client, match_id, "Bob")

        with client.websocket_connect(f"/ws/match/{match_id}?token={token_a}") as ws_a:
            joined_a = ws_a.receive_json()["payload"]
            with client.websocket_connect(f"/ws/match/{match_id}?token={token_b}") as ws_b:
                ws_b.receive_json()  # joined
                x_ws = ws_a if joined_a["symbol"] == "X" else ws_b

                x_ws.send_json({"action": "submit_move", "payload": {"move": 99}})
                reply = x_ws.receive_json()
                assert reply["event"] == "error"

                x_ws.send_json({"action": "submit_move", "payload": {"move": 0}})
                update = x_ws.receive_json()
                assert update["event"] == "state_update"
                assert update["payload"]["board"][0] == "X"


def test_spectator_submit_move_yields_error_and_never_mutates_state() -> None:
    with TestClient(app) as client:
        match_id = _create_match(client)
        spectator_token = _join(client, match_id, "Observer", spectator=True)

        with client.websocket_connect(f"/ws/match/{match_id}?token={spectator_token}") as ws:
            joined = ws.receive_json()["payload"]
            assert joined["symbol"] is None

            ws.send_json({"action": "submit_move", "payload": {"move": 0}})
            reply = ws.receive_json()
            assert reply["event"] == "error"
