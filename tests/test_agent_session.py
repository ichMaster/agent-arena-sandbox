"""Integration: AgentSession plays a FULL game against the real server (v02 release gate).

The LLM is a scripted mock (incl. one illegal reply → retry) — zero paid calls. Events flow through
a real TestClient WebSocket against the real app + throwaway DB; a scripted opponent (plain WS sends,
no LLM) holds the second seat.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent.agent import AgentSession
from agent.memory import MemoryWindow
from agent.profile import AgentProfile
from agent.schemas import AgentResponse
from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def lobby(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/agent.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as client:
        yield client


def _join(client: TestClient, match_id: str, name: str) -> str:
    return str(
        client.post(
            "/api/v1/lobby/join", json={"match_id": match_id, "player_name": name}
        ).json()["token"]
    )


async def _feed(ws: Any, session: AgentSession, event: dict[str, Any]) -> None:
    for action in await session.on_event(event):
        ws.send_json(action)


async def test_agent_plays_full_game_to_win(lobby: TestClient) -> None:
    match_id = lobby.post("/api/v1/lobby/match").json()["match_id"]
    x_token = _join(lobby, match_id, "Alice-Agent")
    o_token = _join(lobby, match_id, "Bob-Scripted")

    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    llm = AsyncMock()
    # 4 real decisions: open at 0; then an illegal retry (0 is now its own, occupied) before 1;
    # then the winning move at 2 (completing the top row 0,1,2).
    llm.generate_structured_response = AsyncMock(
        side_effect=[
            AgentResponse(move=0, comment="corner? no, center of the action"),
            AgentResponse(move=0, comment="still mine!"),  # illegal: already occupied by itself
            AgentResponse(move=1, comment="fine, right next door"),
            AgentResponse(move=2, comment="top row, all mine"),
        ]
    )
    memory = MemoryWindow(profile.memory_limit)
    session = AgentSession(profile, llm, memory)
    o_moves = iter([3, 4])  # never blocks the top row

    with lobby.websocket_connect(f"/ws/match/{match_id}?token={x_token}") as wx, \
         lobby.websocket_connect(f"/ws/match/{match_id}?token={o_token}") as wo:
        # Drain both joined events before acting -- an early action's broadcast can otherwise race
        # the other connection's own joined (a cross-task ordering hazard, not this test's concern).
        ev_x = wx.receive_json()
        ev_o = wo.receive_json()
        assert ev_x["payload"]["symbol"] == "X"
        assert ev_o["payload"]["symbol"] == "O"

        await _feed(wx, session, ev_x)  # X's turn -> opens with move 0 (chat + submit_move)

        result_event = None
        for _ in range(4):  # at most 4 X-turns needed to reach game_over in this script
            wx.receive_json()  # X's own chat_message echo
            su_x = wx.receive_json()  # state_update after X's move
            wo.receive_json()  # same chat_message, on O's socket
            su_o = wo.receive_json()  # same state_update, on O's socket

            if su_x["payload"]["current_turn"] is None:  # the terminal move -- game over next
                await _feed(wx, session, su_x)  # must NOT act (current_turn is null)
                over_x = wx.receive_json()
                over_o = wo.receive_json()
                await _feed(wx, session, over_x)
                result_event = over_x
                assert over_o == over_x
                break

            await _feed(wx, session, su_x)  # not X's turn (O to move) -> records O's move, no action

            move = next(o_moves)
            wo.send_json({"action": "submit_move", "payload": {"move": move}})
            su2_x = wx.receive_json()  # broadcast of O's move
            wo.receive_json()  # same, on O's own socket

            await _feed(wx, session, su2_x)  # X's turn again -> its next decision

    assert result_event == {"event": "game_over", "payload": {"result": "X"}}
    assert session.finished
    # Exactly 4 model calls -- proof neither the terminal update nor game_over triggered a 5th.
    assert llm.generate_structured_response.await_count == 4
    events = memory.events()
    assert "O played 3" in events and "O played 4" in events  # opponent moves recorded
    assert not any("X played" in e for e in events)  # never double-records its own moves


async def test_session_never_acts_off_turn_or_on_terminal_update() -> None:
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    llm = AsyncMock()
    session = AgentSession(profile, llm, MemoryWindow(5))

    joined = {
        "event": "joined",
        "payload": {"symbol": "O", "board": [""] * 9, "current_turn": "X", "valid_moves": list(range(9))},
    }
    assert await session.on_event(joined) == []  # not my turn
    llm.generate_structured_response.assert_not_awaited()

    terminal = {
        "event": "state_update",
        "payload": {
            "board": ["X"] + [""] * 8,
            "current_turn": None,  # the game just ended
            "valid_moves": [],
            "last_move": {"player": "X", "move": 0},
        },
    }
    assert await session.on_event(terminal) == []
    llm.generate_structured_response.assert_not_awaited()


async def test_observer_symbol_null_never_moves() -> None:
    """A joined with symbol:null (an observer connection) must never call the model."""
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    llm = AsyncMock()
    session = AgentSession(profile, llm, MemoryWindow(5))

    joined = {
        "event": "joined",
        "payload": {"symbol": None, "board": [""] * 9, "current_turn": "X", "valid_moves": list(range(9))},
    }
    assert await session.on_event(joined) == []
    llm.generate_structured_response.assert_not_awaited()


async def test_game_over_sets_finished() -> None:
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    session = AgentSession(profile, AsyncMock(), MemoryWindow(5))
    await session.on_event({"event": "game_over", "payload": {"result": "draw"}})
    assert session.finished is True
