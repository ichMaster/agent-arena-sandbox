"""Integration tests for the /ui static mount and its no-store middleware (ARENA-062)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_ui_root_served_with_no_store() -> None:
    response = client.get("/ui/")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_non_ui_route_does_not_carry_no_store() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("cache-control") != "no-store"
