"""Player cards + active-turn highlight; same-tab match reset (ARENA-102,
web_ui_specification.md §4.3, §5, §7).

Static assertions on the served app.js source (see test_ui_app.py's module
docstring for why: no browser/JS runner in this repo).
"""

from __future__ import annotations

from server.main import WEB_DIR


def _app_js() -> str:
    return (WEB_DIR / "app.js").read_text()


def _function_body(js: str, signature: str) -> str:
    return js.split(signature)[1].split("\n  function ")[0]


def test_init_player_cards_never_calls_to_lower_case_on_the_symbol() -> None:
    """The classic null-crash shape web_ui_specification.md §5 calls out by
    name -- initPlayerCards(null) must not do anything resembling
    mySymbol.toLowerCase()."""
    js = _app_js()
    body = _function_body(js, "function initPlayerCards(mySymbol)")
    assert "mySymbol.toLowerCase" not in body
    assert "mySymbol ===" in body  # branches on identity, never calls into it


def test_init_player_cards_falls_back_to_defaults_for_an_observer() -> None:
    js = _app_js()
    body = _function_body(js, "function initPlayerCards(mySymbol)")
    else_branch = body.rsplit("} else {", 1)[1]
    assert "Player X" in else_branch
    assert "Player O" in else_branch


def test_init_player_cards_labels_the_humans_own_card_you() -> None:
    js = _app_js()
    body = _function_body(js, "function initPlayerCards(mySymbol)")
    x_branch = body.split('mySymbol === "X"')[1].split('mySymbol === "O"')[0]
    o_branch = body.split('mySymbol === "O"')[1].split("} else {")[0]
    assert '"You"' in x_branch
    assert '"You"' in o_branch


def test_update_active_card_matches_current_turn_to_symbol() -> None:
    js = _app_js()
    body = _function_body(js, "function updateActiveCard(currentTurn)")
    assert 'currentTurn === "X"' in body
    assert 'currentTurn === "O"' in body


def test_neither_card_active_when_current_turn_is_null() -> None:
    """toggle(cls, false) for both when currentTurn is null -- no separate
    branch, so there's no way for exactly one card to end up active."""
    js = _app_js()
    # Bounded to the function's own closing brace (not the next function's
    # comments) -- the body is two statements, no control flow at all.
    body = js.split("function updateActiveCard(currentTurn) {")[1].split("\n  }")[0]
    assert "if" not in body  # a single unconditional pair of toggle() calls


def test_game_over_clears_the_active_card() -> None:
    js = _app_js()
    game_over_case = js.split('case "game_over":')[1].split('case "error":')[0]
    assert "updateActiveCard(null)" in game_over_case


def test_route_event_updates_active_card_on_joined_and_state_update() -> None:
    js = _app_js()
    joined_case = js.split('case "joined":')[1].split('case "state_update":')[0]
    state_update_case = js.split('case "state_update":')[1].split('case "chat_message":')[0]
    assert "updateActiveCard(" in joined_case
    assert "updateActiveCard(" in state_update_case


def test_reset_clears_board_cards_and_error_notice() -> None:
    js = _app_js()
    body = _function_body(js, "function resetBoardAndCards()")
    assert "state.lastBoard = null" in body
    assert 'cell.className = "cell empty disabled"' in body
    assert "initPlayerCards(null)" in body
    assert "updateActiveCard(null)" in body
    assert "statusError.hidden = true" in body


def test_connect_resets_before_the_new_socket_opens() -> None:
    """The reset must happen before joined can possibly arrive, so no stale
    state from the previous match is ever visible even for a moment."""
    js = _app_js()
    connect_body = js.split("function connect(matchId, token, playerName)")[1].split(
        "\n  function "
    )[0]
    reset_index = connect_body.find("resetBoardAndCards()")
    new_ws_index = connect_body.find("new WebSocket(")
    assert reset_index != -1
    assert reset_index < new_ws_index
