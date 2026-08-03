"""Integration tests for the /ui static mount + no-store middleware (ARENA-OPUS-SONNET-025). No LLM."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.database import create_engine, create_session_maker
from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/ui.db")
    app = create_app(db_engine=engine, session_maker=create_session_maker(engine))
    with TestClient(app) as c:
        yield c


def test_ui_index_served_with_no_store(client: TestClient) -> None:
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.headers.get("cache-control") == "no-store"


def test_ui_asset_carries_no_store(client: TestClient) -> None:
    resp = client.get("/ui/index.html")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-store"


def test_non_ui_route_keeps_normal_caching(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") != "no-store"


def test_prefixed_non_ui_path_not_no_store(client: TestClient) -> None:
    """A path merely prefixed '/ui' (not the mount itself) must not get no-store."""
    resp = client.get("/uixyz")
    assert resp.status_code == 404
    assert resp.headers.get("cache-control") != "no-store"
