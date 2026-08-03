"""Unit + contract tests for LLMClient & create_llm_client dispatch (ARENA-053)."""

from __future__ import annotations

import inspect

import pytest

from agent.llm import LLMClient, create_llm_client


def test_llm_client_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_create_llm_client_fails_fast_on_missing_key() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        create_llm_client("haiku", api_key="", temperature=0.7)


def test_create_llm_client_rejects_unknown_vendor() -> None:
    with pytest.raises(ValueError, match="unknown model_type"):
        create_llm_client("bogus-vendor", api_key="sk-whatever", temperature=0.7)


def test_generate_structured_response_signature_matches_architecture_4_2() -> None:
    sig = inspect.signature(LLMClient.generate_structured_response)
    assert list(sig.parameters) == ["self", "prompt", "schema"]
    assert sig.parameters["prompt"].annotation in ("str", str)
