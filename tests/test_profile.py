"""Unit tests for AgentProfile & the aggressive.yml sample persona (ARENA-055)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.profile import AgentProfile

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGGRESSIVE_YML = _REPO_ROOT / "profiles" / "aggressive.yml"


def test_loading_aggressive_yml_produces_expected_fields() -> None:
    profile = AgentProfile.load_from_yaml(_AGGRESSIVE_YML)

    assert profile.name == "Aggressor"
    assert profile.model_type == "haiku"
    assert profile.temperature == 0.9
    assert profile.memory_limit == 10
    assert "Aggressor" in profile.system_prompt


def test_missing_optional_fields_use_documented_defaults(tmp_path: Path) -> None:
    minimal = tmp_path / "minimal.yml"
    minimal.write_text(
        "name: Minimal\nmodel_type: haiku\nsystem_prompt: 'be quiet'\n", encoding="utf-8"
    )

    profile = AgentProfile.load_from_yaml(minimal)

    assert profile.temperature == 0.7
    assert profile.memory_limit == 10


def test_missing_required_field_raises_clear_error(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.yml"
    incomplete.write_text("model_type: haiku\nsystem_prompt: 'be quiet'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid agent profile"):
        AgentProfile.load_from_yaml(incomplete)


def test_malformed_yaml_raises_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("name: [unclosed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid YAML"):
        AgentProfile.load_from_yaml(bad)
