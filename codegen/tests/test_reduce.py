"""TRK-006 / TRK-007 / TRK-008 / TRK-009 — the reducer, its fixtures, and the writer.

Fixtures come from the generator (TRK-024) rather than being hand-authored, so adding
a failure mode means adding a scenario, not transcribing sixty lines of JSON.

The two tests that matter most are the purity check — asserted over the AST, because
a single ``datetime.now()`` would make every golden fixture unreproducible — and
``no-review``, which pins the distinction the prototype originally got wrong.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests import gen_log
from tracker import emit, paths
from tracker import reduce as reduce_mod
from tracker import state as state_mod

NOW = datetime(2026, 8, 3, 18, 0, 0, tzinfo=UTC)


def _reduce(name: str) -> reduce_mod.State:
    return reduce_mod.reduce(gen_log.preset(name).splitlines(), NOW)


# ── purity: what makes golden fixtures possible at all ───────────────────────


def test_reduce_reads_no_clock_no_env_and_no_files() -> None:
    """Asserted over the AST, not by inspection.

    ``reduce`` taking ``now`` as a parameter is the whole reason a fixture can be
    committed. One stray ``datetime.now()`` would break that silently, so the ban is
    mechanical.
    """
    source = Path(reduce_mod.__file__).read_text(encoding="utf-8")
    banned = {"now", "today", "time", "monotonic", "getenv", "open", "read_text"}
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
            node.func.attr in banned
        ):
            offenders.append(node.func.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (
            node.func.id in {"open", "input"}
        ):
            offenders.append(node.func.id)
    assert not offenders, f"reduce.py must stay pure; found {sorted(set(offenders))}"


def test_reducing_twice_is_byte_identical() -> None:
    first = json.dumps(_reduce("clean-run").as_dict(), sort_keys=True)
    second = json.dumps(_reduce("clean-run").as_dict(), sort_keys=True)
    assert first == second


def test_now_only_affects_open_nodes() -> None:
    """A finished run's elapsed must not drift with the clock."""
    lines = gen_log.preset("clean-run").splitlines()
    early = reduce_mod.reduce(lines, NOW)
    late = reduce_mod.reduce(lines, NOW + timedelta(days=3))
    assert early.elapsed_s == late.elapsed_s
    assert early.status == late.status == "done"


# ── the golden fixtures, one per failure mode ────────────────────────────────


def test_clean_run_has_balanced_pairs_and_a_complete_tree() -> None:
    state = _reduce("clean-run")
    assert state.status == "done"
    assert state.counts["torn"] == 0 and state.counts["malformed"] == 0
    assert [node["id"] for node in state.tree] == ["v01"]
    versions = state.tree[0]["children"]
    assert [v["id"] for v in versions] == ["v01.01", "v01.02"]
    assert all(v["status"] == "ok" and v["end"] for v in versions)


def test_retry_run_lowers_the_first_pass_rate() -> None:
    state = _reduce("retry-run")
    assert state.metrics["retried_issues"] == 2
    assert state.metrics["first_pass_rate"] == 0.5


def test_aborted_run_reports_running_without_crashing() -> None:
    state = _reduce("aborted-run")
    assert state.status == "running"
    assert any(node["status"] == "running" for node in state.tree)


def test_torn_tail_is_counted_and_skipped() -> None:
    state = reduce_mod.reduce(gen_log.torn_tail().splitlines(), NOW)
    assert state.counts["torn"] == 1
    assert state.counts["events"] > 0, "everything before the tear must still reduce"


def test_malformed_lines_are_quarantined_with_line_numbers() -> None:
    state = reduce_mod.reduce(gen_log.malformed().splitlines(), NOW)
    reasons = " ".join(entry["reason"] for entry in state.quarantine)
    assert len(state.quarantine) == 2
    assert "invalid JSON" in reasons
    assert "unknown event type" in reasons
    assert all(isinstance(entry["line"], int) for entry in state.quarantine)
    assert state.counts["events"] > 0, "the rest of the file must still reduce"


