"""renderBoard -- dynamic cells, marks, playability (ARENA-100,
web_ui_specification.md §4.2, §5).

Static assertions on the served app.js source, consistent with the rest of the
web/ test suite (no browser/JS runner in this repo -- see test_ui_app.py's
module docstring for the rationale).
"""

from __future__ import annotations

from server.main import WEB_DIR


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def _function_body(js: str, signature: str) -> str:
    return js.split(signature)[1].split("\n  function ")[0]


def test_nine_cells_are_created_once_with_stable_ids() -> None:
    js = _app_js()
    ensure_cells = _function_body(js, "function ensureCells()")
    assert "if (cellButtons) return cellButtons" in ensure_cells
    assert "`cell-${i}`" in ensure_cells
    assert "boardEl.appendChild(btn)" in ensure_cells


def test_render_board_computes_is_my_turn_correctly() -> None:
    js = _app_js()
    render_board = _function_body(js, "function renderBoard(")
    # Observers (mySymbol === null) fall out of the same formula, never a
    # separate branch that could diverge from the Player path.
    assert "isGameActive && mySymbol !== null && currentTurn === mySymbol" in render_board


def test_render_board_gates_playable_on_valid_moves() -> None:
    js = _app_js()
    render_board = _function_body(js, "function renderBoard(")
    assert "isMyTurn && validMoves.includes(i)" in render_board


def test_render_board_uses_the_real_disabled_attribute() -> None:
    """Not just a CSS class -- keyboard/AT users must see it as truly
    unavailable (web_ui_specification.md §9)."""
    js = _app_js()
    render_board = _function_body(js, "function renderBoard(")
    assert "cell.disabled = true" in render_board
    assert "cell.disabled = !playable" in render_board


def test_marked_cells_are_never_playable() -> None:
    js = _app_js()
    render_board = _function_body(js, "function renderBoard(")
    marked_branch = render_board.split('mark === "X" || mark === "O"')[1].split("} else {")[0]
    assert "cell.disabled = true" in marked_branch


def test_route_event_wires_render_board_into_joined_and_state_update() -> None:
    js = _app_js()
    joined_case = js.split('case "joined":')[1].split('case "state_update":')[0]
    state_update_case = js.split('case "state_update":')[1].split('case "chat_message":')[0]
    assert "renderBoard(" in joined_case
    assert "renderBoard(" in state_update_case
