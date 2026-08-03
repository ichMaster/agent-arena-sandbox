"""Unit tests for AgentSession's event dispatch (ARENA-059)."""

from __future__ import annotations

from typing import Any

import pytest

from agent.agent import AgentSession
from agent.llm import LLMClient
from agent.profile import AgentProfile
from agent.schemas import AgentResponse


class _ExplodingLLMClient(LLMClient):
    """Used where the test asserts decide_move/_take_turn is never reached."""

    async def generate_structured_response(self, prompt: str, schema: type) -> object:  # type: ignore[override]
        raise AssertionError("decide_move should not have been called — not my turn")


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


def _session(symbol: str | None) -> AgentSession:
    profile = AgentProfile(name="Tester", model_type="haiku", system_prompt="be terse")
    session = AgentSession(
        "http://test", "m1", profile, _ExplodingLLMClient(), player_name="Tester"
    )
    session.symbol = symbol
    return session


def _state_update(current_turn: str | None, last_move: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "event": "state_update",
        "payload": {
            "board": [None] * 9,
            "current_turn": current_turn,
            "valid_moves": list(range(9)),
            "last_move": last_move,
        },
    }


@pytest.mark.asyncio
async def test_not_my_turn_does_not_take_turn() -> None:
    session = _session(symbol="X")
    ws = _FakeWS()

    await session._handle_event(ws, _state_update("O", {"player": "O", "move": 4}))  # type: ignore[arg-type]

    assert ws.sent == []


@pytest.mark.asyncio
async def test_terminal_state_update_does_not_take_turn_even_with_matching_symbol() -> None:
    session = _session(symbol="X")
    ws = _FakeWS()

    await session._handle_event(ws, _state_update(None, {"player": "X", "move": 8}))  # type: ignore[arg-type]

    assert ws.sent == []


@pytest.mark.asyncio
async def test_opponent_move_recorded_own_echoed_move_is_not() -> None:
    session = _session(symbol="X")
    ws = _FakeWS()

    # current_turn stays "O" (not my turn) in both events, isolating the memory-recording
    # path from _take_turn (covered separately in test_my_turn_sends_chat_then_submit_move).
    await session._handle_event(ws, _state_update("O", {"player": "O", "move": 3}))  # type: ignore[arg-type]
    assert session.memory.entries() == [{"type": "move", "player": "O", "move": 3}]

    # own move echoed back by the server's broadcast must not be recorded a second time.
    await session._handle_event(ws, _state_update("O", {"player": "X", "move": 0}))  # type: ignore[arg-type]
    assert session.memory.entries() == [{"type": "move", "player": "O", "move": 3}]
    assert ws.sent == []


@pytest.mark.asyncio
async def test_opponent_chat_recorded_own_echoed_chat_is_not() -> None:
    session = _session(symbol="X")
    ws = _FakeWS()

    await session._handle_event(
        ws, {"event": "chat_message", "payload": {"sender": "Opponent", "message": "hi"}}
    )
    assert session.memory.entries() == [{"type": "chat", "sender": "Opponent", "message": "hi"}]

    await session._handle_event(
        ws, {"event": "chat_message", "payload": {"sender": "Tester", "message": "yo"}}
    )
    assert session.memory.entries() == [{"type": "chat", "sender": "Opponent", "message": "hi"}]


@pytest.mark.asyncio
async def test_my_turn_sends_chat_then_submit_move() -> None:
    profile = AgentProfile(name="Tester", model_type="haiku", system_prompt="be terse")

    class _StubLLMClient(LLMClient):
        async def generate_structured_response(self, prompt: str, schema: type) -> AgentResponse:  # type: ignore[override]
            return AgentResponse(move=4, comment="center!")

    session = AgentSession(
        "http://test", "m1", profile, _StubLLMClient(), player_name="Tester"
    )
    session.symbol = "X"
    ws = _FakeWS()

    await session._handle_event(ws, _state_update("X", None))  # type: ignore[arg-type]

    assert len(ws.sent) == 2
    assert '"action": "chat"' in ws.sent[0]
    assert '"action": "submit_move"' in ws.sent[1]
    assert session.memory.entries() == [{"type": "move", "player": "X", "move": 4}]
