"""Agent Client CLI — joins a match over REST and plays it over one WebSocket (architecture §7.1).

A pure external client: imports nothing from ``server/`` and talks HTTP/WS only, exactly like the
Web UI. The model is reached solely through the ``LLMClient`` seam (always mocked in tests);
``ANTHROPIC_API_KEY`` lives in this process's environment / ``.env`` and is never sent to the
server (§9). Reasoning is printed to line-buffered stdout — read-only observability (§3.2).
"""

import sys
from pathlib import Path

if not __package__:  # direct-run shim: `python agent/agent.py ...` from the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from typing import Any, Final  # noqa: E402

import httpx  # noqa: E402
import websockets  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agent.llm import LLMClient, create_llm_client, load_api_key  # noqa: E402
from agent.memory import MemoryWindow  # noqa: E402
from agent.profile import AgentProfile  # noqa: E402
from agent.prompt import build_prompt  # noqa: E402
from agent.schemas import AgentResponse  # noqa: E402

MAX_MOVE_ATTEMPTS: Final = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentArena agent client (Anthropic Haiku)")
    parser.add_argument("--match-id", required=True, help="the match to join (from the lobby)")
    parser.add_argument("--profile", required=True, help="path to a persona profile YAML")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--player-name", default=None, help="defaults to the profile's name")
    return parser.parse_args(argv)


def load_environment(dotenv_path: str | Path | None = None) -> str:
    """Load ``.env`` then the fail-fast key read — the secret stays here (§9)."""
    load_dotenv(dotenv_path)
    return load_api_key()


async def join_match(
    server_url: str, match_id: str, player_name: str, *, client: httpx.AsyncClient | None = None
) -> str:
    """``POST /lobby/join`` → the seat-bearing token; a clear error if the match is unknown."""
    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient()
    try:
        response = await http.post(
            f"{server_url}/api/v1/lobby/join",
            json={"match_id": match_id, "player_name": player_name},
        )
        if response.status_code == 404:
            raise RuntimeError(f"match {match_id!r} not found on {server_url}")
        response.raise_for_status()
        return str(response.json()["token"])
    finally:
        if owns_client:
            await http.aclose()


async def choose_move(
    llm: LLMClient,
    memory: MemoryWindow,
    board: list[str],
    valid_moves: list[int],
    persona: str,
) -> tuple[int, str]:
    """Decide → validate → retry (≤ ``MAX_MOVE_ATTEMPTS``) → random-legal fallback (§7.1).

    An illegal, unparseable, or erroring model reply counts as a failed attempt; each retry tells
    the model why the previous choice was rejected. On exhaustion the agent plays a random *legal*
    move rather than stalling the match.
    """
    prompt = build_prompt(memory, board, valid_moves, persona)
    for attempt in range(1, MAX_MOVE_ATTEMPTS + 1):
        try:
            reply = await llm.generate_structured_response(prompt, AgentResponse)
        except Exception as exc:  # a model/validation failure is a failed attempt, never a stall
            print(f"[agent] model error on attempt {attempt}: {exc}")
            continue
        if reply.move in valid_moves:
            print(f"[agent] move {reply.move} — {reply.comment}")
            return reply.move, reply.comment
        print(f"[agent] illegal move {reply.move} on attempt {attempt}; retrying")
        prompt = (  # feed the rejection back so the retry isn't a blind re-roll
            f"{prompt}\n\nYour previous choice {reply.move} was rejected as illegal. "
            "Choose strictly from the legal moves listed above."
        )
    move = random.choice(valid_moves)
    print(f"[agent] falling back to a random legal move: {move}")
    return move, "Switching it up."


class AgentSession:
    """One agent over one WebSocket — the transport-free event core (§7.1).

    Acts only when ``current_turn == my symbol`` (never on the terminal ``state_update``, whose
    ``current_turn`` is ``null``); records opponent moves and others' chat into the memory window;
    answers each of its own turns with ``[chat, submit_move]``.
    """

    def __init__(self, profile: AgentProfile, llm: LLMClient, memory: MemoryWindow) -> None:
        self.profile = profile
        self._llm = llm
        self._memory = memory
        self.symbol: str | None = None
        self.finished = False

    async def on_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        name = event.get("event")
        raw_payload = event.get("payload")
        payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}

        if name == "joined":
            symbol = payload.get("symbol")
            self.symbol = symbol if isinstance(symbol, str) else None
            print(f"[agent] joined as {self.symbol}")
            return await self._maybe_move(payload)
        if name == "state_update":
            last = payload.get("last_move")
            if isinstance(last, dict) and last.get("player") != self.symbol:
                self._memory.record_move(str(last.get("player")), last.get("move"))
            return await self._maybe_move(payload)
        if name == "chat_message":
            if payload.get("sender") != self.symbol:
                self._memory.record_chat(str(payload.get("sender")), str(payload.get("message", "")))
            return []
        if name == "game_over":
            self.finished = True
            print(f"[agent] game over: {payload.get('result')}")
            return []
        if name == "error":
            print(f"[agent] server error: {payload.get('detail')}")
            return []
        return []

    async def _maybe_move(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if self.symbol is None or payload.get("current_turn") != self.symbol:
            return []  # not my turn — including the terminal update (current_turn: null)
        board = [str(cell) for cell in payload.get("board", [])]
        valid_moves = [int(move) for move in payload.get("valid_moves", [])]
        if not valid_moves:
            return []
        move, comment = await choose_move(
            self._llm, self._memory, board, valid_moves, self.profile.system_prompt
        )
        return [
            {"action": "chat", "payload": {"message": comment}},
            {"action": "submit_move", "payload": {"move": move}},
        ]


async def run_agent(
    server_url: str, match_id: str, player_name: str, profile: AgentProfile, llm: LLMClient
) -> None:
    """Join over REST, then drive one ``AgentSession`` over the WS until the room closes (§7.1)."""
    token = await join_match(server_url, match_id, player_name)
    session = AgentSession(profile, llm, MemoryWindow(profile.memory_limit))
    ws_base = server_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    url = f"{ws_base}/ws/match/{match_id}?token={token}"
    try:
        async with websockets.connect(url) as socket:
            async for raw in socket:
                event = json.loads(raw)
                for action in await session.on_event(event):
                    await socket.send(json.dumps(action))
                if session.finished:
                    break
    except websockets.ConnectionClosed:
        pass  # the server closes the room after game_over — a clean exit
    print("[agent] connection closed; exiting")


def _line_buffer_stdio() -> None:
    """Line-buffer stdout/stderr so redirected agent logs flush promptly (§7.1)."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(line_buffering=True)


def main(argv: list[str] | None = None) -> None:
    _line_buffer_stdio()
    args = parse_args(argv)
    api_key = load_environment()
    profile = AgentProfile.load_from_yaml(args.profile)
    llm = create_llm_client(profile.model_type, api_key, profile.temperature)
    player_name = args.player_name or profile.name
    print(f"[agent] {profile.name} heading into match {args.match_id}")
    asyncio.run(run_agent(args.server_url, args.match_id, player_name, profile, llm))


if __name__ == "__main__":
    main()
