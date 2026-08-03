"""ARENA-026/027/028 -- the decision step, the event loop, and the CLI.

**The LLMClient is mocked in every test.** Zero paid calls.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.agent import (
    MAX_MOVE_ATTEMPTS,
    AgentSession,
    build_parser,
    decide_move,
    main,
    run,
)
from agent.llm import LLMClient
from agent.profile import AgentProfile
from agent.schemas import AgentResponse
from server.main import API_PREFIX, app

PROFILE = Path(__file__).resolve().parent.parent / "profiles" / "aggressive.yml"


class ScriptedClient(LLMClient):
    """A mocked model: returns queued replies, then repeats the last one."""

    def __init__(self, *replies: AgentResponse | Exception) -> None:
        self.queue = list(replies)
        self.calls = 0

    async def generate_structured_response(self, prompt: str, schema: type[Any]) -> Any:
        self.calls += 1
        reply = self.queue.pop(0) if len(self.queue) > 1 else (self.queue[0] if self.queue else None)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise RuntimeError("no scripted reply")
        return reply


# -- ARENA-026: decide_move ------------------------------------------------


async def test_a_legal_first_answer_is_used() -> None:
    client = ScriptedClient(AgentResponse(move=4, comment="centre"))
    move, comment = await decide_move(client, "p", [0, 4, 8])
    assert (move, comment, client.calls) == (4, "centre", 1)


async def test_an_illegal_answer_is_retried() -> None:
    client = ScriptedClient(
        AgentResponse(move=99, comment="nope"), AgentResponse(move=0, comment="ok")
    )
    move, _ = await decide_move(client, "p", [0, 4])
    assert (move, client.calls) == (0, 2)


async def test_it_falls_back_to_a_random_legal_move() -> None:
    """An agent that gives up holds a seat forever and the match never ends."""
    client = ScriptedClient(AgentResponse(move=99, comment="wrong"))
    move, _ = await decide_move(client, "p", [1, 5, 7], rng=random.Random(0))
    assert move in {1, 5, 7}
    assert client.calls == MAX_MOVE_ATTEMPTS


async def test_the_fallback_is_always_a_legal_move() -> None:
    client = ScriptedClient(AgentResponse(move=-1, comment="x"))
    for seed in range(20):
        move, _ = await decide_move(client, "p", [2, 6], rng=random.Random(seed))
        assert move in {2, 6}


async def test_a_client_failure_counts_as_a_failed_attempt() -> None:
    """v02.01 review #2: an SDK error must not end the match."""
    client = ScriptedClient(RuntimeError("429"), AgentResponse(move=3, comment="after"))
    move, _ = await decide_move(client, "p", [3, 4])
    assert move == 3


async def test_total_failure_still_yields_a_legal_move() -> None:
    client = ScriptedClient(RuntimeError("down"))
    move, comment = await decide_move(client, "p", [8], rng=random.Random(1))
    assert move == 8 and comment


async def test_it_refuses_when_there_are_no_legal_moves() -> None:
    with pytest.raises(RuntimeError, match="no legal moves"):
        await decide_move(ScriptedClient(AgentResponse(move=0, comment="x")), "p", [])


# -- ARENA-027 / 028: the session and CLI ----------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARENA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'ag.db'}")
    with TestClient(app) as c:
        yield c


def test_the_parser_takes_the_documented_flags() -> None:
    args = build_parser().parse_args(
        ["--match-id", "m", "--profile", "p.yml", "--server-url", "http://x", "--player-name", "N"]
    )
    assert (args.match_id, args.profile, args.server_url, args.player_name) == (
        "m", "p.yml", "http://x", "N")


def test_match_id_and_profile_are_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--match-id", "m"])


def test_a_bad_profile_path_exits_naming_the_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert asyncio.run(run(["--match-id", "m", "--profile", "/nope/absent.yml"])) == 2
    assert "absent.yml" in capsys.readouterr().err


