"""Unit tests for AnthropicHaikuClient (ARENA-054). The SDK is mocked throughout —
no network call, no cost."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agent.llm import AnthropicHaikuClient, create_llm_client
from agent.schemas import AgentResponse


def _fake_tool_use_message(input_dict: dict[str, object]) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", input=input_dict)
    return SimpleNamespace(content=[block])


@pytest.mark.asyncio
async def test_well_formed_tool_call_parses_into_validated_response() -> None:
    client = AnthropicHaikuClient(api_key="sk-test", temperature=0.7)
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_fake_tool_use_message({"move": 4, "comment": "center, obviously"})
    )

    response = await client.generate_structured_response("play your turn", AgentResponse)

    assert response == AgentResponse(move=4, comment="center, obviously")


@pytest.mark.asyncio
async def test_malformed_tool_call_surfaces_as_validation_error() -> None:
    client = AnthropicHaikuClient(api_key="sk-test", temperature=0.7)
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=_fake_tool_use_message({"move": "not an int"})
    )

    with pytest.raises(ValidationError):
        await client.generate_structured_response("play your turn", AgentResponse)


@pytest.mark.asyncio
async def test_no_tool_use_block_raises() -> None:
    client = AnthropicHaikuClient(api_key="sk-test", temperature=0.7)
    client._client.messages.create = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="I refuse")])
    )

    with pytest.raises(ValueError, match="no tool_use block"):
        await client.generate_structured_response("play your turn", AgentResponse)


def test_create_llm_client_haiku_returns_anthropic_haiku_client() -> None:
    client = create_llm_client("haiku", api_key="sk-test", temperature=0.7)
    assert isinstance(client, AnthropicHaikuClient)
