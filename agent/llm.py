"""LLMClient -- the model-vendor seam (architecture.md §4.2).

The only way the agent talks to a model. Keeps agent logic free of any vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from anthropic import AsyncAnthropic
from anthropic.types import ToolUseBlock
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

#: Confirm against the live model list (docs.anthropic.com/en/docs/about-claude/models)
#: before relying on this in production -- never hardcode a guessed id without checking.
HAIKU_MODEL_ID = "claude-haiku-4-5-20251001"

_TOOL_NAME = "respond"


class LLMClient(ABC):
    @abstractmethod
    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Return an instance of `schema`, forcing the model to structured output."""


class AnthropicHaikuClient(LLMClient):
    """The only LLMClient implementation for the MVP (architecture.md §4.2)."""

    def __init__(self, api_key: str, temperature: float = 1.0) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required to construct AnthropicHaikuClient -- "
                "the secret lives only in the agent process (architecture.md §9)."
            )
        self._client = AsyncAnthropic(api_key=api_key)
        self._temperature = temperature

    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Forces structured output via tool-use -- never returns unparsed text.

        A malformed or missing tool response surfaces as a pydantic.ValidationError
        (model_validate on an empty dict fails on required fields), the same failure
        mode as any other malformed response -- never swallowed, never a raw-text
        fallback.
        """
        response = await self._client.messages.create(
            model=HAIKU_MODEL_ID,
            max_tokens=1024,
            temperature=self._temperature,
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": "Provide the structured response.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_input: dict[str, Any] = {}
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == _TOOL_NAME:
                tool_input = block.input
                break
        return schema.model_validate(tool_input)


def create_llm_client(model_type: str, api_key: str, temperature: float) -> LLMClient:
    """Config-driven vendor selection, keyed off AgentProfile.model_type."""
    if model_type == "haiku":
        return AnthropicHaikuClient(api_key, temperature)
    raise ValueError(f"unknown model_type: {model_type!r}")