def test_skipped_versions_are_excluded_from_scope() -> None:
    state = _reduce("skipped-versions")
    assert state.metrics["versions_skipped"] == 1
    assert "v01.01" not in state.scope["undecomposed"]


def test_a_version_without_a_review_is_absent_not_zero() -> None:
    """The prototype's bug, pinned.

    Zero findings and *not yet reviewed* are different claims. A version whose review
    step never ran must not appear among findings at all — rendering it as an empty
    bar asserts "clean" when it means "nobody looked".
    """
    state = _reduce("no-review")
    versions_with_findings = {f["version"] for f in state.findings}
    assert "v01.01" in versions_with_findings
    assert "v01.02" not in versions_with_findings


def test_held_findings_keep_their_outcome() -> None:
    state = _reduce("held-findings")
    outcomes = {f["outcome"] for f in state.findings}
    assert "held" in outcomes


# ── scope, estimate and ETA ──────────────────────────────────────────────────


def test_scope_is_a_range_and_never_a_planned_scalar() -> None:
    state = _reduce("clean-run")
    assert set(state.scope) >= {"known", "est_low", "est_high", "undecomposed"}
    assert "issues_planned" not in json.dumps(state.as_dict()), (
        "a single planned number would be a guess wearing the costume of a fact"
    )


