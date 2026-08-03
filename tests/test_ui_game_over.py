"""Integration tests for handleGameOver, error surfacing & the new-match reset (ARENA-067,
v03.02 release gate)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_handle_game_over() -> None:
    js = _app_js()
    assert re.search(r"\bfunction\s+handleGameOver\b", js)


def test_handle_game_over_disables_all_cells_and_sets_game_inactive() -> None:
    js = _app_js()
    match = re.search(r"function handleGameOver\(result\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "handleGameOver body not found"
    body = match.group(1)
    assert "isGameActive = false" in body
    assert "cell.disabled = true" in body


def test_is_game_active_resets_true_in_the_connect_flow() -> None:
    """web_ui_specification.md §7's explicit regression guard: a second match in the
    same tab must not render every cell permanently disabled."""
    js = _app_js()
    match = re.search(r"function connectWebSocket\([^)]*\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "connectWebSocket body not found"
    body = match.group(1)
    assert "isGameActive = true" in body


def test_route_event_error_case_is_not_a_no_op() -> None:
    js = _app_js()
    match = re.search(r'case "error":\s*\n(.*?)\n\s*break;', js, re.DOTALL)
    assert match, "error case not found"
    body = match.group(1).strip()
    assert body != "", "error case must not be an empty no-op"
    assert "showError" in body
