"""Compliance report — did the skills emit what they were told to?

Architecture §10.4. Whether a model followed an emit instruction is a property of a
*run*, not of code, so this cannot be a unit test. It is a post-run analysis that
reports a **rate**, and it **never fails a build**: a falling rate is a signal that
skill files have grown too long, which is the observer-effect risk the vision names —
not a reason to block anything.

Two independent checks:

* hooks saw a tool call; did the skill emit the matching semantic event?
* the log claims a commit; does ``git log`` contain it, and vice versa?
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

from tracker import paths


@dataclass
class Report:
    run_id: str
    validate_observed: int = 0
    validate_emitted: int = 0
    commits_claimed: int = 0
    commits_in_git: int = 0
    missing_in_git: list[str] = field(default_factory=list)
    missing_in_log: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def emit_rate(self) -> float | None:
        if not self.validate_observed:
            return None
        return round(min(1.0, self.validate_emitted / self.validate_observed), 4)

    @property
    def commit_rate(self) -> float | None:
        if not self.commits_claimed:
            return None
        return round(min(1.0, self.commits_in_git / self.commits_claimed), 4)

    def to_markdown(self) -> str:
        lines = [
            f"# Reconciliation — {self.run_id}",
            "",
            "A measurement, never a gate. A falling rate means the skill files have grown",
            "too long for their emit instructions to survive — the observer effect, showing up.",
            "",
            "| Check | Observed | Emitted | Rate |",
            "|---|---|---|---|",
            f"| pytest runs vs `issue.validate.end` | {self.validate_observed} | "
            f"{self.validate_emitted} | {_pct(self.emit_rate)} |",
            f"| commits claimed vs in `git log` | {self.commits_claimed} | "
            f"{self.commits_in_git} | {_pct(self.commit_rate)} |",
            "",
        ]
        if self.missing_in_git:
            lines += ["**Claimed in the log, absent from git:**", ""]
            lines += [f"- `{sha}`" for sha in self.missing_in_git] + [""]
        if self.missing_in_log:
            lines += ["**In git, absent from the log:**", ""]
            lines += [f"- `{sha}`" for sha in self.missing_in_log] + [""]
        lines += self.notes
        return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _events(run_id: str) -> list[dict[str, Any]]:
    path = paths.events_path(run_id)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _git_shas(limit: int = 500) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--format=%h"],
            capture_output=True, text=True, timeout=15,
            cwd=paths.codegen_root().parent,
        )
        return set(result.stdout.split()) if result.returncode == 0 else set()
    except (OSError, subprocess.SubprocessError):
        return set()


def reconcile(run_id: str, git_shas: set[str] | None = None) -> Report:
    """Compare the hook floor, the skill events and git. Never raises on mismatch."""
    events = _events(run_id)
    report = Report(run_id=run_id)

    for event in events:
        etype = event.get("type")
        data = event.get("data") or {}
        if etype == "tool.used":
            program = str(data.get("program", ""))
            sub = str(data.get("subcommand", ""))
            if program.startswith("pytest") or sub == "pytest" or "pytest" in program:
                report.validate_observed += 1
        elif etype == "issue.validate.end":
            report.validate_emitted += 1
        elif etype in {"issue.commit", "finding.fixed", "harden.finding.fixed"}:
            sha = str(data.get("sha", ""))
            if sha:
                report.commits_claimed += 1

    shas_in_log = {
        str((e.get("data") or {}).get("sha", ""))
        for e in events
        if e.get("type") in {"issue.commit", "finding.fixed", "harden.finding.fixed"}
    } - {""}
    actual = git_shas if git_shas is not None else _git_shas()
    if actual:
        report.commits_in_git = len(shas_in_log & actual)
        report.missing_in_git = sorted(shas_in_log - actual)
    else:
        report.notes.append("_git history unavailable; commit check skipped._")
        report.commits_in_git = report.commits_claimed

    if report.emit_rate is not None and report.emit_rate < 1.0:
        report.notes.append(
            f"_{report.validate_observed - report.validate_emitted} validation run(s) were "
            "observed by hooks but not emitted by the skill._"
        )
    return report


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="tracker.reconcile")
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_args(argv)

    run_id = args.run_id
    if not run_id:
        pointer = paths.current_pointer()
        run_id = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    if not run_id:
        print("no run id given and no active run")
        return 1

    report = reconcile(run_id)
    out = paths.var_root() / f"reconcile-{run_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")
    print(f"{out}: emit {_pct(report.emit_rate)}, commits {_pct(report.commit_rate)}")
    return 0  # never non-zero: this is a measurement, not a gate


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_main(sys.argv[1:]))
