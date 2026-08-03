"""Unit tests for CLI arg parsing and AgentSession.join_match (ARENA-058)."""

from __future__ import annotations

import json

import httpx
import pytest

from agent.agent import AgentSession, _parse_args
from agent.llm import LLMClient
from agent.profile import AgentProfile


def test_parse_args_accepts_documented_flags() -> None:
    args = _parse_args(
        [
            "--match-id",
            "m1",
            "--profile",
            "profiles/aggressive.yml",
            "--server-url",
            "http://example.test:9000",
            "--player-name",
            "Bob",
        ]
    )
    assert args.match_id == "m1"
    assert args.profile == "profiles/aggressive.yml"
    assert args.server_url == "http://example.test:9000"
    assert args.player_name == "Bob"


def test_parse_args_server_url_defaults() -> None:
    args = _parse_args(["--match-id", "m1", "--profile", "profiles/aggressive.yml"])
    assert args.server_url == "http://127.0.0.1:8000"
    assert args.player_name is None


def test_parse_args_missing_required_flag_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--profile", "profiles/aggressive.yml"])
    assert exc_info.value.code != 0


_PROFILE = AgentProfile(name="Tester", model_type="haiku", system_prompt="be terse")


class _StubLLMClient(LLMClient):
    async def generate_structured_response(self, prompt: str, schema: type) -> object:  # type: ignore[override]
        raise NotImplementedError


@pytest.mark.asyncio
async def test_join_match_posts_expected_body_and_returns_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"token": "tok-123"})

    session = AgentSession(
        "http://testserver", "m1", _PROFILE, llm_client=_StubLLMClient(), player_name="Tester"
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await session.join_match(client=client)

    assert token == "tok-123"
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/lobby/join"
    body = json.loads(requests[0].content)
    assert body == {"match_id": "m1", "player_name": "Tester"}
