"""The model-vendor seam (architecture.md §4.2).

``LLMClient`` is the only way the agent talks to a model. Two rules make it load-bearing:

**Structured output is forced at the client.** ``generate_structured_response`` returns a
validated instance of the schema it was handed -- the caller never sees, and never parses,
raw text. A model that replies with prose produces a validation error, not a plausible
wrong answer that flows onward as if it were data.

**The seam is vendor-agnostic.** Anthropic Haiku is the only implementation today; a
second vendor arrives as another subclass behind ``create_llm_client``, never as a branch
inside this one. ``agent/agent.py`` imports the seam and never a concrete client, which is
what keeps the vendor a config choice.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

#: The one place the model id lives. Confirmed against Anthropic's live model list rather
#: than guessed (roadmap §v02.01 asks for exactly that): Haiku 4.5 is current, and it
#: supports structured outputs -- which is what lets this client force a schema instead of
#: prompting for JSON and parsing it. The alias carries no date suffix by design.
HAIKU_MODEL_ID = "claude-haiku-4-5"

#: A single move plus a short taunt. Small on purpose: the reply is one structured object.
DEFAULT_MAX_TOKENS = 512

#: The environment variable the key is read from. It lives only in the agent's process --
#: never sent to, or logged by, the server or the UI (§9).
API_KEY_ENV = "ANTHROPIC_API_KEY"

#: ``model_type`` values accepted by :func:`create_llm_client`.
SUPPORTED_MODEL_TYPES: tuple[str, ...] = ("haiku",)


class LLMClient(ABC):
    """The only way the agent talks to a model vendor."""

    @abstractmethod
    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Return a validated instance of ``schema``.

        Implementations force structured output at the vendor (tool-use or JSON schema);
        they never hand back text for the caller to interpret.
        """


class AnthropicHaikuClient(LLMClient):
    """The only vendor implementation -- Anthropic Haiku over the official SDK."""

    def __init__(
        self,
        api_key: str,
        temperature: float = 1.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str = HAIKU_MODEL_ID,
    ) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Ask Haiku for one structured reply.

        Uses ``messages.parse(output_format=schema)``: the SDK constrains the response to
        the schema and validates it, so a malformed reply raises rather than arriving as a
        half-parsed dict. There is deliberately no ``json.loads`` anywhere in this module.
        """
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        parsed: T | None = response.parsed_output
        if parsed is None:
            raise LLMResponseError(
                f"{self._model} returned no parseable {schema.__name__}; "
                "the reply did not satisfy the requested schema"
            )
        return parsed


class LLMResponseError(RuntimeError):
    """The model replied, but not with something that satisfies the schema."""


class MissingAPIKeyError(RuntimeError):
    """No API key was available. Raised before any client or network call exists."""


def create_llm_client(
    model_type: str,
    api_key: str | None = None,
    temperature: float = 1.0,
) -> LLMClient:
    """Build the client named by ``model_type`` (from ``AgentProfile.model_type``).

    An unknown ``model_type`` is an error naming the supported values -- never a silent
    default. Quietly falling back to a vendor would mean a typo in a profile changes which
    model plays, and which account is billed, with nothing to notice it.
    """
    resolved = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
    if not resolved or not resolved.strip():
        raise MissingAPIKeyError(
            f"{API_KEY_ENV} is not set. The agent needs an Anthropic API key; "
            f"put it in the agent's .env or export {API_KEY_ENV} before starting."
        )

    if model_type not in SUPPORTED_MODEL_TYPES:
        raise ValueError(
            f"unknown model_type {model_type!r}; "
            f"supported: {', '.join(SUPPORTED_MODEL_TYPES)}"
        )

    return AnthropicHaikuClient(api_key=resolved, temperature=temperature)
