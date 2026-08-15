"""agent/agent.py -- CLI args, join_match, AgentSession, WS connect (ARENA-093).

Against a real running server (the agent is a true external client), never
TestClient's in-process transport.
"""

from __future__ import annotations

import json

import httpx

from agent.agent import AgentSession, join_match, parse_args
from agent.llm import AnthropicHaikuClient
from agent.profile import AgentProfile


def test_parse_args_reads_required_and_optional_flags() -> None:
    args = parse_args([
        "--match-id", "m1",
        "--profile", "profiles/aggressive.yml",
        "--server-url", "http://example:9000",
        "--player-name", "Bob",
    ])
    assert args.match_id == "m1"
    assert args.profile == "profiles/aggressive.yml"
    assert args.server_url == "http://example:9000"
    assert args.player_name == "Bob"


def test_parse_args_defaults_server_url_and_player_name() -> None:
    args = parse_args(["--match-id", "m1", "--profile", "profiles/aggressive.yml"])
    assert args.server_url == "http://127.0.0.1:8000"
    assert args.player_name is None


async def test_join_match_returns_a_valid_token(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = await join_match(live_server, match_id, "Alice", client)
    assert isinstance(token, str) and token


async def test_agent_session_connects_and_stores_my_symbol(live_server: str) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = await join_match(live_server, match_id, "Alice", client)

    profile = AgentProfile(
        name="Aggressor", model_type="haiku", temperature=0.9,
        system_prompt="You are aggressive.", memory_limit=10,
    )
    llm_client = AnthropicHaikuClient(api_key="unused-in-this-test")
    session = AgentSession(profile, llm_client, live_server, match_id, token)
    await session.connect()
    assert session._ws is not None

    raw = await session._ws.recv()
    await session._handle_event(json.loads(raw))
    assert session.my_symbol in ("X", "O")
    await session._ws.close()
