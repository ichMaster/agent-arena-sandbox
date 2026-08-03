"""Check the tracking of a run in progress — after every version.

Instrumentation fails quietly. A skill that forgets an emit produces a log that still
parses, still reduces, and still renders; the gap only shows up when someone asks a
question the missing event was supposed to answer. Waiting until the end of a ten-version
run to discover that means ten versions recorded wrong.

So this runs at each version boundary and fails loudly. It is a **gate on the tracking**,
not on the build: the generated code may be perfect while the record of it is broken, and
that is precisely the failure this project cannot afford.

    python3 codegen/validate_run.py            # the active run, all completed versions
    python3 codegen/validate_run.py --version v01.01
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracker import paths, reconcile, schema  # noqa: E402
from tracker.reduce import reduce  # noqa: E402

#: Events a completed version must have produced. Absence is a skill that forgot.
REQUIRED_PER_VERSION = ("version.start", "step.start", "step.end", "version.end")

#: Steps ship-phase runs per version. A missing one means that sub-skill emitted nothing.
EXPECTED_STEPS = ("generate-issues", "execute-issues", "review-and-fix-issues", "release-version")


@dataclass
class Result:
    version: str | None
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def render(self) -> str:
        head = f"tracking validation — {self.version or 'whole run'}"
        lines = [head, "=" * len(head), ""]
        for name, ok, detail in self.checks:
            mark = "ok  " if ok else "FAIL"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        lines.append("")
        lines.append("PASS" if not self.failed else f"FAILED {len(self.failed)} check(s)")
        return "\n".join(lines)


def _events(run_id: str) -> list[dict[str, Any]]:
    path = paths.events_path(run_id)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def validate(run_id: str, version: str | None = None) -> Result:
    result = Result(version=version)
    events = _events(run_id)

    result.add("log exists and parses", bool(events), f"{len(events)} events")
    if not events:
        return result

    invalid = [(i, schema.validate(e)) for i, e in enumerate(events, 1)]
    bad = [(i, p) for i, p in invalid if p]
    result.add("every event validates against the schema", not bad,
               f"{len(bad)} invalid" if bad else "")

    state = reduce(
        paths.events_path(run_id).read_text(encoding="utf-8").splitlines(), datetime.now(UTC)
    )
    result.add("reducer produces state", state.counts.get("events", 0) > 0,
               f"status={state.status}")
    result.add("nothing quarantined", not state.quarantine,
               f"{len(state.quarantine)} quarantined" if state.quarantine else "")
    result.add("no torn lines mid-file", state.counts.get("torn", 0) == 0)

    scoped = [e for e in events if (e.get("scope") or {}).get("version") == version] \
        if version else events
    present = {str(e.get("type")) for e in scoped}

    if version:
        for required in REQUIRED_PER_VERSION:
            result.add(f"{version} emitted {required}", required in present)
        steps = {
            str((e.get("scope") or {}).get("step"))
            for e in scoped if str(e.get("type")).startswith("step.")
        }
        for step in EXPECTED_STEPS:
            result.add(f"{version} ran and recorded step {step}", step in steps,
                       "" if step in steps else "the sub-skill emitted nothing")

        issues = {
            str((e.get("scope") or {}).get("issue"))
            for e in scoped if str(e.get("type")).startswith("issue.")
        } - {"None", ""}
        result.add(f"{version} recorded issues", bool(issues), f"{len(issues)} issues")
        for issue in sorted(issues):
            per = {
                str(e.get("type")) for e in scoped
                if (e.get("scope") or {}).get("issue") == issue
            }
            result.add(f"  {issue} start→end complete",
                       "issue.start" in per and "issue.end" in per)

        node = _find_version_node(state.tree, version)
        result.add(f"{version} appears in the reduced tree", node is not None)
        if node:
            result.add(f"{version} closed cleanly", node.get("status") == "ok",
                       f"status={node.get('status')}")

    opened, closed = _pair_counts(events)
    result.add("start/end pairs balance for closed nodes", opened >= closed,
               f"{opened} starts, {closed} ends")

    report = reconcile.reconcile(run_id)
    if report.emit_rate is None:
        result.add("hook floor present (reconciliation possible)", False,
                   "no tool.used events — hooks not registered in this session")
    else:
        result.add("skill emit compliance", report.emit_rate >= 0.95,
                   f"{report.emit_rate * 100:.0f}%")
    return result


def _pair_counts(events: list[dict[str, Any]]) -> tuple[int, int]:
    opened = sum(1 for e in events if str(e.get("type")).endswith(".start"))
    closed = sum(
        1 for e in events
        if str(e.get("type")).endswith((".end", ".skipped", ".aborted"))
        and not str(e.get("type")).startswith(("issue.implement", "issue.validate"))
    )
    return opened, closed


def _find_version_node(tree: list[dict[str, Any]], version: str) -> dict[str, Any] | None:
    for phase in tree:
        for node in phase.get("children") or []:
            if node.get("id") == version:
                result: dict[str, Any] = node
                return result
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codegen.validate_run",
        description="Check a run's tracking. Gate on the RECORD, not on the build.",
    )
    parser.add_argument("--version", default=None, help="the version just completed")
    parser.add_argument("--run", default=None, help="run id (default: active)")
    args = parser.parse_args(argv)

    run_id = args.run
    if not run_id:
        pointer = paths.current_pointer()
        run_id = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    if not run_id:
        print("no active run — nothing to validate")
        return 1

    result = validate(run_id, args.version)
    print(result.render())
    return 0 if not result.failed else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
