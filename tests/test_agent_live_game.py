"""agent/agent.py -- chat + submit_move, memory recording, game_over (ARENA-095).

Against a real server. LLM is a scripted fake throughout -- zero network calls.

Every scenario plays a full game to natural completion (the server closes the room,
the client's async iterator ends on its own) rather than cancelling the agent's task
mid-game -- an artificial early teardown raced the server's own connection-handling
coroutine badly enough to corrupt a shared DB connection pool and, separately, to let
a second connection race ahead of the first's still-in-flight seat assignment. A game
played to its real end has none of that: termination is server-driven and
well-defined, not something the test has to orchestrate by hand.
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


def _persona() -> AgentProfile:
    return AgentProfile(
        name="Aggressor", model_type="haiku", temperature=0.9,
        system_prompt="You are aggressive.", memory_limit=10,
    )


async def _drive_events(session: AgentSession) -> None:
    assert session._ws is not None
    async for raw in session._ws:
        await session._handle_event(json.loads(raw))


async def _claim_seat_first(session: AgentSession) -> None:
    """Connects the agent (claiming X, since it connects first) without yet
    draining its event queue.

    websockets.connect() returning only means the WS handshake finished -- the
    server's handler is a separate coroutine that hasn't necessarily reached
    assign_symbol() (a DB write) yet. A short pause here lets it commit before a
    test opens a second (opponent) connection, which would otherwise sometimes
    race ahead and claim X for itself.

    Deliberately does NOT start _drive_events yet: on a fresh match `joined`
    already means "my turn", and the scripted LLM resolves instantly, so the
    agent would complete its entire first turn -- chat + submit_move and their
    broadcasts -- before the opponent even connects, and those broadcasts would
    go to nobody. The caller starts draining events only once the opponent's
    socket is registered to receive them.
    """
    await session.connect()
    await asyncio.sleep(0.05)


async def test_full_game_chat_ordering_memory_and_clean_exit(live_server: str) -> None:
    """One full game covers every ARENA-095 behaviour without any manual
    cancellation: chat sent before submit_move, both sides' moves and chat recorded
    into the agent's memory, and the agent's run loop exits cleanly on game_over."""
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        agent_token = await join_match(live_server, match_id, "Aggressor", client)
        opp_token = await join_match(live_server, match_id, "Opponent", client)

    # X (the agent, connects first) wins the top row: X0, O3, X1, O4, X2.
    llm = ScriptedLLMClient([
        AgentResponse(move=0, comment="opening"),
        AgentResponse(move=1, comment="pressing"),
        AgentResponse(move=2, comment="winning"),
    ])
    session = AgentSession(_persona(), llm, live_server, match_id, agent_token)
    await _claim_seat_first(session)

    async with websockets.connect(
        f"{live_server.replace('http', 'ws')}/ws/match/{match_id}?token={opp_token}"
    ) as opp_ws:
        opp_joined = json.loads(await opp_ws.recv())
        assert opp_joined["payload"]["symbol"] == "O"

        # Only now start the agent's event loop -- the opponent's socket is
        # already registered with the manager, so it is guaranteed to see the
        # broadcasts for the agent's first (immediate) move.
        run_task = asyncio.create_task(_drive_events(session))

        # Chat is sent before submit_move: the opponent sees chat_message first,
        # then the state_update for the same decision.
        first = json.loads(await asyncio.wait_for(opp_ws.recv(), timeout=5))
        second = json.loads(await asyncio.wait_for(opp_ws.recv(), timeout=5))
        assert first == {
            "event": "chat_message",
            "payload": {"sender": "Aggressor", "message": "opening"},
        }
        assert second["event"] == "state_update"
        assert second["payload"]["board"][0] == "X"

        await opp_ws.send(json.dumps({"action": "chat", "payload": {"message": "nice try"}}))
        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # echo of the opponent's own chat
        await opp_ws.send(json.dumps({"action": "submit_move", "payload": {"move": 3}}))
        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # state_update (O move 3)

        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # chat (X move 1)
        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # state_update (X move 1)
        await opp_ws.send(json.dumps({"action": "submit_move", "payload": {"move": 4}}))
        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # state_update (O move 4)

        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # chat (X move 2, winning)
        await asyncio.wait_for(opp_ws.recv(), timeout=5)  # state_update (X wins)
        game_over = json.loads(await asyncio.wait_for(opp_ws.recv(), timeout=5))
        assert game_over == {"event": "game_over", "payload": {"result": "X"}}

    # The agent's run loop ends cleanly once the server closes the room -- no
    # explicit cancellation needed, no exception raised.
    await asyncio.wait_for(run_task, timeout=5)
    assert run_task.exception() is None

    # Both sides' moves and chat landed in the agent's own memory.
    events = [(e.kind, e.sender, e.content) for e in session.memory.events()]
    assert ("chat", "Aggressor", "opening") in events
    assert ("move", "X", 0) in events
    assert ("chat", "Opponent", "nice try") in events
    assert ("move", "O", 3) in events
