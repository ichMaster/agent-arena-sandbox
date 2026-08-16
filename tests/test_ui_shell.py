"""The static arena shell -- index.html structural hooks + styles.css tokens
(ARENA-098, web_ui_specification.md §2-4)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.main import WEB_DIR, app


def test_index_html_has_the_dom_hooks_app_js_will_bind_to() -> None:
    with TestClient(app) as client:
        html = client.get("/ui/").text

    # Connection status.
    assert 'id="status-dot"' in html
    assert 'id="status-label"' in html
    assert 'id="match-id"' in html

    # Lobby controls.
    assert 'id="btn-host"' in html
    assert 'id="btn-join"' in html
    assert 'id="btn-observe"' in html

    # Stage: board container + player cards.
    assert 'id="board"' in html
    assert 'id="player-x"' in html
    assert 'id="player-o"' in html

    # Chat: message list + input.
    assert 'id="messages"' in html
    assert 'id="chat-form"' in html
    assert 'id="chat-input"' in html


def test_index_html_has_no_inline_game_logic() -> None:
    """Purely structural markup -- no client-side game state or move logic yet
    (web_ui_specification.md §1: stateless renderer, no build step)."""
    with TestClient(app) as client:
        html = client.get("/ui/").text
    scripts = html.count("<script")
    # Only the bootstrapping <script src="/ui/app.js"> -- no inline logic.
    assert scripts == 1
    assert '<script src="/ui/app.js">' in html


def test_styles_css_defines_the_design_system_tokens() -> None:
    css = (WEB_DIR / "styles.css").read_text()
    for token in ("--bg-0", "--bg-1", "--text", "--muted", "--x", "--o", "--ok", "--accent"):
        assert f"{token}:" in css


def test_styles_css_collapses_to_one_column_at_860px() -> None:
    css = (WEB_DIR / "styles.css").read_text()
    assert "max-width: 860px" in css
    assert "grid-template-columns: 1fr" in css


def test_styles_css_respects_reduced_motion() -> None:
    css = (WEB_DIR / "styles.css").read_text()
    assert "prefers-reduced-motion" in css


def test_web_dir_points_at_the_real_directory() -> None:
    assert WEB_DIR == Path(__file__).resolve().parent.parent / "web"
    assert WEB_DIR.is_dir()
