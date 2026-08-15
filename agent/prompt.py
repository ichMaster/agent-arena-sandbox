"""build_prompt -- persona + memory + pushed board/valid-moves, composed into one
prompt (architecture.md §7.2).

The server pushes full turn state (v01.04), so this is the agent's only source of
truth for a turn -- it never round-trips to read state.
"""

from __future__ import annotations

from typing import Any

from agent.memory import MemoryWindow
from agent.profile import AgentProfile


def _format_board(board: list[Any]) -> str:
    cells = [str(cell) if cell is not None else "_" for cell in board]
    rows = [cells[i : i + 3] for i in range(0, len(cells), 3)]
    return "\n".join(" ".join(row) for row in rows)


def _format_memory(memory: MemoryWindow) -> str:
    events = memory.events()
    if not events:
        return "(no recent history)"
    lines = []
    for event in events:
        if event.kind == "move":
            lines.append(f"- {event.sender} played {event.content}")
        else:
            lines.append(f'- {event.sender} said: "{event.content}"')
    return "\n".join(lines)


def build_prompt(
    memory: MemoryWindow, board: list[Any], valid_moves: list[Any], persona: AgentProfile
) -> str:
    return (
        f"{persona.system_prompt}\n\n"
        f"Current board (numbered 0-8, left to right, top to bottom):\n"
        f"{_format_board(board)}\n\n"
        f"Valid moves: {valid_moves}\n\n"
        f"Recent history:\n{_format_memory(memory)}\n\n"
        f"Choose your move from the valid moves above and give a short in-character comment."
    )
