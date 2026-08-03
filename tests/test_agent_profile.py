"""ARENA-022/023/024/025 -- profile, memory window, prompt, and the shipped persona.

No model call anywhere in this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent.memory import MemoryWindow
from agent.profile import MAX_MEMORY_LIMIT, AgentProfile, ProfileError
from agent.prompt import build_prompt, render_board

VALID = {
    "name": "Aggressive",
    "system_prompt": "Play to win and say so.",
    "model_type": "haiku",
    "temperature": 0.8,
    "memory_limit": 5,
}


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "p.yml"
    path.write_text(yaml.safe_dump(data) if not isinstance(data, str) else data)
    return path


# -- ARENA-022: the profile ------------------------------------------------


def test_a_valid_profile_loads(tmp_path: Path) -> None:
    profile = AgentProfile.load_from_yaml(_write(tmp_path, VALID))
    assert (profile.name, profile.model_type, profile.temperature) == ("Aggressive", "haiku", 0.8)


def test_defaults_are_applied(tmp_path: Path) -> None:
    profile = AgentProfile.load_from_yaml(
        _write(tmp_path, {"name": "A", "system_prompt": "p"})
    )
    assert (profile.model_type, profile.temperature, profile.memory_limit) == ("haiku", 1.0, 10)


def test_an_unknown_model_type_fails_at_load(tmp_path: Path) -> None:
    """Not at the first model call -- by then the agent is already seated in a match."""
    with pytest.raises(ProfileError, match="supported: haiku"):
        AgentProfile.load_from_yaml(_write(tmp_path, {**VALID, "model_type": "gpt"}))


@pytest.mark.parametrize("temperature", [-0.1, 1.1, 42.0])
def test_an_out_of_range_temperature_is_rejected(tmp_path: Path, temperature: float) -> None:
    """v02.01 code review finding #3, homed here."""
    with pytest.raises(ProfileError, match="temperature"):
        AgentProfile.load_from_yaml(_write(tmp_path, {**VALID, "temperature": temperature}))


@pytest.mark.parametrize("limit", [0, -1, MAX_MEMORY_LIMIT + 1])
def test_an_out_of_range_memory_limit_is_rejected(tmp_path: Path, limit: int) -> None:
    with pytest.raises(ProfileError, match="memory_limit"):
        AgentProfile.load_from_yaml(_write(tmp_path, {**VALID, "memory_limit": limit}))


def test_a_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="no profile at"):
        AgentProfile.load_from_yaml(tmp_path / "absent.yml")


def test_malformed_yaml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "p.yml"
    path.write_text("name: [unclosed\n")
    with pytest.raises(ProfileError, match="not valid YAML"):
        AgentProfile.load_from_yaml(path)


def test_a_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.yml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ProfileError, match="mapping"):
        AgentProfile.load_from_yaml(path)


def test_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        AgentProfile.load_from_yaml(_write(tmp_path, {**VALID, "temperatur": 0.5}))


# -- ARENA-023: the memory window ------------------------------------------


def test_it_keeps_the_last_n_and_evicts_oldest_first() -> None:
    window = MemoryWindow(maxlen=3)
    for cell in range(5):
        window.record_move("X", cell)
    assert len(window) == 3
    assert window.render() == ["X played: 2", "X played: 3", "X played: 4"]


def test_it_records_moves_and_chat_in_order() -> None:
    window = MemoryWindow(maxlen=10)
    window.record_move("X", 4)
    window.record_chat("O", "nice one")
    window.record_move("O", 0)
    assert window.render() == ["X played: 4", "O said: nice one", "O played: 0"]


def test_an_empty_window_renders_empty() -> None:
    assert MemoryWindow(maxlen=5).render() == []


@pytest.mark.parametrize("limit", [0, -1])
def test_a_nonpositive_limit_is_rejected(limit: int) -> None:
    """Silently keeping everything would grow the prompt without bound."""
    with pytest.raises(ValueError, match="at least 1"):
        MemoryWindow(maxlen=limit)


def test_the_limit_comes_from_the_profile(tmp_path: Path) -> None:
    profile = AgentProfile.load_from_yaml(_write(tmp_path, {**VALID, "memory_limit": 4}))
    assert MemoryWindow(maxlen=profile.memory_limit).maxlen == 4


# -- ARENA-024: the prompt -------------------------------------------------


def test_the_board_renders_as_a_grid() -> None:
    board = ["X", None, "O", None, "X", None, None, None, "O"]
    assert render_board(board) == "X . O\n. X .\n. . O"


def test_the_prompt_carries_persona_board_and_legal_moves() -> None:
    window = MemoryWindow(maxlen=5)
    window.record_move("O", 4)
    prompt = build_prompt(window, [None] * 9, [0, 1, 2], "You are ruthless.")
    assert "You are ruthless." in prompt
    assert "O played: 4" in prompt
    assert "0, 1, 2" in prompt


def test_the_legal_moves_are_stated_explicitly() -> None:
    """A hallucinated move should mean the model ignored the prompt, not that the
    prompt never told it which cells were free."""
    prompt = build_prompt(MemoryWindow(maxlen=3), [None] * 9, [4, 8], "p")
    assert "Legal moves" in prompt and "4, 8" in prompt


def test_an_empty_memory_degrades_gracefully() -> None:
    prompt = build_prompt(MemoryWindow(maxlen=3), [None] * 9, [0], "p")
    assert "(nothing yet)" in prompt


def test_no_legal_moves_degrades_gracefully() -> None:
    assert "(none)" in build_prompt(MemoryWindow(maxlen=3), [None] * 9, [], "p")


def test_the_prompt_is_deterministic() -> None:
    """A prompt that varied per call would make every test flaky and defeat caching."""
    def make() -> str:
        window = MemoryWindow(maxlen=5)
        window.record_move("X", 0)
        window.record_chat("O", "hm")
        return build_prompt(window, ["X"] + [None] * 8, [1, 2], "persona")

    assert make() == make() == make()


# -- ARENA-025: the shipped persona ----------------------------------------


def test_the_shipped_profile_loads() -> None:
    """Loads the real file, so a broken sample cannot ship green."""
    root = Path(__file__).resolve().parent.parent
    profile = AgentProfile.load_from_yaml(root / "profiles" / "aggressive.yml")
    assert profile.name == "Aggressive"
    assert profile.model_type == "haiku"
    assert 0.0 <= profile.temperature <= 1.0
    assert 1 <= profile.memory_limit <= MAX_MEMORY_LIMIT
    assert len(profile.system_prompt) > 50, "the persona should actually have character"


def test_the_shipped_profile_drives_a_prompt() -> None:
    root = Path(__file__).resolve().parent.parent
    profile = AgentProfile.load_from_yaml(root / "profiles" / "aggressive.yml")
    prompt = build_prompt(MemoryWindow(profile.memory_limit), [None] * 9, [4], profile.system_prompt)
    assert "aggressive" in prompt.lower()
