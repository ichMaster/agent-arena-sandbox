---
name: execute-issues
description: Execute GitHub issues for a phase sequentially - implement, validate, commit, push, and generate a report.
---

# Skill: Execute GitHub Issues

Execute GitHub issues for a phase sequentially: implement, validate, commit, push, and
generate a report.

## Usage

```
/execute-issues <label> [--issue ARENA-###] [--dry-run]
```

The `<label>` is the GitHub phase label exactly as it appears (e.g., `v01.02::phase`).

- `/execute-issues v01.02::phase` -- execute all issues labeled `v01.02::phase`
- `/execute-issues v01.02::phase --issue ARENA-003` -- execute a single issue from that phase
- `/execute-issues v01.02::phase --dry-run` -- show execution plan without making changes

> [!IMPORTANT]
> **Generate every line fresh.** Every line of code, test, script, and config must be written by the
> executing agent in-session. A complete earlier build of this same spec exists in this repo's git
> history (on `main`, tagged `v05.03.00`). Never `git checkout`, `git cherry-pick`, or otherwise
> recover code from history or any other ref to satisfy an issue — the generated run is the point.

## Instructions

### Step 0: Verify prerequisites

1. Confirm we are on the expected branch (the current working dev branch)
2. Confirm working tree is clean (`git status`)
3. Confirm `gh` is authenticated
4. Parse the label to determine the phase: label `v01.02::phase` -> phase `v01.02`
5. Fetch issues from GitHub:
   ```bash
   gh issue list --label "{label}" --state open --limit 100
   ```
6. Read the phase issues file for detailed descriptions: `spec/implementation/v{XX.YY}-issues.md`
7. If a GitHub report exists (`spec/implementation/v{XX.YY}-github-report.md`), read the ARENA-to-GitHub# mapping
8. Read [spec/roadmap.md](../../../spec/roadmap.md) for the version goal and the phase (`vXX.YY`) DoD/Tests, [spec/architecture.md](../../../spec/architecture.md) for the contracts the issue must honor, and [spec/game_specification.md](../../../spec/game_specification.md) for the product scope (MVP vs later).

### Step 1: Build execution queue

From the GitHub issue list, build an ordered queue based on dependencies:
- Parse ARENA-### IDs from issue titles (format: `ARENA-###: {title}`)
- Determine dependency order from the phase issues file dependency tree
- Issues with no unmet dependencies go first
- Closed issues are already excluded (Step 0 fetches `--state open`), so a re-run resumes where the
  last one stopped
- If `--issue ARENA-###` is specified, execute only that issue (but verify its dependencies are closed)

Show the user the execution plan and ask for confirmation.

### Step 2: Execute each issue (loop)

For each issue in the queue:

#### 2a. Assign and announce

Print: `--- Starting ARENA-###: {title} ---`

#### 2b. Read issue details

