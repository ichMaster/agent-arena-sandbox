"""agent/agent.py — the CLI entrypoint and AgentSession (architecture.md §7.1).

A pure external client: imports nothing from server/, talks only over HTTP/WS.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from typing import Any

import httpx
import websockets
from websockets import ClientConnection

from agent.llm import LLMClient, create_llm_client
from agent.memory import MemoryWindow
from agent.profile import AgentProfile
from agent.prompt import build_prompt
from agent.schemas import AgentResponse

MAX_MOVE_ATTEMPTS = 3


class AgentSession:
    def __init__(
        self,
        server_url: str,
        match_id: str,
        profile: AgentProfile,
        llm_client: LLMClient,
        player_name: str | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.match_id = match_id
        self.profile = profile
        self.llm_client = llm_client
        self.player_name = player_name or profile.name
        self.memory = MemoryWindow(maxlen=profile.memory_limit)
        self.symbol: str | None = None

    async def join_match(self, client: httpx.AsyncClient | None = None) -> str:
        """``client`` is injectable so tests can supply a mocked transport."""
        owns_client = client is None
        http_client = client or httpx.AsyncClient()
        try:
            response = await http_client.post(
                f"{self.server_url}/api/v1/lobby/join",
                json={"match_id": self.match_id, "player_name": self.player_name},
            )
            response.raise_for_status()
            token: str = response.json()["token"]
            return token
        finally:
            if owns_client:
                await http_client.aclose()

    async def run(self) -> None:
        token = await self.join_match()
        ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        async with websockets.connect(f"{ws_url}/ws/match/{self.match_id}?token={token}") as ws:
            async for raw in ws:
                envelope = json.loads(raw)
                await self._handle_event(ws, envelope)

    async def _handle_event(self, ws: ClientConnection, envelope: dict[str, Any]) -> None:
        event = envelope.get("event")
        payload = envelope.get("payload") or {}

        if event == "joined":
            self.symbol = payload.get("symbol")
        elif event == "chat_message":
            sender = payload.get("sender", "")
            if sender != self.player_name:
                self.memory.record_chat(sender, payload.get("message", ""))
            return
        elif event == "state_update":
            last_move = payload.get("last_move")
            if last_move and last_move.get("player") != self.symbol:
                self.memory.record_move(last_move["player"], last_move["move"])
        elif event == "game_over":
            print(f"[{self.player_name}] game over: {payload.get('result')}", flush=True)
            return
        else:
            return

        if self.symbol is not None and payload.get("current_turn") == self.symbol:
            await self._take_turn(ws, payload)

    async def _take_turn(self, ws: ClientConnection, payload: dict[str, Any]) -> None:
        board = payload["board"]
        valid_moves = payload["valid_moves"]
        prompt = build_prompt(self.memory, board, valid_moves, self.profile)
        move, comment = await self.decide_move(prompt, valid_moves)

        assert self.symbol is not None
        self.memory.record_move(self.symbol, move)

        print(f"[{self.player_name}] playing {move}: {comment}", flush=True)
        await ws.send(json.dumps({"action": "chat", "payload": {"message": comment}}))
        await ws.send(json.dumps({"action": "submit_move", "payload": {"move": move}}))

    async def decide_move(self, prompt: str, valid_moves: list[int]) -> tuple[int, str]:
        """Re-prompt on an illegal move up to MAX_MOVE_ATTEMPTS; fall back to a random
        legal move on exhaustion rather than stalling the match (architecture.md §7.1)."""
        for attempt in range(1, MAX_MOVE_ATTEMPTS + 1):
            response = await self.llm_client.generate_structured_response(prompt, AgentResponse)
            if response.move in valid_moves:
                return response.move, response.comment
            print(
                f"[{self.player_name}] illegal move {response.move} "
                f"(attempt {attempt}/{MAX_MOVE_ATTEMPTS}), retrying",
                flush=True,
            )

        fallback = random.choice(valid_moves)
        print(f"[{self.player_name}] out of attempts, falling back to {fallback}", flush=True)
        return fallback, "..."


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentArena agent client")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--player-name", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    args = _parse_args(argv)
    profile = AgentProfile.load_from_yaml(args.profile)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    llm_client = create_llm_client(profile.model_type, api_key, profile.temperature)

    session = AgentSession(
        args.server_url, args.match_id, profile, llm_client, args.player_name
    )
    asyncio.run(session.run())


if __name__ == "__main__":
    main()
