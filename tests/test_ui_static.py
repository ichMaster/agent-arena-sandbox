"""`/ui` mount + Cache-Control: no-store scoping (ARENA-097, architecture.md §3, §8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app


def test_ui_root_is_served_with_no_store() -> None:
    with TestClient(app) as client:
        resp = client.get("/ui/")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"


def test_non_ui_routes_do_not_carry_no_store() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "cache-control" not in {k.lower() for k in resp.headers}
