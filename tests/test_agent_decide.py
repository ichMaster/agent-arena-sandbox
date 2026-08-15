"""agent/agent.py -- decision flow: retry/fallback, act only on my turn (ARENA-094).

No model call: LLMClient is a scripted fake throughout.
"""

from __future__ import annotations

from agent.agent import MAX_MOVE_ATTEMPTS, AgentSession
from agent.llm import LLMClient
from agent.profile import AgentProfile
from agent.schemas import AgentResponse
from tests.conftest import ScriptedLLMClient


class _FakeWebSocket:
    """Stands in for the live WS connection when a test drives _handle_event
    directly: deciding on-turn sends chat + submit_move over self._ws, which is
    otherwise None until AgentSession.connect() runs."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


def _session(llm_client: LLMClient) -> AgentSession:
    profile = AgentProfile(
        name="Aggressor", model_type="haiku", temperature=0.9,
        system_prompt="You are aggressive.", memory_limit=10,
    )
    return AgentSession(profile, llm_client, "http://x", "m1", "tok1")


async def test_legal_first_response_is_used_without_retrying() -> None:
    llm = ScriptedLLMClient([AgentResponse(move=4, comment="center")])
    session = _session(llm)
    response = await session.decide([None] * 9, list(range(9)))
    assert response.move == 4
    assert llm.calls == 1


async def test_illegal_move_is_retried_then_falls_back_to_a_legal_move() -> None:
    illegal = AgentResponse(move=99, comment="oops")
    llm = ScriptedLLMClient([illegal] * MAX_MOVE_ATTEMPTS)
    session = _session(llm)
    response = await session.decide([None] * 9, [0, 4, 8])
    assert response.move in (0, 4, 8)
    assert llm.calls == MAX_MOVE_ATTEMPTS


async def test_retry_succeeds_before_exhausting_attempts() -> None:
    illegal = AgentResponse(move=99, comment="oops")
    legal = AgentResponse(move=4, comment="center after all")
    llm = ScriptedLLMClient([illegal, legal])
    session = _session(llm)
    response = await session.decide([None] * 9, list(range(9)))
    assert response.move == 4
    assert llm.calls == 2


async def test_decide_is_never_invoked_when_not_my_turn() -> None:
    llm = ScriptedLLMClient([AgentResponse(move=4, comment="center")])
    session = _session(llm)
    session.my_symbol = "X"

    await session._handle_event({
        "event": "state_update",
        "payload": {"board": [None] * 9, "current_turn": "O", "valid_moves": list(range(9))},
    })
    assert llm.calls == 0


async def test_decide_is_never_invoked_on_the_terminal_state_update() -> None:
    llm = ScriptedLLMClient([AgentResponse(move=4, comment="center")])
    session = _session(llm)
    session.my_symbol = "X"

    await session._handle_event({
        "event": "state_update",
        "payload": {"board": ["X"] * 9, "current_turn": None, "valid_moves": []},
    })
    assert llm.calls == 0


async def test_decide_is_invoked_when_it_is_my_turn() -> None:
    llm = ScriptedLLMClient([AgentResponse(move=4, comment="center")])
    session = _session(llm)
    session.my_symbol = "X"
    session._ws = _FakeWebSocket()  # type: ignore[assignment]

    await session._handle_event({
        "event": "state_update",
        "payload": {"board": [None] * 9, "current_turn": "X", "valid_moves": list(range(9))},
    })
    assert llm.calls == 1