def test_a_missing_key_aborts_before_connecting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert asyncio.run(run(["--match-id", "m", "--profile", str(PROFILE)])) == 3
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_stdout_is_line_buffered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirected log must flush as the game plays, not at exit."""
    seen: list[bool] = []
    monkeypatch.setattr(sys.stdout, "reconfigure", lambda **kw: seen.append(kw["line_buffering"]))
    monkeypatch.setattr(sys.stderr, "reconfigure", lambda **kw: seen.append(kw["line_buffering"]))
    monkeypatch.setattr("agent.agent.asyncio.run", lambda coro: (coro.close(), 0)[1])
    assert main(["--match-id", "m", "--profile", str(PROFILE)]) == 0
    assert seen == [True, True]


def test_the_direct_run_shim_is_present() -> None:
    """`python agent/agent.py` puts agent/ on sys.path, not the repo root."""
    source = Path(__file__).resolve().parent.parent / "agent" / "agent.py"
    text = source.read_text(encoding="utf-8")
    assert '__package__ in (None, "")' in text
    assert "sys.path.insert" in text


def test_the_session_derives_its_ws_url() -> None:
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(
        match_id="m1", profile=profile, client=ScriptedClient(), server_url="http://h:8000"
    )
    assert session.ws_url == "ws://h:8000/ws/match/m1"


def test_the_session_sizes_memory_from_the_profile() -> None:
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(match_id="m", profile=profile, client=ScriptedClient())
    assert session.memory.maxlen == profile.memory_limit


async def test_it_acts_only_on_its_own_turn() -> None:
    """The turn is derived from state, never a separate event (§6.2)."""
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(match_id="m", profile=profile, client=ScriptedClient(
        AgentResponse(move=0, comment="mine")))
    session.symbol = "X"
    sent: list[str] = []

    class Sock:
        async def send(self, data: str) -> None:
            sent.append(data)

    await session._act_if_my_turn(Sock(), {"current_turn": "O", "board": [None] * 9,
                                           "valid_moves": [0, 1]})
    assert sent == [], "it must not act on the opponent's turn"

    await session._act_if_my_turn(Sock(), {"current_turn": "X", "board": [None] * 9,
                                           "valid_moves": [0, 1]})
    actions = [json.loads(s)["action"] for s in sent]
    assert actions == ["chat", "submit_move"]


async def test_it_never_acts_on_the_terminal_update() -> None:
    """The final state_update carries current_turn: null -- the room is closing."""
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(match_id="m", profile=profile, client=ScriptedClient(
        AgentResponse(move=0, comment="x")))
    session.symbol = "X"
    sent: list[str] = []

    class Sock:
        async def send(self, data: str) -> None:
            sent.append(data)

    await session._act_if_my_turn(Sock(), {"current_turn": None, "board": [None] * 9,
                                           "valid_moves": []})
    assert sent == []


async def test_it_records_the_opponent_and_its_own_move() -> None:
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(match_id="m", profile=profile, client=ScriptedClient(
        AgentResponse(move=1, comment="ha")))
    session.symbol = "X"

    class Sock:
        async def send(self, data: str) -> None:
            return None

    await session._act_if_my_turn(Sock(), {"current_turn": "X", "board": [None] * 9,
                                           "valid_moves": [1]})
    assert session.memory.render() == ["X played: 1"]


def test_the_agent_joins_a_real_match_over_rest(client: TestClient) -> None:
    """The join half of the loop, against the real server."""
    match_id = client.post(f"{API_PREFIX}/lobby/match").json()["match_id"]
    profile = AgentProfile.load_from_yaml(PROFILE)
    session = AgentSession(
        match_id=match_id, profile=profile, client=ScriptedClient(),
        server_url=str(client.base_url),
    )
    response = client.post(
        f"{API_PREFIX}/lobby/join",
        json={"match_id": session.match_id, "player_name": session.player_name},
    )
    assert response.status_code == 200 and response.json()["token"]
