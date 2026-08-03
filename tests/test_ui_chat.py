"""Served-asset tests for the chat panel (ARENA-OPUS-030). No LLM, no paid call."""

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


def test_chat_submit_sends_action_not_optimistic(app_js: str) -> None:
    assert "function handleChatSubmit" in app_js
    idx = app_js.index("function handleChatSubmit")
    body = app_js[idx:idx + 500]
    assert "sendAction('chat'" in body
    assert "input.value = ''" in body
    assert "renderChat" not in body   # never rendered optimistically -- the server echoes it back


def test_render_chat_self_detection_uses_symbol_not_name(app_js: str) -> None:
    assert "function renderChat" in app_js
    idx = app_js.index("function renderChat")
    body = app_js[idx:idx + 700]
    assert "sender === mySymbol" in body
    assert "textContent" in body   # escaped, never innerHTML for untrusted chat content
    assert "innerHTML" not in body


def test_error_routes_to_a_system_line(app_js: str) -> None:
    err_idx = app_js.index("case 'error'")
    body = app_js[err_idx:err_idx + 200]
    assert "renderSystem" in body


def test_game_over_posts_a_result_system_line(app_js: str) -> None:
    go_idx = app_js.index("case 'game_over'")
    body = app_js[go_idx:go_idx + 300]
    assert "renderSystem" in body


def test_chat_form_wired_to_submit_handler(app_js: str) -> None:
    assert "function wireChat" in app_js
    idx = app_js.index("function wireChat")
    body = app_js[idx:idx + 200]
    assert "handleChatSubmit" in body
    wire_ui_idx = app_js.index("function wireUI")
    assert "wireChat()" in app_js[wire_ui_idx:wire_ui_idx + 700]
