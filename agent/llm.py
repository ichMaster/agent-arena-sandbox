"""The LLMClient seam — the only way the agent talks to a model vendor (architecture.md §4.2).

Vendor-agnostic by design: `agent/agent.py` never imports a concrete client, only this abstraction
(and, from ARENA-OPUS-SONNET-018 onward, `create_llm_client`). Imports nothing from `server/` — the
agent is a pure external client, exactly like the Web UI.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """One seam, one job: force the model to structured output and hand back a validated instance."""

    @abstractmethod
    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Return an instance of `schema`; the caller never parses raw text."""


# Confirmed against the live Anthropic model list (not guessed) -- a single config constant so a
# future tier/model swap touches one place.
HAIKU_MODEL_ID = "claude-haiku-4-5"
_MAX_TOKENS = 1024


class AnthropicHaikuClient(LLMClient):
    """The only concrete LLMClient for now: Anthropic Haiku via the async SDK (§4.2, §7.3)."""

    def __init__(self, api_key: str, temperature: float = 0.7) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._temperature = temperature

    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        message = await self._client.messages.parse(
            model=HAIKU_MODEL_ID,
            max_tokens=_MAX_TOKENS,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        parsed = message.parsed_output
        if parsed is None:
            raise ValueError("model reply did not parse into the expected structured schema")
        return parsed


def load_api_key(env: Mapping[str, str] | None = None) -> str:
    """Read `ANTHROPIC_API_KEY`, aborting clearly if it's missing or empty (§9).

    The secret lives only in the agent process — never sent to or logged by the server/UI, and
    never logged here either.
    """
    source = env if env is not None else os.environ
    key = source.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Put it in the agent's .env -- this key is read only by "
            "the agent process and is never sent to or logged by the server or UI (architecture.md §9)."
        )
    return key


def create_llm_client(model_type: str, api_key: str, temperature: float = 0.7) -> LLMClient:
    """Config-driven vendor selection (§4.2) -- the only place `agent/agent.py` needs to know a
    concrete client exists."""
    if not api_key:
        raise RuntimeError("create_llm_client: api_key must not be empty")
    if model_type == "haiku":
        return AnthropicHaikuClient(api_key=api_key, temperature=temperature)
    raise ValueError(f"unknown model_type: {model_type!r}")
