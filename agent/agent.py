"""The Agent Client -- a standalone CLI player (architecture.md §7.1).

A true external client: it imports nothing from ``server/`` and speaks only HTTP and
WebSocket, exactly as the Web UI does. The server pushes full turn state, so the agent
never round-trips to read the board -- it replies with one structured ``{move, comment}``
per turn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets
from anthropic import APIError
from pydantic import ValidationError

from agent.llm import LLMClient, LLMResponseError, MissingAPIKeyError, create_llm_client
from agent.memory import MemoryWindow
from agent.profile import AgentProfile, ProfileError
from agent.prompt import build_prompt
from agent.schemas import AgentResponse

#: How many times to ask the model for a legal move before giving up on it.
MAX_MOVE_ATTEMPTS = 3

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_PLAYER_NAME = "Agent"


async def decide_move(
    client: LLMClient,
    prompt: str,
    valid_moves: list[Any],
    rng: random.Random | None = None,
    attempts: int = MAX_MOVE_ATTEMPTS,
) -> tuple[Any, str]:
    """Ask the model for a legal move; fall back to a random legal one.

    The fallback is the point. A model that keeps naming occupied cells would otherwise
    stall the match forever -- the agent holds a seat, the opponent waits on a turn that
    never comes, and the game never reaches ``game_over``. Playing *some* legal move is
    always better than hanging, because the server is the authority on whether it was a
    good one.

    Any failure -- an unparseable reply, an SDK error -- counts as a failed attempt
    rather than crashing the session (v02.01 code review #2).
    """
    chooser = rng or random.Random()
    comment = ""
    for _ in range(attempts):
        try:
            reply: AgentResponse = await client.generate_structured_response(
                prompt, AgentResponse
            )
        except (LLMResponseError, ValidationError, httpx.HTTPError, APIError) as exc:
            # Narrow on purpose. A blanket `except Exception` here would swallow a
            # TypeError or AttributeError from our own code and report it as "the model
            # had a bad turn" -- the agent would keep playing random legal moves and the
            # real defect would never surface. These four are the failures a *model call*
            # genuinely produces: an unparseable reply, a schema violation, a transport
            # error, or an API error.
            print(f"[decide] attempt failed: {type(exc).__name__}", flush=True)
            continue
        comment = reply.comment or comment
        if reply.move in valid_moves:
            return reply.move, comment
    if not valid_moves:
        raise RuntimeError("no legal moves remain; the caller should not have asked")
    return chooser.choice(valid_moves), comment or "..."


@dataclass
class AgentSession:
    """One agent playing one match."""

    match_id: str
    profile: AgentProfile
    client: LLMClient
    server_url: str = DEFAULT_SERVER_URL
    player_name: str = DEFAULT_PLAYER_NAME
    rng: random.Random | None = None
    symbol: str | None = None
    memory: MemoryWindow = field(init=False)

    def __post_init__(self) -> None:
        self.memory = MemoryWindow(maxlen=self.profile.memory_limit)

    @property
    def ws_url(self) -> str:
        base = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        return f"{base}/ws/match/{self.match_id}"

    async def join(self) -> str:
        """Claim a participant token over REST."""
        async with httpx.AsyncClient(base_url=self.server_url, timeout=10) as http:
            response = await http.post(
                "/api/v1/lobby/join",
                json={"match_id": self.match_id, "player_name": self.player_name},
            )
            response.raise_for_status()
            token: str = response.json()["token"]
        return token

    async def play(self) -> str | None:
        """Play until the room closes. Returns the result if one was announced."""
        token = await self.join()
        result: str | None = None
        async with websockets.connect(f"{self.ws_url}?token={token}") as socket:
            async for raw in socket:
                message = json.loads(raw)
                event, payload = message.get("event"), message.get("payload", {})

                if event == "joined":
                    self.symbol = payload.get("symbol")
                    print(f"[{self.profile.name}] seated as {self.symbol}", flush=True)
                elif event == "chat_message":
                    if payload.get("sender") != self.player_name:
                        self.memory.record_chat(payload.get("sender", "?"), payload.get("message", ""))
                    continue
                elif event == "game_over":
                    result = payload.get("result")
                    print(f"[{self.profile.name}] game over: {result}", flush=True)
                    break
                elif event == "error":
                    print(f"[{self.profile.name}] error: {payload.get('detail')}", flush=True)
                    continue
                elif event == "state_update":
                    last = payload.get("last_move") or {}
                    if last and last.get("player") != self.symbol:
                        self.memory.record_move(str(last.get("player")), last.get("move"))
                elif event != "joined":
                    continue

                await self._act_if_my_turn(socket, payload)
        return result

    async def _act_if_my_turn(self, socket: Any, payload: dict[str, Any]) -> None:
        """Act only when the pushed state says it is our turn.

        "Your turn" is a derived condition, never an event (§6.2, §13). The terminal
        ``state_update`` carries ``current_turn: null``, so this check is also what stops
        the agent acting into a room that is about to close.
        """
        if self.symbol is None or payload.get("current_turn") != self.symbol:
            return
        valid_moves = list(payload.get("valid_moves") or [])
        if not valid_moves:
            return

        prompt = build_prompt(
            self.memory, list(payload.get("board") or []), valid_moves, self.profile.system_prompt
        )
        move, comment = await decide_move(self.client, prompt, valid_moves, self.rng)
        print(f"[{self.profile.name}] plays {move}: {comment}", flush=True)

        if comment:
            await socket.send(json.dumps({"action": "chat", "payload": {"message": comment}}))
        await socket.send(json.dumps({"action": "submit_move", "payload": {"move": move}}))
        self.memory.record_move(self.symbol, move)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="Play a match as an LLM agent.")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--player-name", default=None)
    return parser


async def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = AgentProfile.load_from_yaml(args.profile)
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr, flush=True)
        return 2
    try:
        client = create_llm_client(profile.model_type, temperature=profile.temperature)
    except MissingAPIKeyError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 3

    session = AgentSession(
        match_id=args.match_id,
        profile=profile,
        client=client,
        server_url=args.server_url,
        player_name=args.player_name or profile.name,
    )
    await session.play()
    return 0


def main(argv: list[str] | None = None) -> int:
    # Line-buffered so a redirected log flushes as the game plays, not at exit --
    # watching an agent-vs-agent match through `tee` is how this gets debugged.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(line_buffering=True)
    return asyncio.run(run(argv))


if __name__ == "__main__":  # pragma: no cover - the direct-run shim
    # Running `python agent/agent.py` puts agent/ on sys.path, not the repo root, so the
    # package imports above would fail without this.
    if __package__ in (None, ""):
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.exit(main())
