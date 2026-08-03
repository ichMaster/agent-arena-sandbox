"""Unit tests for choose_move — decide/validate/retry/fallback (§7.1). LLM mocked; no paid call."""

from unittest.mock import AsyncMock

import pydantic

from agent.agent import MAX_MOVE_ATTEMPTS, choose_move
from agent.memory import MemoryWindow
from agent.schemas import AgentResponse

BOARD = ["X", "", "", "", "O", "", "", "", ""]
VALID = [1, 2, 3, 5, 6, 7, 8]
PERSONA = "You are Ironclaw."


def _llm(*replies: object) -> AsyncMock:
    llm = AsyncMock()
    llm.generate_structured_response = AsyncMock(side_effect=list(replies))
    return llm


async def test_legal_first_try() -> None:
    llm = _llm(AgentResponse(move=5, comment="mine now"))
    move, comment = await choose_move(llm, MemoryWindow(5), BOARD, VALID, PERSONA)
    assert (move, comment) == (5, "mine now")
    assert llm.generate_structured_response.await_count == 1


async def test_illegal_then_legal_retries() -> None:
    llm = _llm(AgentResponse(move=0, comment="oops"), AgentResponse(move=2, comment="fine"))
    move, comment = await choose_move(llm, MemoryWindow(5), BOARD, VALID, PERSONA)
    assert (move, comment) == (2, "fine")
    assert llm.generate_structured_response.await_count == 2
    # The retry prompt carries the rejection feedback, not a blind re-roll.
    retry_prompt = llm.generate_structured_response.await_args_list[1].args[0]
    assert "previous choice 0 was rejected" in retry_prompt


async def test_all_illegal_falls_back_to_legal() -> None:
    llm = _llm(*[AgentResponse(move=0, comment="stubborn")] * MAX_MOVE_ATTEMPTS)
    move, _ = await choose_move(llm, MemoryWindow(5), BOARD, VALID, PERSONA)
    assert move in VALID  # never the illegal 0; never a stall
    assert llm.generate_structured_response.await_count == MAX_MOVE_ATTEMPTS


async def test_model_errors_fall_back_to_legal() -> None:
    def _validation_error() -> pydantic.ValidationError:
        try:
            AgentResponse(move="bad", comment="x")  # type: ignore[arg-type]
        except pydantic.ValidationError as exc:
            return exc
        raise AssertionError

    llm = _llm(_validation_error(), ValueError("no structured output"), RuntimeError("boom"))
    move, _ = await choose_move(llm, MemoryWindow(5), BOARD, VALID, PERSONA)
    assert move in VALID
    assert llm.generate_structured_response.await_count == MAX_MOVE_ATTEMPTS
