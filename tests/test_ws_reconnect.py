"""End-to-end reconnect: a new connection reclaims a released seat (ARENA-108,
roadmap.md §v05.01 DoD, architecture.md §5.2, §10).

assign_symbol/release_seat already support this at the repository layer
(test_match.py::test_release_seat_frees_symbol_for_reassignment) -- this proves
it through the real WS endpoint end to end, not just the DB primitives.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import websockets

from server.database import async_session_maker
from server.repository import Repository


async def test_a_new_connection_with_the_same_token_reclaims_the_released_seat(
    live_server: str,
) -> None:
    async with httpx.AsyncClient() as client:
        match_id = (await client.post(f"{live_server}/api/v1/lobby/match")).json()["match_id"]
        token = (await client.post(
            f"{live_server}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": "Alice"},
        )).json()["token"]

    ws_base = live_server.replace("http", "ws")
    ws_url = f"{ws_base}/ws/match/{match_id}?token={token}"

    async with websockets.connect(ws_url) as ws1:
        first_joined = json.loads(await ws1.recv())
        first_symbol = first_joined["payload"]["symbol"]
    assert first_symbol in ("X", "O")

    # The disconnect above was a clean WS close -- confirm the seat was
    # actually released before reconnecting. Poll briefly rather than
    # asserting immediately: the client-side closing handshake completing
    # doesn't guarantee the server's own cleanup task has finished its DB
    # write yet (code review #1, v05.01).
    for _ in range(50):
        async with async_session_maker() as session:
            repo = Repository(session)
            participant = await repo.get_participant(match_id, token)
            assert participant is not None
            if participant.symbol is None:
                break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("seat was not released within the timeout")

    async with websockets.connect(ws_url) as ws2:
        second_joined = json.loads(await ws2.recv())
        second_symbol = second_joined["payload"]["symbol"]

    # Reclaimed through the live endpoint, not left seatless.
    assert second_symbol in ("X", "O")
    # Only one seat was ever taken (the same token, reconnecting) -- the
    # reclaimed symbol should be the same one, since nothing else claimed it
    # in between.
    assert second_symbol == first_symbol