Read the full issue description from the phase issues file (the detailed section for this ARENA-###).

#### 2c. Implement

Execute the tasks described in the issue. Follow the conventions in `CLAUDE.md` and the
architecture in `spec/architecture.md`. Route by component ([architecture.md](../../../spec/architecture.md) §2):

- **Games** (`games/`): the abstract `GameInterface` and concrete engines (TicTacToe). Pure logic — imports nothing from `server/`. `apply_move` is the sole legality authority.
- **Server** (`server/`): FastAPI app, the SQLite `Repository`/models/database, the `ConnectionManager`, seat/identity (`match.py`, `auth.py`), the WebSocket event/action protocol. The **server is the ultimate authority** — every move re-validated server-side; seats keyed by per-connection token, never by name; observers never hold a seat.
- **Agent** (`agent/`): the Agent CLI, the `LLMClient` seam + the Anthropic Haiku client (the only vendor impl), prompt/memory/profile. The agent imports nothing from `server/` — it is a pure external client over HTTP/WS.
- **Web** (`web/`): the vanilla HTML/CSS/JS UI served at `/ui`; a stateless renderer of server events (Player and Observer roles) — no client-side game state, no build step.
- **Contract changes:** any change to a stable seam — `GameInterface` (§4.1), `LLMClient` (§4.2), the WebSocket event/action shapes (§6.2), or the seat-by-token identity model (§5.2) — updates `spec/architecture.md` **AND** its contract test, in the same commit.
- Follow existing style/patterns; keep each phase self-contained (don't pull later phases in early — MVP-first, simplicity-first). Use strict typing in Python.

#### 2d. Validate

Run validation checks (Python):

1. **Tests:** `pytest` for the changed packages (unit + the contract tests pinning the seams), where tests exist.
2. **Types:** `mypy games server agent` — strict mode comes from `[tool.mypy] strict = true` in
   `pyproject.toml`. **Do not pass `--config-file mypy.ini`:** no `mypy.ini` is generated, and mypy
   treats a missing config as a hard error (`mypy: error: Cannot find config file 'mypy.ini'`) and
   type-checks nothing — so the gate silently stops being a gate. Pass only the packages that exist
   yet. Fix any error you introduce.
3. **Syntax/import:** `python3 -m py_compile {changed_py_files}` and an import check for changed modules.
4. **Contract consistency:** the touched seams match `spec/architecture.md` and their contract tests.
5. **Acceptance criteria:** go through each criterion from the issue and verify against the phase DoD/Tests in `spec/roadmap.md`.

Record pass/fail for each check. **Tests are part of the work.** No paid APIs in
validation/CI: **the `LLMClient` seam is always mocked**, never a live model call.

#### 2e. Commit

```bash
git add {specific files created/modified}
git commit -m "$(cat <<'EOF'
ARENA-###: {title}

{1-2 sentence summary of what was implemented}

Closes #{github-issue-number}

Co-Authored-By: <the running model's trailer> <noreply@anthropic.com>
EOF
)"
```

#### 2f. Push

```bash
git push
```

#### 2g. Close issue with summary

```bash
gh issue close {issue-number} --comment "$(cat <<'EOF'
## Implementation Summary

**Commit:** {commit-hash}
**Files changed:** {count}

### What was done
{bullet list of key changes}

### Validation
{pass/fail status for each check}

### Acceptance criteria
{checklist with pass/fail}
EOF
)"
```

#### 2h. Log progress

Append to the in-memory execution log: issue ID + title, commit hash, files changed,
validation results, status (success/partial/failed).

### Step 3: Handle failures

If implementation or validation fails for an issue:

1. Do NOT commit broken code
2. Revert changes: `git checkout -- .`
3. Add a comment to the GitHub issue explaining what failed
4. Log the failure
5. Ask the user: continue to next issue (if no dependency), or stop?

### Step 3b: No automatic version bump

**Do NOT bump the version automatically.** Never change the version (VERSION file,
RELEASE.txt, or git tag) without explicit user confirmation. When a phase's issues are
all done, report completion and let the user decide whether/when to release via
`/release-version`.

Version notation `vXX.YY.ZZ`: `XX` = roadmap version (v01…v05), `YY` = phase, `ZZ` =
post-release fix. Roadmap phase `vXX.YY` → release `vXX.YY.00`. If some issues failed or
were skipped, do NOT release — note in the report that the phase is incomplete.

### Step 4: Generate execution report

After all issues are processed (or on stop), generate `spec/implementation/v{XX.YY}-execution-report.md`:

```markdown
# Phase v{XX.YY} -- Execution Report

**Date:** {date}
**Branch:** {branch name}
**Label:** {label}
**Target release:** v{XX.YY}.00
**Executed by:** Claude Code

## Summary

| Status | Count |
|--------|-------|
| Completed | {n} |
| Failed | {n} |
| Skipped | {n} |
| Remaining | {n} |

## Issues

| # | ARENA ID | Title | Phase | Status | Commit | Files | Tests |
|---|----------|-------|-------|--------|--------|-------|-------|
| 1 | ARENA-001 | ... | v01.02 | completed | a1b2c3d | 4 | pass |

## Detailed Results

### ARENA-001: ...
**Status:** completed · **Commit:** a1b2c3d
**Validation:** [x] tests · [x] mypy · [x] acceptance

## Next Steps
{remaining issues + dependencies}
```

Commit and push the report (`ARENA`-style message, with the Co-Authored-By trailer).

## Important Rules

- **Generate every line fresh.** Never `git checkout`/`cherry-pick`/merge code out of git history or any other ref to satisfy an issue — every line is written in-session.
- **One issue at a time.** Never work on multiple issues simultaneously.
- **Dependency order.** Never start an issue whose dependencies are not closed.
- **Clean commits.** Each issue = one commit. No mixing work across issues.
- **No broken code.** Only commit code that passes validation (tests + mypy).
- **Tests ship with the feature.** Mock the `LLMClient`; never call paid APIs.
- **Server is the ultimate authority.** LLM/client output is untrusted; re-validate every move server-side. Seats keyed by per-connection token, never by name; observers never hold a seat.
- **Core independent of interface.** `games/` and `agent/` import nothing from `server/`.
- **Contracts stay stable.** A seam change updates `spec/architecture.md` and its contract test in the same commit.
- **Secrets stay in the agent.** `ANTHROPIC_API_KEY` lives only in the agent's `.env`; never sent to or logged by the server/UI.
- **Ask on ambiguity.** If an issue description is unclear, ask the user rather than guessing.
- **Progress updates.** Print a short status line after each issue completes.
