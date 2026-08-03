"""Contract + unit tests pinning the LLMClient seam + AgentResponse schema (architecture.md §4.2,
§7.3). No LLM, no paid call.
"""

import inspect

import pydantic
import pytest

from agent.llm import LLMClient
from agent.schemas import AgentResponse


def test_agent_response_accepts_well_formed_input() -> None:
    response = AgentResponse(move=4, comment="taking the center")
    assert response.move == 4
    assert response.comment == "taking the center"


@pytest.mark.parametrize(
    "data",
    [
        {"move": "not-an-int", "comment": "x"},
        {"move": 4},  # missing comment
        {"comment": "x"},  # missing move
        {},
    ],
)
def test_agent_response_rejects_malformed_input(data: dict[str, object]) -> None:
    with pytest.raises(pydantic.ValidationError):
        AgentResponse(**data)  # type: ignore[arg-type]


def test_llm_client_is_abstract_and_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_llm_client_seam_signature_pinned() -> None:
    method = LLMClient.generate_structured_response
    assert inspect.iscoroutinefunction(method)
    signature = inspect.signature(method)
    assert list(signature.parameters) == ["self", "prompt", "schema"]
    assert signature.parameters["prompt"].annotation == str


def test_llm_client_defines_exactly_one_abstract_method() -> None:
    assert LLMClient.__abstractmethods__ == frozenset({"generate_structured_response"})


def test_concrete_subclass_is_instantiable() -> None:
    class EchoClient(LLMClient):
        async def generate_structured_response(self, prompt: str, schema: type[AgentResponse]) -> AgentResponse:  # type: ignore[override]
            return schema(move=0, comment=prompt)

    client = EchoClient()
    assert isinstance(client, LLMClient)
