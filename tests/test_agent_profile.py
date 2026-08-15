"""agent/profile.py -- AgentProfile.load_from_yaml (architecture.md §7.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent.profile import AgentProfile


def test_loads_the_sample_aggressive_profile() -> None:
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    assert profile.name
    assert profile.model_type == "haiku"
    assert isinstance(profile.temperature, float)
    assert profile.system_prompt
    assert profile.memory_limit > 0


def test_missing_required_field_raises_validation_error(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.yml"
    incomplete.write_text(yaml.safe_dump({"name": "NoPrompt", "model_type": "haiku"}))
    with pytest.raises(ValidationError):
        AgentProfile.load_from_yaml(incomplete)


def test_nonexistent_path_raises_clearly() -> None:
    with pytest.raises(FileNotFoundError):
        AgentProfile.load_from_yaml("profiles/does-not-exist.yml")
