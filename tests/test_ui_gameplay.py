"""Served-asset tests for the Player-role gameplay wiring (v03.02, ARENA-OPUS-SONNET-028). No LLM,
no paid call. The no-build UI is validated by asserting app.js's entry points + interactivity gate
at the served level (no JS engine in pytest), consistent with the vanilla-JS design.
"""

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


def test_render_functions_defined(app_js: str) -> None:
    assert "function renderBoard" in app_js
    assert "function renderPlayers" in app_js
    assert "function renderTurnBanner" in app_js


def test_interactivity_gate_on_my_turn(app_js: str) -> None:
    # A cell is playable only when active + my turn + legal (web_ui_spec §6.2).
    assert "currentTurn === mySymbol" in app_js
    assert "isGameActive" in app_js
    assert "legal.has(i)" in app_js
    assert "cell.disabled" in app_js  # the real disabled attribute (a11y §9), not just a class


def test_read_events_call_renderers(app_js: str) -> None:
    joined_idx = app_js.index("case 'joined'")
    state_idx = app_js.index("case 'state_update'")
    chat_idx = app_js.index("case 'chat_message'")
    assert "renderBoard(" in app_js[joined_idx:chat_idx]
    assert "renderBoard(" in app_js[state_idx:chat_idx]
