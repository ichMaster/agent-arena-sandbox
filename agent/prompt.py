"""build_prompt — persona + memory + pushed state, composed into one prompt (architecture.md §7.2).

No I/O here: every input is a parameter, since the server pushes full turn state and the
agent never round-trips to read it.
"""

from __future__ import annotations

from agent.memory import MemoryWindow
from agent.profile import AgentProfile


def _render_board(board: list[str | None]) -> str:
    cells = [cell if cell is not None else "." for cell in board]
    rows = [cells[i : i + 3] for i in range(0, 9, 3)]
    return "\n".join(" ".join(row) for row in rows)


def build_prompt(
    memory: MemoryWindow,
    board: list[str | None],
    valid_moves: list[int],
    persona: AgentProfile,
) -> str:
    lines = [
        persona.system_prompt,
        "",
        "Current board:",
        _render_board(board),
        "",
        f"Valid moves: {valid_moves}",
    ]

    entries = memory.entries()
    if entries:
        lines.append("")
        lines.append("Recent history:")
        for entry in entries:
            if entry["type"] == "move":
                lines.append(f"- {entry['player']} played {entry['move']}")
            else:
                lines.append(f"- {entry['sender']} said: {entry['message']}")

    return "\n".join(lines)
