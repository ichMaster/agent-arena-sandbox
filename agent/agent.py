"""The agent CLI entrypoint and AgentSession (architecture.md §7.1).

A true external client: imports nothing from server/, talks only over HTTP/WS.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

from agent.llm import LLMClient, create_llm_client
from agent.memory import MemoryWindow
from agent.profile import AgentProfile
from agent.prompt import build_prompt
from agent.schemas import AgentResponse

#: If the model can't produce a legal move in this many tries, fall back to a
#: random legal one rather than stalling the match (architecture.md §7.1).
MAX_MOVE_ATTEMPTS = 3


@dataclass(frozen=True)
class AgentArgs:
    match_id: str
    profile: str
    server_url: str
    player_name: str | None


def parse_args(argv: list[str] | None = None) -> AgentArgs:
    parser = argparse.ArgumentParser(description="AgentArena CLI agent")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--profile", required=True, help="path to a profile YAML file")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--player-name", default=None)
    ns = parser.parse_args(argv)
    return AgentArgs(
        match_id=ns.match_id,
        profile=ns.profile,
        server_url=ns.server_url,
        player_name=ns.player_name,
    )


async def join_match(
    server_url: str, match_id: str, player_name: str, http_client: httpx.AsyncClient
) -> str:
    resp = await http_client.post(
        f"{server_url}/api/v1/lobby/join",
        json={"match_id": match_id, "player_name": player_name},
    )
    resp.raise_for_status()
    token: str = resp.json()["token"]
    return token


def _ws_url(server_url: str, match_id: str, token: str) -> str:
    ws_base = server_url.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_base}/ws/match/{match_id}?token={token}"


class AgentSession:
    """Holds the profile, the LLMClient, a MemoryWindow, and the live WS connection."""

    def __init__(
        self,
        profile: AgentProfile,
        llm_client: LLMClient,
        server_url: str,
        match_id: str,
        token: str,
    ) -> None:
        self.profile = profile
        self.llm_client = llm_client
        self.memory = MemoryWindow(maxlen=profile.memory_limit)
        self.server_url = server_url
        self.match_id = match_id
        self.token = token
        self.my_symbol: str | None = None
        self._ws: websockets.ClientConnection | None = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(_ws_url(self.server_url, self.match_id, self.token))

    async def run(self) -> None:
        """Connect, then dispatch every event until the connection closes."""
        await self.connect()
        assert self._ws is not None
        async for raw in self._ws:
            await self._handle_event(json.loads(raw))

    async def decide(self, board: list[Any], valid_moves: list[Any]) -> AgentResponse:
        """Prompt -> LLMClient -> validate -> retry -> fallback to a random legal move.

        Never stalls the match: MAX_MOVE_ATTEMPTS exhausted means a legal move is
        chosen for the model, not that the turn is skipped.
        """
        for _attempt in range(MAX_MOVE_ATTEMPTS):
            prompt = build_prompt(self.memory, board, valid_moves, self.profile)
            response = await self.llm_client.generate_structured_response(prompt, AgentResponse)
            if response.move in valid_moves:
                return response
        fallback_move = random.choice(valid_moves)
        return AgentResponse(move=fallback_move, comment="(taking a legal move)")

    async def _handle_event(self, envelope: dict[str, Any]) -> None:
        event = envelope.get("event")
        payload = envelope.get("payload") or {}
        if event == "joined":
            self.my_symbol = payload.get("symbol")
            print(f"[{self.profile.name}] joined as {self.my_symbol}", flush=True)

        if event in ("joined", "state_update"):
            current_turn = payload.get("current_turn")
            if self.my_symbol is not None and current_turn == self.my_symbol:
                board = payload.get("board", [])
                valid_moves = payload.get("valid_moves", [])
                response = await self.decide(board, valid_moves)
                print(
                    f"[{self.profile.name}] move={response.move}: {response.comment}",
                    flush=True,
                )
                # Sending chat + submit_move lands in ARENA-095.
        # chat_message / game_over handling lands in ARENA-095.


async def main(args: AgentArgs) -> None:
    profile = AgentProfile.load_from_yaml(args.profile)
    player_name = args.player_name or profile.name
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    llm_client = create_llm_client(profile.model_type, api_key, profile.temperature)

    async with httpx.AsyncClient() as http_client:
        token = await join_match(args.server_url, args.match_id, player_name, http_client)

    session = AgentSession(profile, llm_client, args.server_url, args.match_id, token)
    await session.run()
