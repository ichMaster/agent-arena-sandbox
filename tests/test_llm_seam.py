"""ARENA-018..021 -- the LLMClient seam, the Haiku client, and the factory.

**Every test here mocks the vendor.** No test in this repository may spend model quota,
so the Anthropic SDK is patched at the boundary and the real client is never constructed
with a usable key. A test that made a paid call would be a defect, not a trade-off.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from agent import llm as llm_module
from agent.llm import (
    API_KEY_ENV,
    HAIKU_MODEL_ID,
    SUPPORTED_MODEL_TYPES,
    AnthropicHaikuClient,
    LLMClient,
    LLMResponseError,
    MissingAPIKeyError,
    create_llm_client,
)
from agent.schemas import AgentResponse

# -- ARENA-019: the seam ---------------------------------------------------


def test_the_seam_has_exactly_one_method() -> None:
    declared = {
        name
        for name, value in vars(LLMClient).items()
        if callable(value) and not name.startswith("_")
    }
    assert declared == {"generate_structured_response"}


def test_the_seam_signature_is_pinned() -> None:
    """Contract test for §4.2 -- name, parameters, and the schema/return relationship."""
    signature = inspect.signature(LLMClient.generate_structured_response)
    assert [p for p in signature.parameters if p != "self"] == ["prompt", "schema"]
    assert str(signature.parameters["prompt"].annotation) == "str"
    assert str(signature.parameters["schema"].annotation) == "type[T]"
    assert str(signature.return_annotation) == "T"
    assert inspect.iscoroutinefunction(LLMClient.generate_structured_response)


def test_the_seam_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_a_subclass_missing_the_method_cannot_be_instantiated() -> None:
    partial = type("Partial", (LLMClient,), {})
    with pytest.raises(TypeError):
        partial()


async def test_a_stub_implementation_satisfies_the_seam() -> None:
    class Stub(LLMClient):
        async def generate_structured_response(self, prompt: str, schema: type[Any]) -> Any:
            return schema(move=0, comment="stubbed")

    reply = await Stub().generate_structured_response("go", AgentResponse)
    assert isinstance(reply, AgentResponse)
    assert reply.comment == "stubbed"


# -- ARENA-020: the Haiku client (SDK mocked) ------------------------------


def _client(**kwargs: Any) -> AnthropicHaikuClient:
    """Build the client with the SDK patched out -- no real Anthropic client exists."""
    with patch("anthropic.AsyncAnthropic") as sdk:
        client = AnthropicHaikuClient(api_key="not-a-real-key", **kwargs)
    client._client = sdk.return_value
    return client


def test_the_model_id_is_a_single_confirmed_constant() -> None:
    """Pinned so a later edit cannot silently change the model or add a date suffix.

    `claude-haiku-4-5` was confirmed against Anthropic's live model list rather than
    guessed, which is what roadmap §v02.01 asks for.
    """
    assert HAIKU_MODEL_ID == "claude-haiku-4-5"
    assert not HAIKU_MODEL_ID[-1].isdigit() or "-2" not in HAIKU_MODEL_ID, (
        "the alias must not carry a date suffix"
    )
    source = Path(llm_module.__file__).read_text(encoding="utf-8")
    assert source.count('"claude-haiku-4-5"') == 1, "the model id must live in one place"


async def test_it_returns_a_validated_response_from_a_mocked_sdk() -> None:
    client = _client()
    parsed = AgentResponse(move=4, comment="center")
    client._client.messages = AsyncMock()
    client._client.messages.parse = AsyncMock(
        return_value=type("R", (), {"parsed_output": parsed})()
    )

    reply = await client.generate_structured_response("your turn", AgentResponse)

    assert reply is parsed
    client._client.messages.parse.assert_awaited_once()


async def test_it_forces_structured_output_and_passes_config_through() -> None:
    client = _client(temperature=0.3, max_tokens=128)
    client._client.messages = AsyncMock()
    client._client.messages.parse = AsyncMock(
        return_value=type("R", (), {"parsed_output": AgentResponse(move=0, comment="x")})()
    )

    await client.generate_structured_response("prompt text", AgentResponse)

    kwargs = client._client.messages.parse.await_args.kwargs
    assert kwargs["output_format"] is AgentResponse, "the schema must be forced at the client"
    assert kwargs["model"] == HAIKU_MODEL_ID
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 128
    assert kwargs["messages"] == [{"role": "user", "content": "prompt text"}]


async def test_an_unparseable_reply_raises_rather_than_returning_nothing() -> None:
    """A wrong answer must not flow onward looking like data."""
    client = _client()
    client._client.messages = AsyncMock()
    client._client.messages.parse = AsyncMock(
        return_value=type("R", (), {"parsed_output": None})()
    )

    with pytest.raises(LLMResponseError, match="did not satisfy"):
        await client.generate_structured_response("go", AgentResponse)


def test_the_agent_never_parses_raw_text() -> None:
    """Structural: forcing the schema is pointless if someone re-adds json.loads.

    Asserted over the AST so a future edit that hand-parses a model reply fails here
    rather than silently reintroducing the class of bug the seam exists to prevent.
    """
    source = Path(llm_module.__file__).read_text(encoding="utf-8")
    offenders = [
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"loads", "load"}
    ]
    assert not offenders, f"model replies must never be hand-parsed: {offenders}"


# -- ARENA-021: the factory and the key ------------------------------------


def test_the_factory_builds_a_haiku_client() -> None:
    with patch("anthropic.AsyncAnthropic"):
        client = create_llm_client("haiku", api_key="not-a-real-key")
    assert isinstance(client, AnthropicHaikuClient)
    assert isinstance(client, LLMClient)


@pytest.mark.parametrize("model_type", ["gpt", "sonnet", "opus", "", "HAIKU"])
def test_an_unknown_model_type_names_the_supported_values(model_type: str) -> None:
    """Never a silent default: a typo would otherwise change which account is billed."""
    with pytest.raises(ValueError, match="supported: haiku"):
        create_llm_client(model_type, api_key="not-a-real-key")


@pytest.mark.parametrize("key", ["", "   ", None])
def test_a_missing_key_aborts_before_any_client_exists(
    key: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with patch("anthropic.AsyncAnthropic") as sdk:
        with pytest.raises(MissingAPIKeyError, match=API_KEY_ENV):
            create_llm_client("haiku", api_key=key)
    sdk.assert_not_called(), "no client may be constructed without a key"


def test_the_key_falls_back_to_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "not-a-real-key")
    with patch("anthropic.AsyncAnthropic"):
        assert isinstance(create_llm_client("haiku"), AnthropicHaikuClient)


def test_the_key_never_appears_in_an_error_or_repr() -> None:
    """§9: the secret lives only in this process. A traceback is how it usually escapes."""
    secret = "sk-ant-SUPERSECRET-do-not-leak"
    with patch("anthropic.AsyncAnthropic"):
        client = create_llm_client("haiku", api_key=secret)
    assert secret not in repr(client)

    with patch("anthropic.AsyncAnthropic"):
        try:
            create_llm_client("nope", api_key=secret)
        except ValueError as exc:
            assert secret not in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected a ValueError")


def test_the_supported_types_are_pinned() -> None:
    assert SUPPORTED_MODEL_TYPES == ("haiku",)


def test_the_agent_package_imports_nothing_from_the_server() -> None:
    """§2: the agent is a true external client, over HTTP/WS only."""
    offenders: list[str] = []
    for path in Path(llm_module.__file__).parent.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("server"):
                offenders.append(f"{path.name}: {node.module}")
            elif isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}: {a.name}" for a in node.names if a.name.startswith("server")
                ]
    assert not offenders, offenders
