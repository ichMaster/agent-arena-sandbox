"""Unit tests for create_llm_client + load_api_key (architecture.md §4.2, §9). SDK mocked; no
paid call, no network.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.llm import AnthropicHaikuClient, create_llm_client, load_api_key


def test_haiku_dispatch_returns_anthropic_haiku_client() -> None:
    with patch("agent.llm.AsyncAnthropic", return_value=MagicMock()) as mock_ctor:
        client = create_llm_client("haiku", "sk-test-key", 0.5)
    assert isinstance(client, AnthropicHaikuClient)
    mock_ctor.assert_called_once_with(api_key="sk-test-key")  # the real SDK class never ran


def test_unknown_model_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown model_type"):
        create_llm_client("gpt-nope", "sk-test-key", 0.5)


def test_empty_api_key_raises() -> None:
    with pytest.raises(RuntimeError):
        create_llm_client("haiku", "", 0.5)


def test_load_api_key_reads_from_the_given_mapping() -> None:
    assert load_api_key({"ANTHROPIC_API_KEY": "sk-from-env"}) == "sk-from-env"


@pytest.mark.parametrize("env", [{}, {"ANTHROPIC_API_KEY": ""}, {"ANTHROPIC_API_KEY": "   "}])
def test_load_api_key_aborts_clearly_when_missing_or_empty(env: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        load_api_key(env)


def test_load_api_key_default_reads_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-os-environ")
    assert load_api_key() == "sk-from-os-environ"
