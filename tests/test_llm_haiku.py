"""AnthropicHaikuClient -- structured output via a mocked SDK. No network call, no cost."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import ToolUseBlock
from pydantic import ValidationError

from agent.llm import AnthropicHaikuClient, create_llm_client
from agent.schemas import AgentResponse


def _mock_tool_response(input_payload: dict[str, object]) -> SimpleNamespace:
    block = ToolUseBlock(id="t1", input=input_payload, name="respond", type="tool_use")
    return SimpleNamespace(content=[block])


async def test_generate_structured_response_returns_validated_schema() -> None:
    client = AnthropicHaikuClient(api_key="test-key")
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_mock_tool_response({"move": 4, "comment": "center is strong"})
    )

    result = await client.generate_structured_response("play tic-tac-toe", AgentResponse)

    assert result == AgentResponse(move=4, comment="center is strong")
    client._client.messages.create.assert_awaited_once()


async def test_malformed_tool_output_surfaces_as_validation_error() -> None:
    client = AnthropicHaikuClient(api_key="test-key")
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_mock_tool_response({"move": "not-an-int"})
    )

    with pytest.raises(ValidationError):
        await client.generate_structured_response("play tic-tac-toe", AgentResponse)


async def test_missing_tool_use_block_surfaces_as_validation_error() -> None:
    client = AnthropicHaikuClient(api_key="test-key")
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(content=[])
    )

    with pytest.raises(ValidationError):
        await client.generate_structured_response("play tic-tac-toe", AgentResponse)


def test_missing_api_key_aborts_construction_immediately() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicHaikuClient(api_key="")


def test_create_llm_client_haiku_returns_working_client() -> None:
    client = create_llm_client("haiku", api_key="test-key", temperature=0.8)
    assert isinstance(client, AnthropicHaikuClient)
