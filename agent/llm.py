"""LLMClient -- the model-vendor seam (architecture.md §4.2).

The only way the agent talks to a model. Keeps agent logic free of any vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    @abstractmethod
    async def generate_structured_response(self, prompt: str, schema: type[T]) -> T:
        """Return an instance of `schema`, forcing the model to structured output."""


def create_llm_client(model_type: str, api_key: str, temperature: float) -> LLMClient:
    """Config-driven vendor selection, keyed off AgentProfile.model_type.

    No implementation is registered yet -- AnthropicHaikuClient lands in ARENA-089 and
    adds the "haiku" branch here.
    """
    raise ValueError(f"unknown model_type: {model_type!r}")
