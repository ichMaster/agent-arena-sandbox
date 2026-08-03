"""Fold an event log into the dashboard's state. Pure.

``reduce(lines, now)`` reads nothing and writes nothing: ``now`` is a **parameter**,
never ``datetime.now()``. That is what makes golden fixtures possible (architecture
§6) — a reducer that read the clock could not produce byte-identical output twice.

Tolerance is part of the contract (architecture §5.3). A torn final line is counted
and skipped; a malformed or unknown-type line is quarantined with its line number.
Nothing is discarded silently: an observability system that loses data quietly is
lying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tracker import schema

TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"

#: One event, or one of its sub-objects. Aliased to keep handler signatures readable.
Evt = dict[str, Any]

#: Issue-size weights. The burn-down is size-weighted, so three S issues must not
#: outrank one L (vision §6.2).
SIZE_POINTS = {"S": 1, "M": 3, "L": 5}

#: Roadmap band for a version that has not been decomposed yet (architecture §3.2).
ISSUES_LOW, ISSUES_HIGH = 3, 7

#: Suffixes that close a node opened by ``*.start``.
CLOSERS = {"end", "skipped", "aborted"}


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, TS_FORMAT)
    except (ValueError, TypeError):
        return None


@dataclass
class Node:
    """One node of the run tree: run, phase, version, step or issue."""

    id: str
    kind: str
    status: str = "running"
    start: str | None = None
    end: str | None = None
    elapsed_s: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "elapsed_s": round(self.elapsed_s, 3),
        }
        if self.data:
            out["data"] = self.data
        if self.children:
            out["children"] = [child.as_dict() for child in self.children]
        return out


@dataclass
class State:
    """The reduced view. Serialised verbatim to ``state.json``."""

    run_id: str = ""
    schema: int = schema.SCHEMA_VERSION
    status: str = "unknown"
    command: str = ""
    started: str | None = None
    ended: str | None = None
    elapsed_s: float = 0.0
    idle_s: float = 0.0
    plan: list[str] = field(default_factory=list)
    tree: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    github: dict[str, Any] = field(default_factory=dict)
    estimate: dict[str, Any] | None = None
    eta: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    quarantine: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema": self.schema,
            "status": self.status,
            "command": self.command,
            "started": self.started,
            "ended": self.ended,
            "elapsed_s": round(self.elapsed_s, 3),
            "idle_s": round(self.idle_s, 3),
            "plan": self.plan,
            "tree": self.tree,
            "metrics": self.metrics,
            "scope": self.scope,
            "github": self.github,
            "estimate": self.estimate,
            "eta": self.eta,
            "findings": self.findings,
            "quarantine": self.quarantine,
            "counts": self.counts,
        }


def reduce(lines: Any, now: datetime) -> State:  # noqa: A001 - the domain name
    """Fold log lines into a :class:`State`. Pure: ``now`` is injected, never read."""
    events, counts, quarantine = _parse(lines)
    state = State(counts=counts, quarantine=quarantine)
    if not events:
        state.counts.setdefault("events", 0)
        return state

    tracker = _Accumulator(now)
    for seq, event in enumerate(events):
        tracker.apply(seq, event)
    tracker.finalise(state)
    return state


def _parse(lines: Any) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    """Split lines into usable events, counts and quarantine entries."""
    events: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    raw = [line for line in lines]
    torn = 0

    for number, line in enumerate(raw, start=1):
        text = line.rstrip("\n")
        if not text.strip():
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # A cut final line is a killed process; anywhere else it is corruption.
            if number == len(raw):
                torn += 1
            else:
                quarantine.append({"line": number, "reason": "invalid JSON"})
            continue
        problems = schema.validate(parsed)
        if problems:
            quarantine.append({"line": number, "reason": "; ".join(problems[:3])})
            continue
        events.append(parsed)

    return events, {
        "events": len(events),
        "torn": torn,
        "malformed": len(quarantine),
    }, quarantine


class _Accumulator:
    """Mutable fold state. Split out so :func:`reduce` stays readable."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.root = Node(id="run", kind="run")
        self.nodes: dict[tuple[str, ...], Node] = {(): self.root}
        self.run_data: dict[str, Any] = {}
        self.estimate: dict[str, Any] | None = None
        self.status = "running"
        self.started: str | None = None
        self.ended: str | None = None
        self.last_ts: str | None = None
        self.idle_s = 0.0
        self.decomposed: dict[str, list[dict[str, Any]]] = {}
        self.released: set[str] = set()
        self.skipped: set[str] = set()
        self.issue_attempts: dict[str, int] = {}
        self.issue_durations: list[float] = []
        self.tests_passing = 0
        self.gh_created = 0
        self.gh_closed = 0
        self.commits = 0
        self.findings: dict[str, dict[str, Any]] = {}
        self.version_overheads: list[float] = []
        self.harden_durations: list[float] = []

    # ── event dispatch ───────────────────────────────────────────────────

    def apply(self, seq: int, event: dict[str, Any]) -> None:
        etype = str(event["type"])
        scope = event.get("scope") or {}
        data = event.get("data") or {}
        ts = str(event.get("ts", ""))
        self.last_ts = ts

        if self.started is None:
            self.started = ts

        handler = getattr(self, f"_on_{etype.replace('.', '_')}", None)
        if handler is not None:
            handler(event, scope, data, ts)

        self._track_tree(etype, scope, data, ts, event.get("status"))

    # ── tree ─────────────────────────────────────────────────────────────

    def _path(self, scope: dict[str, Any]) -> tuple[str, ...]:
        return tuple(
            str(scope[key]) for key in ("phase", "version", "step", "issue") if scope.get(key)
        )

    def _ensure(self, path: tuple[str, ...]) -> Node:
        if path in self.nodes:
            return self.nodes[path]
        kind = ("run", "phase", "version", "step", "issue")[len(path)]
        node = Node(id=path[-1] if path else "run", kind=kind)
        parent = self._ensure(path[:-1])
        parent.children.append(node)
        self.nodes[path] = node
        return node

    def _track_tree(
        self, etype: str, scope: dict[str, Any], data: dict[str, Any],
        ts: str, status: Any,
    ) -> None:
        family, _, tail = etype.rpartition(".")
        # Findings, hardening and releases are scoped to a version but are NOT nodes of
        # the tree. Letting them through re-opened a closed version: harden.start
        # carries the last version's scope, so the node went back to "running" after
        # its version.end had already closed it.
        if family in {"finding", "harden", "release"} or etype.startswith("harden."):
            return
        if family == "run" and tail != "start":
            return
        path = self._path(scope)
        node = self._ensure(path)

        if tail == "start":
            node.start = node.start or ts
            node.status = "running"
        elif tail in CLOSERS:
            node.end = ts
            node.status = {"end": str(status or "ok"), "skipped": "skip",
                           "aborted": "fail"}.get(tail, "ok")
            if data:
                keep = {"tag", "reason", "attempts"}
            node.data.update({k: v for k, v in data.items() if k in keep})

    # ── handlers ─────────────────────────────────────────────────────────

    def _on_run_start(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.run_data = d
        self.started = ts

    def _on_run_estimate(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.estimate = d

    def _on_run_resumed(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.idle_s += float(d.get("gap_s", 0) or 0)

    def _on_run_end(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.status = "done"
        self.ended = ts

    def _on_run_aborted(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.status = "aborted"
        self.ended = ts

    def _on_version_decomposed( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.decomposed[str(s.get("version"))] = list(d.get("issues") or [])

    def _on_version_end(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.released.add(str(s.get("version")))

    def _on_version_skipped( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.skipped.add(str(s.get("version")))

    def _on_issue_validate_end( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        issue = str(s.get("issue"))
        attempt = int(d.get("attempt", 1) or 1)
        self.issue_attempts[issue] = max(self.issue_attempts.get(issue, 0), attempt)
        passed = (d.get("pytest") or {}).get("passed")
        if isinstance(passed, int):
            self.tests_passing = max(self.tests_passing, passed)

    def _on_issue_uploaded(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.gh_created += 1

    def _on_issue_closed(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.gh_closed += 1

    def _on_issue_commit(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.commits += 1

    def _on_finding_fixed(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.commits += 1
        self._finding(s, d, outcome="fixed")

    def _on_harden_finding_fixed( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self.commits += 1
        self._finding(s, d, outcome="hardened")

    def _on_harden_finding_held( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self._finding(s, d, outcome="held")

    def _on_finding_raised(self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self._finding(s, d, severity=str(d.get("severity", "")), outcome="open")

    def _on_finding_classified( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self._finding(s, d, disposition=str(d.get("disposition", "")))

    def _on_finding_deferred( self, e: Evt, s: Evt, d: Evt, ts: str) -> None:
        self._finding(s, d, outcome="deferred")

    def _finding(self, scope: Evt, data: Evt, **fields: Any) -> None:
        fid = str(data.get("finding", ""))
        if not fid:
            return
        entry = self.findings.setdefault(
            fid, {"id": fid, "version": scope.get("version"), "severity": "", "outcome": "open"}
        )
        entry.update({k: v for k, v in fields.items() if v})

    # ── finalise ─────────────────────────────────────────────────────────

    def finalise(self, state: State) -> None:
        self._close_elapsed(self.root)
        self.issue_durations = [
            node.elapsed_s
            for path, node in self.nodes.items()
            if node.kind == "issue" and node.end
        ]

        state.run_id = str(self.run_data.get("run_id", "")) or ""
        state.command = str(self.run_data.get("command", ""))
        state.plan = list(self.run_data.get("plan") or [])
        state.started = self.started
        state.ended = self.ended
        state.status = self.status if self.status != "running" else "running"
        state.idle_s = self.idle_s

        start_dt = parse_ts(self.started or "")
        end_dt = parse_ts(self.ended or "") if self.ended else self.now
        if start_dt and end_dt:
            state.elapsed_s = max(0.0, (end_dt - start_dt).total_seconds() - self.idle_s)

        state.tree = [child.as_dict() for child in self.root.children]
        state.findings = sorted(self.findings.values(), key=lambda f: str(f["id"]))
        self._scope_and_eta(state)
        self._metrics(state)
        self._github(state)

    def _close_elapsed(self, node: Node) -> None:
        start = parse_ts(node.start or "")
        end = parse_ts(node.end or "") if node.end else self.now
        if start and end:
            node.elapsed_s = max(0.0, (end - start).total_seconds())
        for child in node.children:
            self._close_elapsed(child)

    def _scope_and_eta(self, state: State) -> None:
        planned = [v for v in state.plan if v not in self.skipped]
        undecomposed = [v for v in planned if v not in self.decomposed]

        known_points = sum(
            SIZE_POINTS.get(str(issue.get("size")), 3)
            for issues in self.decomposed.values()
            for issue in issues
        )
        known_issues = sum(len(issues) for issues in self.decomposed.values())
        mean_issues = (known_issues / len(self.decomposed)) if self.decomposed else None
        low = int(mean_issues) if mean_issues else ISSUES_LOW
        high = int(mean_issues) if mean_issues else ISSUES_HIGH

        state.scope = {
            "known": known_issues,
            "known_points": known_points,
            "est_low": known_issues + len(undecomposed) * low,
            "est_high": known_issues + len(undecomposed) * high,
            "undecomposed": undecomposed,
        }

        if self.estimate:
            state.estimate = dict(self.estimate)
            state.estimate["accuracy"] = self._estimate_accuracy()

        done = sum(1 for issue in self.issue_attempts)
        if self.released and self.issue_durations:
            mean_issue = sum(self.issue_durations) / len(self.issue_durations)
            remaining_low = max(0, state.scope["est_low"] - done)
            remaining_high = max(0, state.scope["est_high"] - done)
            state.eta = {
                "low_s": int(remaining_low * mean_issue),
                "high_s": int(remaining_high * mean_issue),
                "basis": {
                    "issues_sampled": len(self.issue_durations),
                    "undecomposed_versions": len(undecomposed),
                },
            }

    def _estimate_accuracy(self) -> list[dict[str, Any]]:
        """Signed error per version: actual minus estimated. Never used to correct."""
        if not self.estimate:
            return []
        rows: list[dict[str, Any]] = []
        for entry in self.estimate.get("versions") or []:
            version = str(entry.get("id"))
            if version not in self.decomposed:
                continue
            actual = len(self.decomposed[version])
            mid = (int(entry.get("issues_low", 0)) + int(entry.get("issues_high", 0))) / 2
            rows.append({"version": version, "estimated_mid": mid, "actual": actual,
                         "error": actual - mid})
        return rows

    def _metrics(self, state: State) -> None:
        attempts = list(self.issue_attempts.values())
        first_pass = sum(1 for a in attempts if a == 1)
        state.metrics = {
            "issues_done": len(attempts),
            "first_pass_rate": round(first_pass / len(attempts), 4) if attempts else None,
            "retried_issues": sum(1 for a in attempts if a > 1),
            "mean_issue_s": (
                round(sum(self.issue_durations) / len(self.issue_durations), 2)
                if self.issue_durations else None
            ),
            "tests_passing": self.tests_passing,
            "versions_released": len(self.released),
            "versions_skipped": len(self.skipped),
            "findings_open": sum(
                1 for f in self.findings.values() if f["outcome"] in {"open", "deferred"}
            ),
            "findings_total": len(self.findings),
        }

    def _github(self, state: State) -> None:
        git = self.run_data.get("git") or {}
        state.github = {
            "created": self.gh_created,
            "closed": self.gh_closed,
            "open": max(0, self.gh_created - self.gh_closed),
            "commits": self.commits,
            "branch": git.get("branch"),
            "head_sha": git.get("head_sha"),
        }
