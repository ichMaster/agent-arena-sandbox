"""TRK-019 / TRK-020 / TRK-021 — the dashboard server, its frames, and the palette.

The load-bearing test is the first: the dashboard must serve with the entire generated
application absent, because that is its normal state between runs. A dashboard that
needs the tree it is watching would be deleted by the process it exists to observe.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import gen_log
from tracker import paths

fastapi = pytest.importorskip("fastapi", reason="dashboard deps are optional (requirements.txt)")
from fastapi.testclient import TestClient  # noqa: E402

from dashboard import server  # noqa: E402

STATIC = paths.codegen_root() / "dashboard" / "static"


@pytest.fixture
def seeded(isolated_runs_dir: Path) -> str:
    run_id = gen_log.RUN_ID
    paths.events_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    paths.events_path(run_id).write_text(gen_log.preset("clean-run"), encoding="utf-8")
    paths.current_pointer().write_text(run_id, encoding="utf-8")
    return run_id


# ── independence from the generated application ──────────────────────────────


def test_the_dashboard_imports_nothing_from_the_generated_app() -> None:
    """server/, games/, agent/ may not exist. Asserted over the source, not by trying."""
    offenders: list[str] = []
    for path in (paths.codegen_root()).rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for module in ("server.", "games.", "agent.", "web."):
            if re.search(rf"^\s*(from|import)\s+{re.escape(module)}", text, re.MULTILINE):
                offenders.append(f"{path.name}: {module}")
    assert not offenders, offenders


def test_it_serves_with_the_application_tree_absent(seeded: str) -> None:
    for directory in ("server", "games", "agent", "web"):
        assert not (paths.codegen_root().parent / directory).exists(), (
            f"{directory}/ exists; this test is meant to run without it"
        )
    with TestClient(server.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/state").status_code == 200


def test_it_uses_its_own_port_never_the_apps() -> None:
    assert server.PORT == 8420, "8000 belongs to the generated app; both may run at once"


# ── state and frames ─────────────────────────────────────────────────────────


def test_api_state_returns_the_reduced_run(seeded: str) -> None:
    with TestClient(server.app) as client:
        payload = client.get("/api/state").json()
    assert payload["run_id"] == seeded
    assert payload["metrics"]["issues_done"] == 7
    assert payload["status"] == "done"


def test_api_state_is_sane_when_no_run_exists(isolated_runs_dir: Path) -> None:
    with TestClient(server.app) as client:
        payload = client.get("/api/state").json()
    assert payload["status"] == "no-runs"
    assert payload["tree"] == []


def test_websocket_sends_a_snapshot_first(seeded: str) -> None:
    with TestClient(server.app) as client, client.websocket_connect("/ws") as ws:
        frame = ws.receive_json()
    assert frame["kind"] == "snapshot"
    assert frame["state"]["run_id"] == seeded


def test_frame_shape_matches_the_specification(seeded: str) -> None:
    """dashboard-specification §6.1: {kind, state, event?} and nothing else."""
    with TestClient(server.app) as client, client.websocket_connect("/ws") as ws:
        frame = ws.receive_json()
    assert set(frame) <= {"kind", "state", "event"}
    assert frame["kind"] in {"snapshot", "delta"}


def test_a_client_connecting_late_converges_to_the_same_state(seeded: str) -> None:
    """Reconnect re-requests a snapshot, so no per-client cursor is needed (§6.2)."""
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as first:
            early = first.receive_json()["state"]
        with client.websocket_connect("/ws") as second:
            late = second.receive_json()["state"]
    assert early["metrics"] == late["metrics"]
    assert early["tree"] == late["tree"]


def test_api_runs_lists_runs(seeded: str) -> None:
    with TestClient(server.app) as client:
        payload = client.get("/api/runs").json()
    assert seeded in payload["runs"]
    assert payload["active"] == seeded


# ── the static bundle ────────────────────────────────────────────────────────


def test_the_ui_is_split_into_three_files_with_no_build_step() -> None:
    for name in ("index.html", "app.js", "styles.css"):
        assert (STATIC / name).is_file(), name


def test_no_external_requests_anywhere_in_the_bundle() -> None:
    """A strict reading of containment: the page must work offline."""
    for name in ("index.html", "app.js", "styles.css"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, name
        assert "cdn" not in text.lower(), name


def test_the_page_references_only_local_assets() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for match in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert match.startswith("/static/"), match


def test_app_js_is_valid_javascript() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    result = subprocess.run(
        [node, "--check", str(STATIC / "app.js")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_every_chart_has_a_table_view_toggle() -> None:
    """The WCAG-clean twin is not optional on any panel (spec §4.9)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    charts = set(re.findall(r'id="c-(\w+)"', html))
    tables = set(re.findall(r'id="tv-(\w+)"', html))
    assert charts and charts == tables, (charts, tables)


def test_reduced_motion_and_focus_rings_are_honoured() -> None:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
    assert "focus-visible" in css
    assert "outline:none" not in css.replace(" ", "")


# ── TRK-021: the palette must stay validated ─────────────────────────────────

VALIDATOR = Path(
    "/private/tmp/claude-502/bundled-skills/2.1.220/"
    "a580c4f332c8630ce8703970b2ee2a79/dataviz/scripts/validate_palette.js"
)


def _series(mode: str) -> list[str]:
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    block = css.split(':root[data-theme="dark"]')[1] if mode == "dark" else css.split("@media")[0]
    found = dict(re.findall(r"--series-(\d):\s*(#[0-9a-fA-F]{6})", block))
    return [found[str(i)] for i in sorted(found) if i in "12345"]


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_shipped_palette_still_passes_the_validator(mode: str) -> None:
    """A colour tweak must not silently break CVD safety."""
    series = _series(mode)
    assert len(series) == 5, f"expected 5 series slots in {mode}, got {series}"
    node = shutil.which("node")
    if not node or not VALIDATOR.is_file():
        pytest.skip("palette validator unavailable")
    result = subprocess.run(
        [node, str(VALIDATOR), ",".join(series), "--mode", mode],
        capture_output=True, text=True,
    )
    assert "FAIL" not in result.stdout, result.stdout


def test_the_css_palette_matches_the_specification_table() -> None:
    """The spec table and the shipped CSS are one palette; drift fails here."""
    spec = (paths.codegen_root() / "dashboard-specification.md").read_text(encoding="utf-8")
    row = next(line for line in spec.splitlines() if line.startswith("| `--series-1…5`"))
    documented = re.findall(r"#[0-9a-fA-F]{6}", row)
    assert documented[:5] == _series("light")
    assert documented[5:10] == _series("dark")


def test_replay_drives_a_live_update(isolated_runs_dir: Path) -> None:
    """TRK-024's second half: the only way to exercise motion before instrumentation."""
    from tests.replay import replay

    lines = gen_log.preset("clean-run").splitlines()[:12]
    count = replay(lines, gen_log.RUN_ID, speed=1000.0)
    assert count == 12
    with TestClient(server.app) as client:
        assert client.get("/api/state").json()["counts"]["events"] == 12


def test_dashboard_writes_only_under_codegen(seeded: str) -> None:
    """Containment: reads runs/, writes var/, touches nothing else."""
    source = (paths.codegen_root() / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert "var_root()" in source
    assert "/tmp" not in source
    assert json.dumps(source).count("os.path.expanduser") == 0
