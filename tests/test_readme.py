"""README.md -- setup, the three run modes, protocol summary, testing
(ARENA-111/112, roadmap.md §v05.03 DoD).

Content checks only -- actually running the documented commands (fresh venv
install, pytest, mypy, server start, /ui headers, scripts/run_arena.sh) was
done manually during ARENA-112's own verification, not automated here (that
would mean spawning a second venv and a real server from within the test
suite itself, disproportionate to what a content-drift guard needs).
"""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def _readme() -> str:
    return README.read_text()


def test_readme_exists() -> None:
    assert README.is_file()


def test_documents_all_three_run_modes() -> None:
    text = _readme()
    assert "Human vs. agent" in text
    assert "Agent vs. agent" in text
    assert "Observe" in text


def test_documents_the_exact_setup_commands() -> None:
    text = _readme()
    assert "python3 -m venv .venv" in text
    assert 'pip install -e ".[dev]"' in text
    assert "ANTHROPIC_API_KEY" in text
    assert ".env" in text
    assert "arena.db" in text


def test_documents_the_exact_run_commands() -> None:
    text = _readme()
    assert "uvicorn server.main:app" in text
    assert "python -m agent.agent --match-id" in text
    assert "--profile profiles/aggressive.yml" in text
    assert "./scripts/run_arena.sh" in text


def test_documents_testing_commands_and_mock_policy() -> None:
    text = _readme()
    assert "pytest" in text
    assert "mypy games server agent" in text
    assert "mocked" in text.lower()


def test_links_to_the_two_spec_documents() -> None:
    text = _readme()
    assert "spec/game_specification.md" in text
    assert "spec/architecture.md" in text


def test_summarizes_the_ws_protocol_events_and_actions() -> None:
    text = _readme()
    for event in ("joined", "state_update", "chat_message", "game_over", "error"):
        assert event in text
    for action in ("submit_move", "chat"):
        assert action in text
