"""handleCellClick -> submit_move; game_over freeze + win-line highlight
(ARENA-101, web_ui_specification.md §4.1-4.2, §6.1, §6.3).

Static assertions on the served app.js source (see test_ui_app.py's module
docstring for why: no browser/JS runner in this repo).
"""

from __future__ import annotations

from server.main import WEB_DIR


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def _function_body(js: str, signature: str) -> str:
    return js.split(signature)[1].split("\n  function ")[0]


def test_handle_cell_click_guards_a_closed_or_missing_socket() -> None:
    js = _app_js()
    body = _function_body(js, "function handleCellClick(index)")
    assert "state.ws.readyState !== WebSocket.OPEN" in body


def test_handle_cell_click_guards_an_inactive_game() -> None:
    js = _app_js()
    body = _function_body(js, "function handleCellClick(index)")
    assert "!state.isGameActive" in body


def test_handle_cell_click_guards_a_disabled_cell() -> None:
    js = _app_js()
    body = _function_body(js, "function handleCellClick(index)")
    assert "cell.disabled" in body


def test_handle_cell_click_sends_submit_move_with_the_index() -> None:
    js = _app_js()
    body = _function_body(js, "function handleCellClick(index)")
    assert 'action: "submit_move"' in body
    assert "move: index" in body


def test_handle_cell_click_never_touches_the_dom_directly() -> None:
    """No optimistic update -- only a real state_update may change what's
    rendered (web_ui_specification.md §8 interaction flows)."""
    js = _app_js()
    body = _function_body(js, "function handleCellClick(index)")
    assert "textContent" not in body
    assert "className" not in body


def test_cell_click_listeners_are_bound_once_at_creation() -> None:
    js = _app_js()
    ensure_cells = _function_body(js, "function ensureCells()")
    assert "handleCellClick(i)" in ensure_cells


def test_game_over_freezes_every_cell() -> None:
    js = _app_js()
    freeze = _function_body(js, "function freezeBoard()")
    assert "cell.disabled = true" in freeze
    game_over_case = js.split('case "game_over":')[1].split('case "error":')[0]
    assert "freezeBoard()" in game_over_case


def test_game_over_sets_the_status_label_to_the_result() -> None:
    js = _app_js()
    game_over_case = js.split('case "game_over":')[1].split('case "error":')[0]
    assert "statusLabel.textContent" in game_over_case
    assert "payload.result" in game_over_case


def test_game_over_highlights_the_winning_line_only_for_x_or_o() -> None:
    js = _app_js()
    game_over_case = js.split('case "game_over":')[1].split('case "error":')[0]
    assert 'payload.result === "X" || payload.result === "O"' in game_over_case
    assert "computeWinningLine" in game_over_case
    assert 'classList.add("win")' in game_over_case


def test_compute_winning_line_checks_all_eight_lines() -> None:
    js = _app_js()
    body = _function_body(js, "function computeWinningLine(board, result)")
    assert "WIN_LINES" in body
    win_lines_decl = js.split("WIN_LINES = [")[1].split("];")[0]
    # Three rows, three columns, two diagonals -- all eight winning lines.
    assert win_lines_decl.count("[") == 8


def test_error_case_surfaces_detail_and_keeps_the_connection_open() -> None:
    js = _app_js()
    error_case = js.split('case "error":')[1].split("default:")[0]
    assert "statusError.textContent = payload.detail" in error_case
    assert "statusError.hidden = false" in error_case
    assert ".close()" not in error_case
