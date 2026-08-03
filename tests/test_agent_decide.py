"""Unit tests for decide_move's retry-then-fallback logic (ARENA-060)."""

from __future__ import annotations

import pytest

from agent.agent import MAX_MOVE_ATTEMPTS, AgentSession
from agent.llm import LLMClient
from agent.profile import AgentProfile
from agent.schemas import AgentResponse


class _ScriptedLLMClient(LLMClient):
    def __init__(self, responses: list[AgentResponse]) -> None:
        self._responses = responses
        self.call_count = 0

    async def generate_structured_response(self, prompt: str, schema: type) -> AgentResponse:  # type: ignore[override]
        response = self._responses[self.call_count]
        self.call_count += 1
        return response


def _session(llm_client: LLMClient) -> AgentSession:
    profile = AgentProfile(name="Tester", model_type="haiku", system_prompt="be terse")
    return AgentSession("http://test", "m1", profile, llm_client, player_name="Tester")


@pytest.mark.asyncio
async def test_illegal_then_legal_returns_the_legal_move_after_one_retry() -> None:
    llm = _ScriptedLLMClient(
        [
            AgentResponse(move=99, comment="oops"),  # illegal: out of range
            AgentResponse(move=4, comment="center"),
        ]
    )
    session = _session(llm)

    move, comment = await session.decide_move("prompt", valid_moves=list(range(9)))

    assert (move, comment) == (4, "center")
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_all_illegal_falls_back_to_a_random_legal_move() -> None:
    illegal_responses = [AgentResponse(move=99, comment="oops") for _ in range(MAX_MOVE_ATTEMPTS)]
    llm = _ScriptedLLMClient(illegal_responses)
    session = _session(llm)
    valid_moves = [2, 5, 7]

    move, _comment = await session.decide_move("prompt", valid_moves=valid_moves)

    assert move in valid_moves
    assert llm.call_count == MAX_MOVE_ATTEMPTS


@pytest.mark.asyncio
async def test_first_attempt_legal_returns_immediately_without_retry() -> None:
    llm = _ScriptedLLMClient([AgentResponse(move=0, comment="corner")])
    session = _session(llm)

    move, comment = await session.decide_move("prompt", valid_moves=list(range(9)))

    assert (move, comment) == (0, "corner")
    assert llm.call_count == 1
