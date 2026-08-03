"""ARENA-032/033 -- the Player role: board rendering, clicks, cards, reset.

Served-asset level, consistent with the no-build UI.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.main import app


@pytest.fixture
def js(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'g.db'}")
    with TestClient(app) as client:
        yield client.get("/ui/app.js").text


# -- ARENA-032 -------------------------------------------------------------


@pytest.mark.parametrize("case", ['case "joined"', 'case "state_update"',
                                  'case "game_over"', 'case "error"'])
def test_route_event_handles_every_server_event(js: str, case: str) -> None:
    assert case in js


def test_the_board_renders_from_the_pushed_payload(js: str) -> None:
    assert "function renderBoard(board, validMoves)" in js
    assert "cell.textContent = mark" in js


def test_cells_are_enabled_only_on_our_turn_and_only_when_legal(js: str) -> None:
    """The client must not invent legality -- the server says which cells are legal."""
    assert "state.currentTurn !== state.symbol" in js
    assert "!legal.has(index)" in js
    assert "const legal = new Set(validMoves)" in js


def test_an_observer_never_gets_an_enabled_cell(js: str) -> None:
    assert "state.symbol === null" in js


def test_the_click_handler_guards_every_way_it_can_be_wrong(js: str) -> None:
    assert "if (cell.disabled || state.over) return;" in js
    assert "state.socket.readyState !== 1" in js
    assert "state.currentTurn !== state.symbol" in js


def test_a_click_sends_submit_move(js: str) -> None:
    assert 'action: "submit_move"' in js
    assert "Number(cell.dataset.cell)" in js


def test_game_over_freezes_the_board_and_shows_the_result(js: str) -> None:
    assert "function handleGameOver" in js
    assert "disableBoard()" in js
    assert "result-banner" in js


def test_a_draw_reads_as_draw(js: str) -> None:
    assert '=== "draw"' in js


# -- ARENA-033 -------------------------------------------------------------


def test_both_seats_are_shown_and_the_active_one_highlighted(js: str) -> None:
    assert "function markActivePlayer(turn)" in js
    assert "card.dataset.active" in js


def test_init_player_cards_tolerates_a_null_symbol(js: str) -> None:
    """The observer path: symbol is null and must not crash the view."""
    assert "function initPlayerCards(symbol)" in js
    assert "if (!card) return;" in js


def test_a_new_match_resets_play_state(js: str) -> None:
    """Otherwise the second game renders on top of the first."""
    assert "function resetPlayState()" in js
    assert "resetPlayState();" in js
    assert "banner.hidden = true" in js
    assert "log.replaceChildren()" in js


def test_the_reset_runs_when_a_socket_opens(js: str) -> None:
    opened = js.index("function openSocket")
    assert "resetPlayState();" in js[opened : opened + 400]
