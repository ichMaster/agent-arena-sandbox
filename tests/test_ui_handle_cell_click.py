"""Integration tests for handleCellClick -> submit_move, guarded (ARENA-066)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def _app_js() -> str:
    response = client.get("/ui/app.js")
    assert response.status_code == 200
    return response.text


def test_defines_handle_cell_click() -> None:
    js = _app_js()
    assert re.search(r"\bfunction\s+handleCellClick\b", js)


def test_handle_cell_click_guards_socket_state_and_active_game() -> None:
    js = _app_js()
    match = re.search(r"function handleCellClick\(index\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "handleCellClick body not found"
    body = match.group(1)
    assert "ws.readyState" in body
    assert "WebSocket.OPEN" in body
    assert "isGameActive" in body
    assert "disabled" in body


def test_handle_cell_click_sends_documented_submit_move_envelope() -> None:
    js = _app_js()
    match = re.search(r"function handleCellClick\(index\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "handleCellClick body not found"
    body = match.group(1)
    assert re.search(r"action:\s*[\"']submit_move[\"']", body)
    assert re.search(r"move:\s*index", body)


def test_click_listeners_wired_to_all_nine_cells() -> None:
    js = _app_js()
    match = re.search(r"function init\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert match, "init body not found"
    body = match.group(1)
    assert "handleCellClick" in body
    assert "cell-${i}" in body or "cell-" in body
