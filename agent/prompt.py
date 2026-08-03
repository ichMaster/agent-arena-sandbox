"""Persona + memory + the pushed board, composed into one prompt (architecture.md §7.2).

The server pushes full turn state (§6.2), so the agent never round-trips to read the
board -- everything the model needs is already in hand when this runs.
"""

from __future__ import annotations

from typing import Any

from agent.memory import MemoryWindow

#: How an empty cell renders. A blank would make the board ambiguous to read.
EMPTY_CELL = "."


def render_board(board: list[Any]) -> str:
    """Three rows of three, so the model sees the geometry rather than a flat list."""
    cells = [EMPTY_CELL if cell is None else str(cell) for cell in board]
    return "\n".join(" ".join(cells[row : row + 3]) for row in range(0, len(cells), 3))


def build_prompt(
    memory: MemoryWindow,
    board: list[Any],
    valid_moves: list[Any],
    persona: str,
) -> str:
    """Compose the turn prompt.

    The legal moves are stated **explicitly**. The agent validates the reply and the
    server re-validates it again, but a model that was never told which cells are free
    is being set up to fail -- so a hallucinated move should mean the model ignored the
    prompt, not that the prompt withheld the answer.

    Deterministic for the same inputs: a prompt that varied per call would make every
    test flaky and defeat prompt caching.
    """
    recent = memory.render()
    history = "\n".join(recent) if recent else "(nothing yet)"
    moves = ", ".join(str(move) for move in valid_moves) if valid_moves else "(none)"

    return (
        f"{persona}\n\n"
        "You are playing Tic-Tac-Toe. Here is the board "
        f"('{EMPTY_CELL}' is an empty cell):\n"
        f"{render_board(board)}\n\n"
        f"Legal moves (cell indices you may play): {moves}\n\n"
        f"Recent events:\n{history}\n\n"
        "Choose exactly one move from the legal moves above, and say something in "
        "character about it."
    )
