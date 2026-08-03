---
name: reset-generated
description: Delete everything a tracked run created, by reading the run's own event log - no hardcoded directory names, so it works unchanged in any product. Dry-run first, then apply. Never touches codegen/, the run logs, or GitHub issues.
---

# Skill: Reset Generated

Clear the generated output so the next run starts from nothing. This is the *reset* half
of the project's cycle: **generate → observe → reset → regenerate.**

## The mechanism: the log is the manifest

This skill names no directories. It does not know what `server/` or `games/` are, and it
does not need to — **the run recorded what it created**, so the run itself says what to
remove:

| The log says | Used for |
|---|---|
| `issue.commit`, `finding.fixed`, `harden.finding.fixed` → `data.sha` | which commits this run produced |
| `release.tagged` → `data.tag` | which tags to delete |

The file list then comes from **git**, not from the log: `git show --diff-filter=A` over
those commits. That distinction matters — a commit's recorded `files` includes files it
*modified*, and deleting one of those would remove something that predated the run. The
log decides *which commits to ask about*; git decides *what was added*.

**That is what makes this portable.** Reusing it in another product needs no
configuration: a different codebase produces different commits, and the same query
returns its files.

## Usage

```
/reset-generated [--apply]
```

Dry by default. Nothing is deleted without `--apply`.

## Instructions

### Step 0: Refuse when a reset would destroy work

Run `python3 codegen/reset.py` (no flags). It refuses, and you stop, when:

- **the working tree is dirty** — uncommitted work would be lost;
- **a run has not finished** — resetting mid-flight orphans it.

Both are overridable with `--force`, which is the user's call to make, not yours. Ask.

### Step 1: Show the plan and get confirmation

The dry run prints exactly what would go: files created, tags cut, build residue, and —
importantly — two lists that are *not* acted on:

- **commits claimed by the log but absent from git** (rebased, amended, or never real);
- **files present that no run claims.** These are **left alone** and reported. An
  unexplained deletion is worse than an unexplained leftover, and a low reconciliation
  rate (`tracker.reconcile`) is the usual cause — the run made something without
  recording it.

Show that output and **ask before applying**. This is destructive and irreversible short
of git.

### Step 2: Apply, then commit

`python3 codegen/reset.py --apply`, then commit the deletion. The next `/ship-phase` run
now starts from a clean tree.

## What is never touched

| | Why |
|---|---|
| **`codegen/`** | the tracker — and `codegen/runs/`, where the logs live. **The logs are the product of the run**; deleting them destroys exactly what the generation was performed to produce. Enforced in code, not by configuration. |
| **GitHub issues** | they carry the issue-id counter. `generate-issues` resolves the next id from `max(GitHub, local) + 1`, so wiping them restarts numbering at 001 and collides with everything already shipped. This skill never calls `gh`. |
| **Anything unclaimed** | reported, never removed. |

## Important Rules

- **Never delete without showing the plan and asking.** Dry run first, always.
- **Release tags must go.** Both orchestrators skip any version whose tag exists, so a
  reset that leaves them makes the next run silently do nothing — the worst outcome,
  because it looks like success.
- **Never call `gh`.** Not to close issues, not to delete them.
- **Never edit the log to make a reset tidier.** The log is evidence; if it disagrees
  with the tree, that disagreement is the finding.
- **No hardcoded paths.** If you find yourself typing a directory name into this skill,
  the mechanism has been broken — the whole point is that it works unchanged elsewhere.
