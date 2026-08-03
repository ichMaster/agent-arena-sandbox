"""Delete what a tracked run created, by reading its own log.

The project's cycle is generate → observe → reset → regenerate. This is the reset half.

**The log is the manifest.** Nothing here names ``server/`` or ``games/`` or any other
directory: those mean nothing in the next product. The run recorded every commit it made
(``issue.commit``, ``finding.fixed``, ``harden.finding.fixed``) and every tag it cut
(``release.tagged``), so the run itself says what to remove. That makes this portable by
construction rather than by configuration.

**Created, not merely touched.** A commit's recorded ``files`` list includes files it
*modified*, and deleting one of those would remove something that predated the run. So
the file set comes from ``git show --diff-filter=A`` over the commits the log names —
git decides what was *added*, the log decides *which commits to ask about*.

Three things it never touches:

* **`codegen/`** — the tracker, and `codegen/runs/`, where the logs live. The logs are
  the product of the run; deleting them destroys what the generation was performed to
  produce. Enforced in code, not by configuration.
* **GitHub issues** — they carry the issue-id counter, which `generate-issues` reads to
  continue numbering. This module never invokes `gh`.
* **Anything no run claims.** A file the log does not account for is left alone and
  reported, because an unexplained deletion is worse than an unexplained leftover.

Dry by default; ``--apply`` is required to remove anything.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Never deletable, whatever a log claims. This is the TOOLING, and it is the same in
#: every product these skills are used in -- which is why naming it here does not
#: reintroduce the portability problem that naming `server/` or `games/` would.
#:
#: `.claude` matters more than it looks. A fix to a skill is source, and a run commit
#: that CREATES a skill file would otherwise put it in the deletion set. (An *edited*
#: skill was always safe: `--diff-filter=A` lists additions only.)
ALWAYS_KEEP = (
    "codegen",
    ".claude",
    ".git",
    # Local secrets and the rule that hides them. Neither is generated output, and both
    # are the same in every product, so naming them costs no portability.
    #
    # Today a reset would already spare them -- the file set comes from
    # `git --diff-filter=A`, and a gitignored file is never added by a run commit. That
    # is a property of the *current* .gitignore, not a guarantee: loosen the ignore rule,
    # or `git add -f` once, and a run commit would put a real API key in the deletion set.
    # A leftover .env is a small annoyance; a deleted one is a secret that may not be
    # recoverable, so this asymmetry is worth a hard guard rather than a derived one.
    ".env",
    ".envrc",
    ".gitignore",
)

#: Prefix match too, so `.env.local` / `.env.production` are covered without listing them.
#: `.env.example` is a template with no secret in it, and is deliberately NOT protected --
#: it is ordinary source that a run may legitimately create and a reset may remove.
SECRET_PREFIXES = (".env.",)

#: Events whose ``data.sha`` names a commit this run produced.
COMMIT_EVENTS = ("issue.commit", "finding.fixed", "harden.finding.fixed")

#: Events naming a tag this run cut.
TAG_EVENTS = ("release.tagged",)


def _git(*args: str, repo: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo or REPO, capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip() if result.returncode == 0 else ""


@dataclass
class Manifest:
    """What the logs say a run produced."""

    runs: list[str] = field(default_factory=list)
    shas: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    missing_shas: list[str] = field(default_factory=list)
    #: Protected paths a run commit added -- reported, never deleted.
    protected: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)
    unaccounted: list[str] = field(default_factory=list)


def read_logs(runs_root: Path) -> list[dict[str, object]]:
    """Every event across every run directory, oldest run first."""
    events: list[dict[str, object]] = []
    if not runs_root.is_dir():
        return events
    for run_dir in sorted(p for p in runs_root.glob("run-*") if p.is_dir()):
        log = run_dir / "events.jsonl"
        if not log.is_file():
            continue
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn tail is not a reason to refuse a reset
    return events


def files_added_by(sha: str, repo: Path | None = None) -> list[str]:
    """Files this commit ADDED. Modified files are excluded — they predate the run."""
    out = _git("show", "--diff-filter=A", "--name-only", "--format=", sha, repo=repo)
    return [line for line in out.splitlines() if line.strip()]


def build_manifest(runs_root: Path, repo: Path | None = None) -> Manifest:
    """Derive, from the logs plus git, exactly what the runs created."""
    manifest = Manifest()
    events = read_logs(runs_root)
    if not events:
        return manifest

    manifest.runs = sorted({str(e.get("run_id", "")) for e in events} - {""})
    known = set(_git("log", "--format=%h", "-2000", repo=repo).split())

    seen_shas: list[str] = []
    for event in events:
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        etype = event.get("type")
        if etype in COMMIT_EVENTS:
            sha = str(data.get("sha", ""))
            if sha and sha not in seen_shas:
                seen_shas.append(sha)
        elif etype in TAG_EVENTS:
            tag = str(data.get("tag", ""))
            if tag and tag not in manifest.tags:
                manifest.tags.append(tag)

    files: list[str] = []
    for sha in seen_shas:
        if sha not in known:
            # Claimed by the log but absent from git: rebased, amended, or never real.
            manifest.missing_shas.append(sha)
            continue
        manifest.shas.append(sha)
        for path in files_added_by(sha, repo):
            if is_protected(path):
                # A run commit added a protected path -- a committed .env, or a
                # .gitignore the generator wrote. Record it so the omission is visible
                # rather than silent, but never queue it for deletion.
                if path not in manifest.protected:
                    manifest.protected.append(path)
                continue
            if path not in files:
                files.append(path)

    candidates = [f for f in files if f.split("/", 1)[0] not in ALWAYS_KEEP]
    manifest.files = [f for f in candidates if not looks_like_source(f)]
    manifest.withheld = [f for f in candidates if looks_like_source(f)]

    tracked = set(_git("ls-files", repo=repo).splitlines())
    accounted = set(manifest.files)
    manifest.unaccounted = sorted(
        f for f in tracked - accounted
        if f.split("/", 1)[0] not in ALWAYS_KEEP and _looks_generated(f)
    )
    return manifest


def _looks_generated(path: str) -> bool:
    """Heuristic, used only to *report* leftovers -- never to delete them."""
    head = path.split("/", 1)[0]
    return head not in {".claude", ".github", "spec", "LICENSE"} and not head.endswith(".md")


def looks_like_source(path: str) -> bool:
    """Does this deletion candidate look like something a human wrote?

    The second layer of the skills concern. ALWAYS_KEEP covers the tooling by name; this
    covers the rest by shape, because a product's source directory is not called the same
    thing everywhere. A candidate matching this is **withheld and reported**, never
    deleted silently -- the run may legitimately have added it, but that is a decision
    for a person, not a heuristic.
    """
    head, _, tail = path.partition("/")
    if head == "spec" and not tail.startswith("implementation/"):
        return True          # the specification itself; only implementation/ is per-run
    # root docs
    return "/" not in path and (path.endswith(".md") or path in {"LICENSE", ".gitignore"})


@dataclass
class Plan:
    manifest: Manifest
    residue: list[Path] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.manifest.files or self.manifest.tags or self.residue)

    def render(self) -> str:
        m = self.manifest
        lines: list[str] = []
        if self.blockers:
            lines += ["REFUSING:", *(f"  x {b}" for b in self.blockers), ""]
        lines.append(
            f"from {len(m.runs)} run(s): {len(m.shas)} commits -> {len(m.files)} files added"
        )
        lines.append("")
        for label, items in (
            ("files this run created", m.files),
            ("tags this run cut", m.tags),
            ("build residue", [str(p) for p in self.residue]),
            ("protected -- a run created these, but they are NEVER deleted",
             self.manifest.protected),
        ):
            if items:
                lines.append(f"{label} ({len(items)}):")
                lines += [f"  - {i}" for i in items[:15]]
                if len(items) > 15:
                    lines.append(f"  ... and {len(items) - 15} more")
                lines.append("")
        if m.missing_shas:
            lines += [
                f"claimed by the log but absent from git ({len(m.missing_shas)}) -- skipped:",
                *(f"  ? {s}" for s in m.missing_shas[:8]), "",
            ]
        if m.withheld:
            lines += [
                f"claimed by a run but LOOKS LIKE SOURCE ({len(m.withheld)}) -- WITHHELD:",
                *(f"  ! {f}" for f in m.withheld[:10]),
                "  delete these by hand if you are sure. A run adding source is unusual",
                "  enough to be worth a human deciding.", "",
            ]
        if m.unaccounted:
            lines += [
                f"present but no run claims them ({len(m.unaccounted)}) -- LEFT ALONE:",
                *(f"  ! {f}" for f in m.unaccounted[:10]),
                "  an unexplained deletion is worse than an unexplained leftover.", "",
            ]
        lines += [
            "never touched:",
            "  codegen/          the tracker, and codegen/runs/ -- the logs are the product",
            "  .claude/          the skills; a fix to one is source, not output",
            "  .env, .envrc      local secrets -- a deleted key may not be recoverable",
            "  .gitignore        the rule that keeps those secrets out of git",
            "  GitHub issues     they carry the issue-id counter; this never calls gh",
        ]
        return "\n".join(lines)


def build_plan(runs_root: Path | None = None, *, force: bool = False) -> Plan:
    root = runs_root or (REPO / "codegen" / "runs")
    plan = Plan(manifest=build_manifest(root))

    if not force:
        if _git("status", "--porcelain"):
            plan.blockers.append(
                "working tree is dirty -- commit or stash first, or a reset loses that work"
            )
        running = _active_run()
        if running:
            plan.blockers.append(
                f"run {running} has not finished -- resetting now would orphan it mid-flight"
            )

    for pattern in ("**/__pycache__", "**/*.egg-info", ".pytest_cache", ".mypy_cache", "*.db"):
        for path in REPO.glob(pattern):
            relative = path.relative_to(REPO)
            if is_protected(relative) or relative.parts[:1] == (".venv",):
                continue
            plan.residue.append(path.relative_to(REPO))
    return plan


def _active_run() -> str | None:
    sys.path.insert(0, str(REPO / "codegen"))
    try:
        from tracker import run as run_mod

        pending = run_mod.pending()
        return pending.run_id if pending else None
    except Exception:  # noqa: BLE001 - an absent tracker is not a blocker
        return None


def is_protected(relative: str | Path) -> bool:
    """Whether a path may never be deleted, whatever a log claims."""
    parts = Path(relative).parts
    if not parts:
        return False
    head = parts[0]
    if head in ALWAYS_KEEP:
        return True
    # `.env.example` is a template, not a secret -- it stays deletable.
    return head.startswith(SECRET_PREFIXES) and head != ".env.example"


def _assert_safe(relative: str | Path) -> None:
    if is_protected(relative):
        raise RuntimeError(f"refusing to delete protected path {relative}")


def apply(plan: Plan, repo: Path | None = None) -> dict[str, int]:
    """Carry out the plan. Raises rather than proceed past a protected path."""
    if plan.blockers:
        raise RuntimeError("; ".join(plan.blockers))
    base = repo or REPO
    counts = {"files": 0, "residue": 0, "tags": 0, "dirs": 0}

    for relative in plan.manifest.files:
        _assert_safe(relative)
        target = base / relative
        if target.is_file():
            target.unlink()
            counts["files"] += 1
    for residue_path in plan.residue:
        _assert_safe(residue_path)
        target = base / residue_path
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        counts["residue"] += 1
    for tag in plan.manifest.tags:
        _git("tag", "-d", tag, repo=base)
        counts["tags"] += 1

    counts["dirs"] = _prune_empty_dirs(base)
    return counts


def _prune_empty_dirs(base: Path) -> int:
    """Remove directories emptied by the deletion. Never descends into ALWAYS_KEEP."""
    removed = 0
    for path in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        parts = path.relative_to(base).parts
        if not parts or parts[0] in ALWAYS_KEEP or parts[0] in {".git", ".venv"}:
            continue
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codegen.reset",
        description="Delete what a tracked run created, by reading its own log.",
    )
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument(
        "--force", action="store_true", help="skip the dirty-tree/active-run checks"
    )
    parser.add_argument("--runs", type=Path, default=None, help="path to a runs/ directory")
    args = parser.parse_args(argv)

    plan = build_plan(args.runs, force=args.force)
    print(plan.render())

    if plan.blockers:
        return 1
    if not plan.manifest.runs:
        print("\nno run logs found -- nothing to reset from. The log IS the manifest.")
        return 1
    if plan.empty:
        print("\nnothing to reset.")
        return 0
    if not args.apply:
        print("\nDRY RUN -- nothing deleted. Re-run with --apply.")
        return 0

    counts = apply(plan)
    print(
        f"\nremoved {counts['files']} files, {counts['residue']} residue, "
        f"{counts['tags']} tags, {counts['dirs']} emptied directories."
    )
    print("commit the deletion; the next run starts from a clean tree.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

