"""Integration tests for renderBoard/initPlayerCards/updateActiveCard (ARENA-065).

Source-level checks, consistent with this repo's no-headless-browser testing approach.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_render_board_and_player_card_functions() -> None:
    js = _app_js()
    for name in ("renderBoard", "initPlayerCards", "updateActiveCard"):
        assert re.search(rf"\bfunction\s+{name}\b", js), f"{name} not defined"


def test_render_board_ties_playability_to_current_turn_matching_my_symbol() -> None:
    js = _app_js()
    match = re.search(r"function renderBoard\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "renderBoard body not found"
    body = match.group(1)
    assert "currentTurn" in body
    assert re.search(r"currentTurn\s*===\s*mySymbolParam", body)
    assert "isGameActiveParam" in body


def test_init_player_cards_never_calls_a_method_directly_on_symbol() -> None:
    js = _app_js()
    match = re.search(r"function initPlayerCards\(symbol\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "initPlayerCards body not found"
    body = match.group(1)
    # the null.toLowerCase() regression class: symbol.<method>(...) anywhere in the body.
    assert not re.search(r"\bsymbol\.\w+\(", body)


def test_route_event_wires_joined_and_state_update_to_rendering() -> None:
    js = _app_js()
    match = re.search(r"function routeEvent\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "routeEvent body not found"
    body = match.group(1)
    assert body.count("renderBoard(") >= 2  # joined and state_update both call it
    assert body.count("updateActiveCard(") >= 2
    assert "initPlayerCards(" in body
