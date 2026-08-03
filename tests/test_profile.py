"""Unit tests for AgentProfile (architecture §7.2, spec §5.2). No LLM, no paid call.

Covers: loading the shipped sample, defaults, every validation failure, file/parse errors, and —
per the v02.02 reconciliation — that a loaded profile's fields drive the real `create_llm_client`.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pydantic
import pytest

from agent.llm import AnthropicHaikuClient, create_llm_client
from agent.profile import AgentProfile


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "profile.yml"
    path.write_text(content, encoding="utf-8")
    return path


def test_sample_profile_loads() -> None:
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    assert profile.name == "Ironclaw"
    assert profile.model_type == "haiku"
    assert 0.0 <= profile.temperature <= 1.0
    assert profile.memory_limit > 0
    assert "Ironclaw" in profile.system_prompt


def test_minimal_yaml_gets_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path, 'name: Min\nsystem_prompt: "be minimal"\n')
    profile = AgentProfile.load_from_yaml(path)
    assert profile.model_type == "haiku"
    assert profile.temperature == 0.7
    assert profile.memory_limit == 10


@pytest.mark.parametrize(
    "content",
    [
        "name: X\nsystem_prompt: p\ntemperature: 1.5\n",  # temperature out of bounds
        "name: X\nsystem_prompt: p\ntemperature: -0.1\n",
        "name: X\nsystem_prompt: p\nmemory_limit: 0\n",  # non-positive memory
        "name: X\nsystem_prompt: p\ntaunt_level: 11\n",  # unknown key rejected
        "system_prompt: p\n",  # missing name
        "name: X\n",  # missing system_prompt
    ],
)
def test_invalid_profiles_raise(tmp_path: Path, content: str) -> None:
    path = _write(tmp_path, content)
    with pytest.raises(pydantic.ValidationError):
        AgentProfile.load_from_yaml(path)


def test_missing_file_raises_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        AgentProfile.load_from_yaml(tmp_path / "nope.yml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "name: [unclosed\n")
    with pytest.raises(Exception):  # a YAML parse error surfaces
        AgentProfile.load_from_yaml(path)


def test_non_mapping_document_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        AgentProfile.load_from_yaml(path)


def test_profile_drives_the_real_llm_factory() -> None:
    """Reconciliation tie: the loaded profile's model_type/temperature feed create_llm_client."""
    profile = AgentProfile.load_from_yaml("profiles/aggressive.yml")
    with patch("agent.llm.AsyncAnthropic", return_value=MagicMock()):  # no real SDK / network
        client = create_llm_client(profile.model_type, "sk-test", profile.temperature)
    assert isinstance(client, AnthropicHaikuClient)
