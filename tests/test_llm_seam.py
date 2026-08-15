"""Contract test pinning LLMClient (architecture.md §4.2) + create_llm_client dispatch."""

from __future__ import annotations

import inspect
from abc import ABC

import pytest

from agent.llm import LLMClient, create_llm_client


def test_llm_client_is_abstract() -> None:
    assert issubclass(LLMClient, ABC)
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_generate_structured_response_pinned_signature() -> None:
    method = LLMClient.generate_structured_response
    assert getattr(method, "__isabstractmethod__", False)
    sig = inspect.signature(method)
    assert list(sig.parameters) == ["self", "prompt", "schema"]


def test_create_llm_client_raises_on_unknown_model_type() -> None:
    with pytest.raises(ValueError, match="unknown model_type"):
        create_llm_client("not-a-real-model", api_key="key", temperature=0.7)
