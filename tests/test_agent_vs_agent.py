"""Agent-vs-agent end-to-end: two real AgentSessions, mocked LLM, full game
(ARENA-110, roadmap.md §v05.02 DoD, architecture.md §11).

Mirrors what scripts/run_arena.sh does in production (v04.02) -- two
independent AgentSessions, wired only through a real server, no direct
coupling between them -- but deterministic, free, and part of the default
suite: both sides' LLMClient is ScriptedLLMClient throughout, so this test
makes zero real calls to Anthropic.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from agent.agent import AgentSession, join_match
from agent.profile import AgentProfile
from agent.schemas import AgentResponse
from tests.conftest import ScriptedLLMClient


def _persona_x() -> AgentProfile:
    return AgentProfile(
        name="Aggressor", model_type="haiku", temperature=0.9,
        system_prompt="You are aggressive.", memory_limit=10,
    )


def _persona_o() -> AgentProfile:
    return AgentProfile(
        name="Sentinel", model_type="haiku", temperature=0.4,
        system_prompt="You are cautious.", memory_limit=10,
    )


async def _drive_events(session: AgentSession) -> None:
    assert session._ws is not None
    async for raw in session._ws:
        await session._handle_event(json.loads(raw))


async def _claim_seat(session: AgentSession) -> None:
    """Connects and lets seat assignment commit, without draining events yet
    -- the same discipline test_agent_live_game.py established: an
    AgentSession reacts to `joined` immediately if it's already its turn, so
    starting to drain before *both* sides are connected would let one side
    complete its whole first turn before the other is even registered to
    see the broadcast.
    """
    await session.connect()
    await asyncio.sleep(0.05)


async def test_two_agent_sessions_play_a_full_game_with_zero_model_calls(
    live_server: str,
) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token_x = await join_match(live_server, match_id, "Aggressor", client)
        token_o = await join_match(live_server, match_id, "Sentinel", client)

    # X (connects first) wins the top row: X0, O3, X1, O4, X2.
    llm_x = ScriptedLLMClient([
        AgentResponse(move=0, comment="opening"),
        AgentResponse(move=1, comment="pressing"),
        AgentResponse(move=2, comment="winning"),
    ])
    llm_o = ScriptedLLMClient([
        AgentResponse(move=3, comment="blocking"),
        AgentResponse(move=4, comment="holding"),
    ])

    session_x = AgentSession(_persona_x(), llm_x, live_server, match_id, token_x)
    session_o = AgentSession(_persona_o(), llm_o, live_server, match_id, token_o)

    # Both seats claimed (deterministic X/O via connection order -- see
    # architecture.md §5.2, no --symbol-style mechanism exists) before either
    # session starts reacting to events.
    await _claim_seat(session_x)
    await _claim_seat(session_o)

    task_x = asyncio.create_task(_drive_events(session_x))
    task_o = asyncio.create_task(_drive_events(session_o))

    # Neither run loop raises; both exit cleanly once the server closes the
    # room after game_over. A hang here (e.g. a stuck turn) fails the test
    # via the timeout rather than blocking indefinitely.
    await asyncio.wait_for(asyncio.gather(task_x, task_o), timeout=10)

    assert session_x.my_symbol == "X"
    assert session_o.my_symbol == "O"

    # Each session saw every move (its own and the opponent's) via the
    # broadcasts it's registered to receive as a live connection.
    x_moves = [(e.sender, e.content) for e in session_x.memory.events() if e.kind == "move"]
    o_moves = [(e.sender, e.content) for e in session_o.memory.events() if e.kind == "move"]
    expected = [("X", 0), ("O", 3), ("X", 1), ("O", 4), ("X", 2)]
    assert x_moves == expected
    assert o_moves == expected

    # Zero real model calls on either side -- confirmed by construction
    # (ScriptedLLMClient never touches the network) and by the exact script
    # length each side actually consumed.
    assert llm_x.calls == 3
    assert llm_o.calls == 2


async def test_observer_watches_an_agent_vs_agent_match_without_claiming_a_seat(
    live_server: str,
) -> None:
    """The DoD's illustrative scenario for v04's whole point: a human at /ui
    -> Observe watches two agents play. Exercised here at the protocol level
    -- app.js can't run in this suite, but the server-side guarantee
    (symbol:null, sees every broadcast, never asked to move) is the same
    contract v03.03's Observer hardening already pins; this test confirms it
    holds specifically while *both* seats are agent-held, not human-held.
    """
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token_x = await join_match(live_server, match_id, "Aggressor", client)
        token_o = await join_match(live_server, match_id, "Sentinel", client)
        observer_token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Watcher", "spectator": True},
        )).json()["token"]

    llm_x = ScriptedLLMClient([
        AgentResponse(move=0, comment="opening"),
        AgentResponse(move=1, comment="pressing"),
        AgentResponse(move=2, comment="winning"),
    ])
    llm_o = ScriptedLLMClient([
        AgentResponse(move=3, comment="blocking"),
        AgentResponse(move=4, comment="holding"),
    ])
    session_x = AgentSession(_persona_x(), llm_x, live_server, match_id, token_x)
    session_o = AgentSession(_persona_o(), llm_o, live_server, match_id, token_o)
    await _claim_seat(session_x)
    await _claim_seat(session_o)

    ws_base = live_server.replace("http", "ws")
    async with websockets.connect(f"{ws_base}/ws/match/{match_id}?token={observer_token}") as obs:
        joined = json.loads(await obs.recv())
        assert joined["payload"]["symbol"] is None  # never claims a seat

        task_x = asyncio.create_task(_drive_events(session_x))
        task_o = asyncio.create_task(_drive_events(session_o))

        # The observer sees the game to completion purely as a bystander.
        game_over = None
        while game_over is None:
            envelope = json.loads(await asyncio.wait_for(obs.recv(), timeout=10))
            if envelope["event"] == "game_over":
                game_over = envelope

        assert game_over["payload"]["result"] == "X"

    await asyncio.wait_for(asyncio.gather(task_x, task_o), timeout=10)
