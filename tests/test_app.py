"""Integration tests for the app gate: lifespan + health (architecture.md §3). Throwaway DB; no LLM."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/app.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:  # __enter__/__exit__ run the lifespan
        yield c


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_initializes_the_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/lifespan.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app):
        pass  # entering/exiting the context runs the lifespan, including init_models

    import asyncio

    async def _table_names() -> set[str]:
        async with engine.connect() as conn:
            return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))

    tables = asyncio.run(_table_names())
    assert {"matches", "participants", "moves", "chat_messages"} <= tables
