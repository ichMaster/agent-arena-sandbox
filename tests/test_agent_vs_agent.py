"""Agent-vs-agent end-to-end over the real server (ARENA-OPUS-036, roadmap §v05.02) -- the v04
headline scenario, as an automated integration test. Two real `AgentSession`s (Ironclaw vs Bastion,
both LLMs scripted-mocked) play a full game to `game_over` over real WS connections. Zero paid calls.
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
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/agent_vs_agent.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as client:
        yield client


def _join(client: TestClient, match_id: str, name: str) -> str:
    body = {"match_id": match_id, "player_name": name}
    return str(client.post("/api/v1/lobby/join", json=body).json()["token"])


def _mock_llm(*replies: AgentResponse) -> AsyncMock:
    llm = AsyncMock()
    llm.generate_structured_response = AsyncMock(side_effect=list(replies))
    return llm


async def _feed_both(
    ws_x: Any, ws_o: Any, session_x: AgentSession, session_o: AgentSession, event: dict[str, Any]
) -> None:
    """Deliver one server broadcast to both sessions in lock-step; each acts only on its own turn
    (AgentSession.on_event is a no-op unless current_turn matches its own symbol)."""
    for action in await session_x.on_event(event):
        ws_x.send_json(action)
    for action in await session_o.on_event(event):
        ws_o.send_json(action)


async def test_agent_vs_agent_plays_to_game_over(lobby: TestClient) -> None:
    match_id = lobby.post("/api/v1/lobby/match").json()["match_id"]
    profile_x = AgentProfile.load_from_yaml("profiles/aggressive.yml")  # Ironclaw
    profile_o = AgentProfile.load_from_yaml("profiles/cautious.yml")  # Bastion
    token_x = _join(lobby, match_id, profile_x.name)
    token_o = _join(lobby, match_id, profile_o.name)

    llm_x = _mock_llm(
        AgentResponse(move=0, comment="center of the storm"),
        AgentResponse(move=1, comment="pressing on"),
        AgentResponse(move=2, comment="top row, all mine"),
    )
    llm_o = _mock_llm(
        AgentResponse(move=3, comment="holding the line"),
        AgentResponse(move=4, comment="steady as she goes"),
    )
    memory_x = MemoryWindow(profile_x.memory_limit)
    memory_o = MemoryWindow(profile_o.memory_limit)
    session_x = AgentSession(profile_x, llm_x, memory_x)
    session_o = AgentSession(profile_o, llm_o, memory_o)

    with lobby.websocket_connect(f"/ws/match/{match_id}?token={token_x}") as wx, \
         lobby.websocket_connect(f"/ws/match/{match_id}?token={token_o}") as wo:
        ev_x = wx.receive_json()
        ev_o = wo.receive_json()
        assert ev_x["payload"]["symbol"] == "X"
        assert ev_o["payload"]["symbol"] == "O"

        # X is first to move -- its own joined event triggers its opening move.
        for action in await session_x.on_event(ev_x):
            wx.send_json(action)
        assert await session_o.on_event(ev_o) == []  # not O's turn yet

        # Drive event-by-event (not paired) since the final round broadcasts three events --
        # chat, the terminal state_update, then game_over -- one more than every earlier round.
        result_event: dict[str, Any] | None = None
        for _ in range(20):  # generous upper bound; the real driver is the game_over break below
            event_x = wx.receive_json()
            event_o = wo.receive_json()
            assert event_x == event_o  # the same broadcast, delivered to both sockets
            await _feed_both(wx, wo, session_x, session_o, event_x)
            if event_x["event"] == "game_over":
                result_event = event_x
                break

    assert result_event == {"event": "game_over", "payload": {"result": "X"}}
    assert session_x.finished and session_o.finished

    # Each side acted only on its own turn -- LLM call counts match the script exactly (no action
    # on the terminal state_update, whose current_turn is null).
    assert llm_x.generate_structured_response.await_count == 3
    assert llm_o.generate_structured_response.await_count == 2

    # Opponent moves/chat were recorded in each side's memory (never its own).
    events_x = memory_x.events()
    assert "O played 3" in events_x and "O played 4" in events_x
    assert not any("X played" in e for e in events_x)
    events_o = memory_o.events()
    assert "X played 0" in events_o and "X played 1" in events_o and "X played 2" in events_o
    assert not any("O played" in e for e in events_o)
