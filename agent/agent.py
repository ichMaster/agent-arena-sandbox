"""agent/agent.py — the CLI entrypoint and AgentSession (architecture.md §7.1).

A pure external client: imports nothing from server/, talks only over HTTP/WS. The WS
event loop lands in ARENA-059; this issue only wires arg parsing and the REST join.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from agent.llm import LLMClient, create_llm_client
from agent.memory import MemoryWindow
from agent.profile import AgentProfile


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
    asyncio.run(session.join_match())


if __name__ == "__main__":
    main()
