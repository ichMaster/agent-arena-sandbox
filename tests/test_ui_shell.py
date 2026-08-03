"""Integration tests for the static index.html + styles.css shell (ARENA-063)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_served_html_has_app_bar_elements() -> None:
    html = client.get("/ui/").text

    assert "Agent" in html and "Arena" in html
    assert 'id="connection-dot"' in html
    assert 'id="connection-label"' in html
    assert "Host New Match" in html
    assert "Join Match" in html
    assert "Observe" in html


def test_served_html_has_nine_disabled_board_cells() -> None:
    html = client.get("/ui/").text

    for i in range(9):
        assert f'id="cell-{i}"' in html
    # each cell button carries the disabled attribute (inert until v03.02).
    import re

    cells = re.findall(r'<button class="cell empty" id="cell-\d"[^>]*>', html)
    assert len(cells) == 9
    assert all("disabled" in cell for cell in cells)


def test_served_html_has_chat_panel_structure() -> None:
    html = client.get("/ui/").text

    assert 'id="messages"' in html
    assert 'id="chat-input"' in html
    assert 'id="chat-send"' in html
    assert "disabled" in html  # the chat input/send start disabled


def test_styles_css_defines_documented_custom_properties() -> None:
    css = client.get("/ui/styles.css").text

    for token in ("--x:", "--o:", "--ok:", "--accent:"):
        assert token in css
