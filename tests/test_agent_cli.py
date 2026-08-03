"""Unit/integration tests for the agent CLI scaffolding (args, .env, join). No paid call.

`join_match` runs against the REAL server app via an in-process ASGI transport — no network.
"""

from pathlib import Path

import httpx
import pytest

from agent.agent import join_match, load_environment, parse_args
from server.database import create_engine, create_session_maker, init_models
from server.main import create_app


def test_parse_args_full() -> None:
    args = parse_args(
        ["--match-id", "m1", "--profile", "profiles/aggressive.yml",
         "--server-url", "http://h:9", "--player-name", "Bot"]
    )
    assert (args.match_id, args.profile, args.server_url, args.player_name) == (
        "m1", "profiles/aggressive.yml", "http://h:9", "Bot"
    )


def test_parse_args_defaults() -> None:
    args = parse_args(["--match-id", "m1", "--profile", "p.yml"])
    assert args.server_url == "http://127.0.0.1:8000"
    assert args.player_name is None


def test_parse_args_missing_required() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--profile", "p.yml"])  # no --match-id


def test_load_environment_reads_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    assert load_environment(env_file) == "sk-from-dotenv"


def test_load_environment_missing_key_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        load_environment(tmp_path / "absent.env")


async def test_join_match_against_real_app(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/cli.db")
    await init_models(engine)  # ASGITransport skips lifespan; create the schema explicitly
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://arena") as client:
        match_id = (await client.post("/api/v1/lobby/match")).json()["match_id"]
        token = await join_match("http://arena", match_id, "Ironclaw", client=client)
        assert token  # a seat-bearing participant id

        with pytest.raises(RuntimeError, match="not found"):
            await join_match("http://arena", "no-such-match", "Ironclaw", client=client)
    await engine.dispose()
