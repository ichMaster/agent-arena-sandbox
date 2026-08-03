"""Unit tests for AnthropicHaikuClient with the SDK fully mocked -- zero paid calls, zero network."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.llm import HAIKU_MODEL_ID, AnthropicHaikuClient
from agent.schemas import AgentResponse


def _mock_anthropic_returning(parsed_output: AgentResponse | None) -> MagicMock:
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.parsed_output = parsed_output
    mock_client.messages.parse = AsyncMock(return_value=mock_message)
    return mock_client


async def test_returns_the_parsed_agent_response() -> None:
    expected = AgentResponse(move=4, comment="center, obviously")
    with patch(
        "agent.llm.AsyncAnthropic", return_value=_mock_anthropic_returning(expected)
    ) as mock_ctor:
        client = AnthropicHaikuClient(api_key="sk-test-not-real")
        result = await client.generate_structured_response("pick a move", AgentResponse)

    assert result == expected
    mock_ctor.assert_called_once_with(api_key="sk-test-not-real")  # the REAL SDK class never ran


async def test_uses_the_haiku_model_id_and_the_passed_temperature() -> None:
    mock_client = _mock_anthropic_returning(AgentResponse(move=0, comment="x"))
    with patch("agent.llm.AsyncAnthropic", return_value=mock_client):
        client = AnthropicHaikuClient(api_key="sk-test", temperature=0.9)
        await client.generate_structured_response("prompt text", AgentResponse)

    call_kwargs = mock_client.messages.parse.call_args.kwargs
    assert call_kwargs["model"] == HAIKU_MODEL_ID == "claude-haiku-4-5"
    assert call_kwargs["temperature"] == 0.9
    assert call_kwargs["output_format"] is AgentResponse
    assert call_kwargs["messages"] == [{"role": "user", "content": "prompt text"}]


async def test_none_parsed_output_raises_instead_of_silently_accepting() -> None:
    """Malformed/unparseable model output surfaces as an error, never as a silent pass-through."""
    with patch("agent.llm.AsyncAnthropic", return_value=_mock_anthropic_returning(None)):
        client = AnthropicHaikuClient(api_key="sk-test")
        with pytest.raises(ValueError):
            await client.generate_structured_response("prompt", AgentResponse)