def test_the_uncertainty_band_narrows_as_versions_are_decomposed() -> None:
    """Widest when nothing is known; zero once every version is decomposed."""
    lines = gen_log.preset("clean-run").splitlines()
    widths: list[int] = []
    for cut in (3, len(lines) // 2, len(lines)):
        state = reduce_mod.reduce(lines[:cut], NOW)
        widths.append(state.scope["est_high"] - state.scope["est_low"])
    assert widths[0] >= widths[-1]
    assert widths[-1] == 0, "no undecomposed versions should leave no uncertainty"


def test_estimate_accuracy_is_recorded_as_signed_error() -> None:
    state = _reduce("clean-run")
    assert state.estimate is not None
    rows = state.estimate["accuracy"]
    assert rows and all({"version", "estimated_mid", "actual", "error"} <= set(r) for r in rows)
    for row in rows:
        assert row["error"] == row["actual"] - row["estimated_mid"]


def test_eta_is_absent_until_a_version_has_finished() -> None:
    lines = gen_log.preset("clean-run").splitlines()
    assert reduce_mod.reduce(lines[:5], NOW).eta is None


def test_eta_carries_its_own_basis() -> None:
    state = _reduce("clean-run")
    assert state.eta is not None
    assert state.eta["basis"]["issues_sampled"] > 0
    assert state.eta["low_s"] <= state.eta["high_s"]


# ── github and idle ──────────────────────────────────────────────────────────


def test_github_counts_come_from_the_log() -> None:
    state = _reduce("clean-run")
    assert state.github["created"] == state.github["closed"] == 7
    assert state.github["open"] == 0
    assert state.github["commits"] >= 7
    assert state.github["branch"] == "codegen-tracking"


def test_elapsed_excludes_the_idle_gap(isolated_runs_dir: Path) -> None:
    """A run paused overnight must not report the pause as working time."""
    base = gen_log.preset("clean-run").splitlines()
    resumed = json.dumps(
        {
            "v": 1, "ts": "2026-08-03T15:00:00.000Z", "run_id": gen_log.RUN_ID,
            "type": "run.resumed", "emitter": "skill:ship-phase", "scope": {},
            "data": {"gap_s": 60},
        },
        separators=(",", ":"),
    )
    state = reduce_mod.reduce([*base[:-1], resumed, base[-1]], NOW)
    assert state.idle_s == 60
    plain = reduce_mod.reduce(base, NOW)
    assert state.elapsed_s == pytest.approx(plain.elapsed_s - 60, abs=1)


# ── the writer ───────────────────────────────────────────────────────────────


def test_state_is_written_atomically_and_reread(isolated_runs_dir: Path) -> None:
    run_id = gen_log.RUN_ID
    paths.events_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    paths.events_path(run_id).write_text(gen_log.preset("clean-run"), encoding="utf-8")

    state = state_mod.rebuild(run_id, NOW)
    assert state.run_id == run_id
    on_disk = state_mod.read(run_id)
    assert on_disk is not None
    assert on_disk["metrics"]["issues_done"] == state.metrics["issues_done"]


def test_deleting_state_loses_nothing(isolated_runs_dir: Path) -> None:
    """state.json is disposable; events.jsonl is the source of truth."""
    run_id = gen_log.RUN_ID
    paths.events_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    paths.events_path(run_id).write_text(gen_log.preset("clean-run"), encoding="utf-8")

    first = json.dumps(state_mod.rebuild(run_id, NOW).as_dict(), sort_keys=True)
    paths.state_path(run_id).unlink()
    second = json.dumps(state_mod.rebuild(run_id, NOW).as_dict(), sort_keys=True)
    assert first == second


def test_a_reader_never_sees_a_half_written_snapshot(isolated_runs_dir: Path) -> None:
    """Atomic replace: 200 rapid writes, read concurrently, never invalid JSON."""
    run_id = gen_log.RUN_ID
    paths.events_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    paths.events_path(run_id).write_text(gen_log.preset("clean-run"), encoding="utf-8")
    state = reduce_mod.reduce(gen_log.preset("clean-run").splitlines(), NOW)

    reader = subprocess.Popen(
        [
            sys.executable, "-c",
            "import json,sys,time\n"
            f"p = {str(paths.state_path(run_id))!r}\n"
            "bad = 0\n"
            "for _ in range(400):\n"
            "    try:\n"
            "        json.load(open(p))\n"
            "    except FileNotFoundError:\n"
            "        pass\n"
            "    except Exception:\n"
            "        bad += 1\n"
            "    time.sleep(0.001)\n"
            "sys.exit(bad)\n",
        ],
    )
    for _ in range(200):
        state_mod.write(run_id, state)
    assert reader.wait(timeout=60) == 0, "a reader observed a partial snapshot"


def test_rebuild_cli_reports_the_run(isolated_runs_dir: Path) -> None:
    run_id = gen_log.RUN_ID
    paths.events_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    paths.events_path(run_id).write_text(gen_log.preset("clean-run"), encoding="utf-8")
    paths.current_pointer().write_text(run_id, encoding="utf-8")

    env = dict(__import__("os").environ, CODEGEN_RUNS_DIR=str(paths.runs_root()))
    result = subprocess.run(
        [sys.executable, "-m", "tracker.state"],
        cwd=paths.codegen_root(), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert run_id in result.stdout and "events" in result.stdout


def test_emitted_events_reduce_end_to_end(isolated_runs_dir: Path) -> None:
    """The emitter and the reducer agree — not just the generator and the reducer."""
    run_id = "run-20260803-142012"
    paths.run_dir(run_id).mkdir(parents=True, exist_ok=True)
    paths.current_pointer().write_text(run_id, encoding="utf-8")

    emit.emit("run.start", emitter="skill:ship-phase", data={
        "command": "/ship-phase v01", "plan": ["v01.01"],
        "baseline": {"tests": 0, "mypy_errors": 0},
        "git": {"branch": "b", "head_sha": "s", "remote": "o"},
    })
    emit.emit("phase.start", emitter="skill:ship-phase", scope={"phase": "v01"})
    emit.emit("version.start", emitter="skill:ship-phase",
              scope={"phase": "v01", "version": "v01.01"})
    emit.emit("run.end", emitter="skill:ship-phase", status="ok",
              data={"versions_done": 0, "issues_done": 0})

    state = state_mod.rebuild(run_id, NOW)
    assert state.status == "done"
    assert state.command == "/ship-phase v01"
    assert state.counts["malformed"] == 0
