"""TRK-016 / TRK-017 / TRK-018 — hooks and the compliance report.

Hooks run inside the session they observe, so the tests are mostly about what they
must *not* do: raise, exit non-zero, print to stdout, or record a command string.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from hooks import on_stop, on_tool_use
from tracker import emit, paths, reconcile

HOOKS = paths.codegen_root() / "hooks"


@pytest.fixture
def active_run(isolated_runs_dir: Path) -> str:
    run_id = "run-20260803-142012"
    paths.run_dir(run_id).mkdir(parents=True, exist_ok=True)
    paths.current_pointer().write_text(run_id, encoding="utf-8")
    return run_id


def _events(run_id: str) -> list[dict[str, Any]]:
    path = paths.events_path(run_id)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _run_hook(script: str, payload: Any, run_id_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, CODEGEN_RUNS_DIR=str(run_id_dir))
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        env=env, capture_output=True, text=True, timeout=30,
    )


BASH_PAYLOAD = {
    "tool_name": "Bash",
    "tool_input": {"command": "pytest codegen/tests -q"},
    "tool_response": {"exit_code": 0, "duration_ms": 1200},
}


def test_a_bash_call_becomes_a_tool_used_event(active_run: str) -> None:
    result = _run_hook("on_tool_use.py", BASH_PAYLOAD, paths.runs_root())
    assert result.returncode == 0
    events = _events(active_run)
    assert [e["type"] for e in events] == ["tool.used"]
    assert events[0]["data"]["program"] == "pytest"


@pytest.mark.parametrize(
    "payload",
    ["", "   ", "{not json", "[]", '"a string"', json.dumps({"tool_name": "Read"})],
    ids=["empty", "blank", "broken", "list", "string", "uninteresting"],
)
def test_bad_or_uninteresting_input_exits_zero_and_writes_nothing(
    active_run: str, payload: str
) -> None:
    result = _run_hook("on_tool_use.py", payload, paths.runs_root())
    assert result.returncode == 0
    assert result.stdout == ""
    assert _events(active_run) == []


def test_the_raw_command_never_reaches_disk(active_run: str) -> None:
    """A command line can carry an API key, so only its shape is recorded."""
    secret = "sk-ant-" + "A" * 30
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"ANTHROPIC_API_KEY={secret} python agent/agent.py --live"},
        "tool_response": {"exit_code": 0},
    }
    _run_hook("on_tool_use.py", payload, paths.runs_root())
    written = paths.events_path(active_run).read_text(encoding="utf-8")
    assert secret not in written
    assert "agent/agent.py" not in written, "the command line itself must not be recorded"


def test_file_tools_record_only_the_basename(active_run: str) -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/Users/someone/secret-project/server/main.py",
                       "content": "an api key could be in here"},
        "tool_response": {},
    }
    _run_hook("on_tool_use.py", payload, paths.runs_root())
    written = paths.events_path(active_run).read_text(encoding="utf-8")
    assert "main.py" in written
    assert "secret-project" not in written
    assert "an api key" not in written


def test_the_hook_is_fast_enough_to_run_on_every_tool_call(active_run: str) -> None:
    """It runs on every call; a slow hook taxes the whole pipeline. Budget: 50ms p95."""
    durations: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        on_tool_use.build_data(BASH_PAYLOAD)
        durations.append(time.perf_counter() - started)
    durations.sort()
    assert durations[int(len(durations) * 0.95) - 1] < 0.05


def test_summarise_bash_keeps_shape_not_content() -> None:
    summary = on_tool_use.summarise_bash("git commit -m 'a message with a secret'")
    assert summary == {"program": "git", "subcommand": "commit", "argv_len": 4}


# ── the Stop hook ────────────────────────────────────────────────────────────


def test_stop_closes_an_open_run(active_run: str) -> None:
    emit.emit("run.start", emitter="skill:ship-phase", data={
        "command": "/ship-phase v01", "plan": ["v01.01"],
        "baseline": {"tests": 0, "mypy_errors": 0},
        "git": {"branch": "b", "head_sha": "s", "remote": "o"},
    })
    result = _run_hook("on_stop.py", "{}", paths.runs_root())
    assert result.returncode == 0
    assert [e["type"] for e in _events(active_run)][-1] == "run.aborted"
    assert _events(active_run)[-1]["data"]["reason"] == "session-stopped"


def test_stop_does_not_touch_a_finished_run(active_run: str) -> None:
    """A spurious run.aborted would make a clean run look like a crash."""
    emit.emit("run.start", emitter="skill:ship-phase", data={
        "command": "/ship-phase v01", "plan": [],
        "baseline": {"tests": 0, "mypy_errors": 0},
        "git": {"branch": "b", "head_sha": "s", "remote": "o"},
    })
    emit.emit("run.end", emitter="skill:ship-phase", status="ok",
              data={"versions_done": 0, "issues_done": 0})
    before = _events(active_run)
    _run_hook("on_stop.py", "{}", paths.runs_root())
    assert _events(active_run) == before


def test_stop_is_silent_when_there_is_no_run(isolated_runs_dir: Path) -> None:
    result = _run_hook("on_stop.py", "{}", paths.runs_root())
    assert result.returncode == 0 and result.stdout == ""


def test_run_is_open_treats_a_torn_tail_as_still_open(active_run: str) -> None:
    path = paths.events_path(active_run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"v":1,"ts":"2026-08-03T14:2', encoding="utf-8")
    assert on_stop.run_is_open(active_run) is True


# ── reconciliation ───────────────────────────────────────────────────────────


def _seed(run_id: str, validations: int, observed: int, shas: list[str]) -> None:
    scope = {"phase": "v01", "version": "v01.01", "step": "execute-issues", "issue": "ARENA-001"}
    for _ in range(observed):
        emit.emit("tool.used", emitter="hook:on-tool-use", status="ok",
                  data={"tool": "Bash", "program": "pytest", "argv_len": 3})
    for i in range(validations):
        emit.emit("issue.validate.end", emitter="skill:execute-issues", status="ok", scope=scope,
                  data={"attempt": i + 1, "pytest": {"passed": 1, "failed": 0, "duration_s": 1.0},
                        "mypy": {"errors": 0}})
    for sha in shas:
        emit.emit("issue.commit", emitter="skill:execute-issues", status="ok", scope=scope,
                  data={"sha": sha, "files": ["x.py"]})


def test_full_compliance_reports_one_hundred_percent(active_run: str) -> None:
    _seed(active_run, validations=3, observed=3, shas=["aaa1111", "bbb2222"])
    report = reconcile.reconcile(active_run, git_shas={"aaa1111", "bbb2222"})
    assert report.emit_rate == 1.0
    assert report.commit_rate == 1.0
    assert report.missing_in_git == []


def test_a_missing_emit_is_reported_and_named(active_run: str) -> None:
    """The gap the reconciliation exists to find: hooks saw it, the skill did not emit."""
    _seed(active_run, validations=1, observed=4, shas=[])
    report = reconcile.reconcile(active_run, git_shas=set())
    assert report.emit_rate == 0.25
    assert "not emitted by the skill" in report.to_markdown()


def test_a_commit_claimed_but_absent_from_git_is_flagged(active_run: str) -> None:
    _seed(active_run, validations=1, observed=1, shas=["real123", "ghost99"])
    report = reconcile.reconcile(active_run, git_shas={"real123"})
    assert report.missing_in_git == ["ghost99"]
    assert "ghost99" in report.to_markdown()


def test_reconciliation_is_never_a_gate(active_run: str) -> None:
    """It reports a rate; it must not fail anything, even at zero compliance."""
    _seed(active_run, validations=0, observed=5, shas=[])
    env = dict(os.environ, CODEGEN_RUNS_DIR=str(paths.runs_root()))
    result = subprocess.run(
        [sys.executable, "-m", "tracker.reconcile", active_run],
        cwd=paths.codegen_root(), env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, "a measurement must never exit non-zero"
    assert "0.0%" in result.stdout


def test_settings_json_holds_matchers_and_commands_only() -> None:
    """Architecture §7: the one file outside codegen/ must stay a pointer, not logic."""
    settings_path = paths.codegen_root().parent / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    commands = [
        entry["command"]
        for group in settings.get("hooks", {}).values()
        for matcher in group
        for entry in matcher.get("hooks", [])
    ]
    assert commands, "no hooks registered"
    for command in commands:
        assert command.startswith("python3 codegen/hooks/"), command
        # A command is an invocation, never a program: no pipes, no chaining, no logic.
        assert not any(token in command for token in ("&&", "||", ";", "|", "$(", "`")), command

    allowed = {"hooks", "matcher", "command", "type", "PostToolUse", "Stop"}
    for group in settings.get("hooks", {}).values():
        for matcher in group:
            assert set(matcher) <= allowed, set(matcher) - allowed
