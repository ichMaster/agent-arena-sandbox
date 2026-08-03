---
name: execute-issues-file
description: Execute one version's issues directly from its local spec/implementation/vXX.YY-issues.md file (no GitHub). Implement -> validate -> commit -> push each issue in dependency order, then write an execution report. The offline, file-driven counterpart of execute-issues.
---

# Skill: Execute Issues From File

Execute the issues for one version **straight from its already-generated issues file** —
`spec/implementation/vXX.YY-issues.md` — with **no GitHub involvement** (no upload, no issue lookup,
no closing). Implement, validate, commit, and push each issue in dependency order, then write an
execution report.

This is the offline counterpart of `execute-issues`: same implementation discipline, but the issue
list comes from the local markdown file instead of `gh issue list`, and there are no GitHub issues to
close.

## Usage

```
/execute-issues-file <vXX.YY | path-to-issues-file> [--issue ARENA-###] [--dry-run]
```

- `/execute-issues-file v02.01` → executes `spec/implementation/v02.01-issues.md`
- `/execute-issues-file @spec/implementation/v03.02-issues.md`
- `--issue ARENA-###` → only that issue (its file-listed deps must already be committed)
- `--dry-run` → print the execution plan without making changes

> [!IMPORTANT]
> **Generate every line fresh.** A complete implementation of this same spec exists on sibling
> branches — you must **NEVER** `git checkout`/`cherry-pick`/merge code from another branch to satisfy
> an issue. This is an independent build.

## Instructions

### Step 0: Verify prerequisites & read the file

1. Confirm we are on the working dev branch (not a sibling) and the tree is clean (`git status`).
2. Resolve the target to `spec/implementation/vXX.YY-issues.md` and **read it** — the Issues Summary
   Table (IDs, titles, size, area, dependencies), the Dependency Tree, and each detailed
   `### ARENA-### …` section. **No `gh` is used.**
3. Read [spec/roadmap.md](../../../spec/roadmap.md) for the version goal + the `vXX.YY` DoD/Tests,
   [spec/architecture.md](../../../spec/architecture.md) for the contracts, and
   [spec/game_specification.md](../../../spec/game_specification.md) for scope (MVP vs later).
4. Establish a **green baseline** (`pytest` + strict `mypy`) so a later failure is attributable.

### Step 1: Build the execution queue (from the file)

- Parse the ARENA-### IDs + titles from the file's summary table; order them by the file's
  **Dependency Tree** (issues with no unmet dependency first).
- **Skip issues already implemented** — an issue whose ID already appears in a prior commit
  (`git log --grep "ARENA-###:"`) is done; skip it (resumability).
- With `--issue ARENA-###`, execute only that one (verify its file-listed deps are already committed).
- Show the ordered plan and proceed (stop here if `--dry-run`).

### Step 2: Execute each issue (loop, in dependency order)

For each issue:

1. **Announce:** `--- Starting ARENA-###: {title} ---`.
2. **Read** its detailed section from the issues file (What needs to be done / Acceptance criteria).
3. **Implement** per `CLAUDE.md` + `spec/architecture.md`, routed by component
   ([architecture.md](../../../spec/architecture.md) §2): `games/` (pure engine, no server import),
   `server/` (the ultimate authority — re-validate every move; seats by token; observers never seated),
   `agent/` (imports nothing from `server/`; the `LLMClient` seam is the only vendor path),
   `web/` (vanilla no-build renderer at `/ui`). A **seam change** (`GameInterface`, `LLMClient`, the WS
   event/action shapes, seat-by-token identity) updates `spec/architecture.md` **and** its contract
   test in the **same** commit. Strict typing; MVP-first (don't pull later phases in early).
4. **Validate:** `pytest` (unit + contract + integration where relevant) and `mypy` (strict) — **the
   `LLMClient` seam is always mocked; never a paid model call.** Walk each acceptance criterion against
   the phase DoD/Tests in `spec/roadmap.md`. Record pass/fail.
5. **Commit** (one issue = one commit; only code that passes validation):
   ```bash
   git commit -m "$(cat <<'EOF'
   ARENA-###: {title}

   {1-2 sentence summary of what was implemented}

   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```
   (No `Closes #…` line — there is no GitHub issue.)
6. **Push:** `git push`.
7. **Log** the issue ID + title, commit hash, files, validation result, status.

### Step 3: Handle failures

If implementation or validation fails: do **not** commit broken code; `git checkout -- .` to revert;
log the failure; then ask the user — continue to the next issue (if nothing depends on the failed one)
or stop.

### Step 3b: No automatic version bump

Do **not** change the version (VERSION/RELEASE.txt/tag) here — that is `/release-version`, on explicit
confirmation. If any issue failed or was skipped, do **not** treat the version as complete.

### Step 4: Write the execution report

Write `spec/implementation/vXX.YY-execution-report.md`: a summary table (completed/failed/skipped),
a per-issue table (ARENA ID · title · status · commit · files · tests), detailed results with the
validation checklist, and next steps. Commit + push it (an `ARENA`/`docs` message with the trailer).
(No GitHub mapping section — this run never touched GitHub.)

## Important Rules

- **File-driven, no GitHub.** The issue list, details, and dependency order come from the local
  `*-issues.md` file. Never `gh issue list`/`create`/`close`. No `vXX.YY-github-report.md` is written.
- **Generate every line fresh** — never copy code from a sibling branch.
- **One issue = one commit.** Never mix work across IDs; never work on two issues at once.
- **Dependency order.** Never start an issue whose file-listed dependencies aren't committed.
- **No broken code.** Only commit what passes `pytest` + strict `mypy`.
- **Tests ship with the feature; the LLM is always mocked** — no paid API call in tests/validation.
- **Server is the ultimate authority**; `games/` and `agent/` import nothing from `server/`;
  **contracts stay stable** (seam change → `spec/architecture.md` + contract test in the same commit);
  **secrets stay in the agent's `.env`**.
- **Ask on ambiguity.** If an issue's scope is unclear, ask rather than guess.
- **Progress updates.** Print a short status line after each issue.
