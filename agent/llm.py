"""LLMClient — the model-vendor seam (architecture.md §4.2).

The only way the agent talks to a model. Keeps agent logic free of any vendor SDK —
``agent/agent.py`` imports only ``LLMClient`` and ``create_llm_client``, never a
concrete client class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

#: Anthropic's current Haiku 4.5 release — confirmed against the live model list,
#: not a placeholder guess.
_HAIKU_MODEL_ID = "claude-haiku-4-5-20251001"
_RESPONSE_TOOL_NAME = "submit_response"


class LLMClient(ABC):
    @abstractmethod
    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Return an instance of ``schema``, forcing the model to structured output."""


class AnthropicHaikuClient(LLMClient):
    """The only LLMClient implementation for now (architecture.md §4.2)."""

    def __init__(self, api_key: str, temperature: float) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._temperature = temperature

    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        message = await self._client.messages.create(
            model=_HAIKU_MODEL_ID,
            max_tokens=1024,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": _RESPONSE_TOOL_NAME,
                    "description": "Submit the structured response for this turn.",
                    "input_schema": schema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": _RESPONSE_TOOL_NAME},
        )
        for block in message.content:
            if block.type == "tool_use":
                return schema(**block.input)
        raise ValueError("model response contained no tool_use block")


def create_llm_client(model_type: str, api_key: str, temperature: float) -> LLMClient:
    """Config-driven vendor selection, keyed off ``AgentProfile.model_type``."""
    if model_type == "haiku":
        if not api_key.strip():
            raise RuntimeError("ANTHROPIC_API_KEY is required to run a live agent")
        return AnthropicHaikuClient(api_key, temperature)

    raise ValueError(f"unknown model_type: {model_type!r}")
