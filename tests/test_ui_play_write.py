"""Served-asset tests for the Player-role write path (ARENA-OPUS-SONNET-029). No LLM, no paid call."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def app_js(tmp_path: Path) -> str:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/ui.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        return c.get("/ui/app.js").text


def test_click_handler_sends_submit_move(app_js: str) -> None:
    assert "function handleCellClick" in app_js
    assert "sendAction('submit_move'" in app_js
    assert "cell.classList.contains('playable')" in app_js
    assert "if (!isGameActive) return" in app_js


def test_game_over_freezes_and_marks_win(app_js: str) -> None:
    assert "function handleGameOver" in app_js
    over_idx = app_js.index("function handleGameOver")
    body = app_js[over_idx:over_idx + 800]
    assert "isGameActive = false" in body
    assert "'win'" in body
    assert "WIN_LINES" in body
    go_idx = app_js.index("case 'game_over'")
    assert "handleGameOver(" in app_js[go_idx:go_idx + 120]


def test_new_match_resets_play_state(app_js: str) -> None:
    assert "function resetPlayState" in app_js
    jc = app_js.index("async function joinAndConnect")
    assert "resetPlayState()" in app_js[jc:jc + 500]
    assert "isGameActive = true" in app_js[jc:jc + 500]


def test_board_click_listeners_wired(app_js: str) -> None:
    assert "function wireBoard" in app_js
    assert "addEventListener('click', () => handleCellClick(i))" in app_js
