"""The static arena shell -- index.html structural hooks + styles.css tokens
(ARENA-098, web_ui_specification.md §2-4)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import WEB_DIR, app

PROTOTYPE = Path(__file__).resolve().parent.parent / "spec" / "ui_prototype.html"


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


def test_styles_css_matches_every_prototype_design_token() -> None:
    """ARENA-112 (v05.03): the manual check that found zero drift between
    web/styles.css and spec/ui_prototype.html -- automated so future drift
    fails a test rather than requiring another manual re-check."""
    token_pattern = re.compile(r"--[a-z0-9-]+:")
    prototype_tokens = set(token_pattern.findall(PROTOTYPE.read_text()))
    shipped_tokens = set(token_pattern.findall((WEB_DIR / "styles.css").read_text()))
    assert prototype_tokens  # sanity: the pattern actually matched something
    assert prototype_tokens == shipped_tokens


def test_every_dom_id_app_js_looks_up_exists_in_index_html() -> None:
    """ARENA-112 (v05.03): a mismatched id here is a null-dereference crash
    the first time that code path runs, not a style nit -- automated so it
    can never silently regress (code review, v03.02, made the same point
    manually; this locks it in)."""
    referenced = set(re.findall(r'getElementById\("([^"]+)"\)', (WEB_DIR / "app.js").read_text()))
    defined = set(re.findall(r'id="([^"]+)"', (WEB_DIR / "index.html").read_text()))
    assert referenced  # sanity: the pattern actually matched something
    assert referenced <= defined
