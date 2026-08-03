"""Unit tests for build_prompt (ARENA-057, v02.02 release gate)."""

from __future__ import annotations

from agent.memory import MemoryWindow
from agent.profile import AgentProfile
from agent.prompt import build_prompt

_PERSONA = AgentProfile(
    name="Aggressor",
    model_type="haiku",
    system_prompt="You are a swaggering, trash-talking Tic-Tac-Toe player.",
)


def test_prompt_contains_persona_system_prompt() -> None:
    prompt = build_prompt(MemoryWindow(maxlen=10), [None] * 9, list(range(9)), _PERSONA)
    assert _PERSONA.system_prompt in prompt


def test_prompt_reflects_current_board_state() -> None:
    board: list[str | None] = ["X", None, "O", None, None, None, None, None, None]
    prompt = build_prompt(MemoryWindow(maxlen=10), board, [1, 3, 4, 5, 6, 7, 8], _PERSONA)

    assert "X" in prompt
    assert "O" in prompt
    # the empty-cell marker appears too, so the model can tell occupied from empty.
    assert "." in prompt


def test_prompt_lists_valid_moves() -> None:
    valid_moves = [1, 3, 4, 5, 6, 7, 8]
    prompt = build_prompt(MemoryWindow(maxlen=10), [None] * 9, valid_moves, _PERSONA)

    assert str(valid_moves) in prompt


def test_prompt_includes_memory_window_entries() -> None:
    memory = MemoryWindow(maxlen=10)
    memory.record_move("X", 0)
    memory.record_chat("O", "good luck")

    prompt = build_prompt(memory, [None] * 9, list(range(9)), _PERSONA)

    assert "X played 0" in prompt
    assert "O said: good luck" in prompt


def test_prompt_with_empty_memory_omits_history_section() -> None:
    prompt = build_prompt(MemoryWindow(maxlen=10), [None] * 9, list(range(9)), _PERSONA)
    assert "Recent history" not in prompt
