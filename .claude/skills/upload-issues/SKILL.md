---
name: upload-issues
description: Upload issues from a phase issues file to GitHub one by one with proper labels and dependencies.
---

# Skill: Upload Version Issues to GitHub

Upload issues from a phase issues file to GitHub one by one, with proper labels
(prefixed by version) and dependencies.

## Usage

```
/upload-issues <phase-issues-file>
```

Example: `/upload-issues @spec/implementation/v01.02-issues.md`

A phase issues file is the fine-grained breakdown of a ROADMAP phase (`vXX.YY`): each
phase in [spec/roadmap.md](../../../spec/roadmap.md) is split into one or more
`ARENA-###` issues by `/generate-issues`. If the file does not exist yet, run
`/generate-issues <phase>` first, then this skill.

## Instructions

### Step 1: Read the phase issues file

Read the provided file (e.g., `spec/implementation/v{XX.YY}-issues.md`).

Determine from the file:
- **Version number** (XX): the roadmap version the phase sits under (e.g. `v01.02` → `01`).
- **Phase** (XX.YY): from the filename or heading (e.g., `v01.02-issues.md` → `v01.02`).
- **Label prefix**: `v{XX.YY}::` (e.g., `v01.02::`).

Parse the **Issues Summary Table** to extract for each issue:
- `ID` (e.g., ARENA-001)
- `Title`
- `Size` (S, M, L)
- `Area` (the component: `games`, `server`, `agent`, `web`, `profiles`, `scripts`, `tests`)
- `Phase` (the ROADMAP phase it implements, e.g. `v01.02`)
- `Dependencies` (list of ARENA-### IDs)

Then parse each **detailed issue section** (heading with ARENA-###) to extract:
`Description`, `What needs to be done`, `Dependencies`, `Expected result`,
`Acceptance criteria` (should align with the phase DoD in roadmap.md).

### Step 2: Confirm with user

Show the user a summary of what will be created: number of issues, label prefix (e.g.,
`v01.02::`), the full list of labels, and ask for confirmation before proceeding.

### Step 3: Create labels (if they don't exist)

All labels MUST be prefixed with `v{XX.YY}::`. Label format: `v{XX.YY}::{category}:{value}`.

Version titles: **v01 — Game Core & Server Foundation**; **v02 — Agent Client (Haiku)**;
**v03 — Web UI (Player & Observer)**; **v04 — Agent-vs-Agent Orchestration**;
**v05 — Hardening & Polish**.

```bash
# Phase label
gh label create "v01.02::phase" --color "0E8A16" --description "Phase v01.02" 2>/dev/null || true

# Size labels
gh label create "v01.02::size:S" --color "28A745" --description "Small (1-2 days)" 2>/dev/null || true
gh label create "v01.02::size:M" --color "FFC107" --description "Medium (3-5 days)" 2>/dev/null || true
gh label create "v01.02::size:L" --color "DC3545" --description "Large (5-8 days)" 2>/dev/null || true

# Area labels (one per component touched in this phase)
gh label create "v01.02::area:games"  --color "6F42C1" 2>/dev/null || true
gh label create "v01.02::area:server" --color "1D76DB" 2>/dev/null || true
gh label create "v01.02::area:agent"  --color "0E8A16" 2>/dev/null || true
# ... web / profiles / scripts / tests as needed
```

### Step 4: Create issues ONE BY ONE

**IMPORTANT:** Issues must be created one at a time, sequentially. After creating each
issue, show the user the result (issue number, URL) and proceed to the next immediately
(do not wait for confirmation between issues).

For each issue (in order from the summary table):

1. Build the issue body in markdown:

```markdown
## Description
{description}

## What needs to be done
{full content}

## Dependencies
{dependency list, with references to already-created issue numbers}

## Expected result
{expected result}

## Acceptance criteria
{checklist}

---
**ID:** {ARENA-###}
**Size:** {S/M/L}
**Version:** v{XX}
**Area:** {games/server/agent/web/profiles/scripts/tests}
**Phase:** {vXX.YY from roadmap}
```

2. Create the issue with a single `gh issue create` command (one issue per command, never batch):

```bash
gh issue create \
  --title "ARENA-###: {title}" \
  --label "v01.02::phase,v01.02::size:{S/M/L},v01.02::area:{area}" \
  --body "$(cat <<'BODY'
{issue body}
BODY
)"
```

3. Record the mapping: ARENA-### -> GitHub issue #number
4. Report to user: `Created ARENA-### -> #{number}: {title}`
5. If the issue depends on already-created issues, add a comment:
   ```bash
   gh issue comment {issue-number} --body "Blocked by #{dep-issue-number} (ARENA-###)"
   ```
6. Move to the next issue.

### Step 5: Generate report

After all issues are created, generate `spec/implementation/v{XX.YY}-github-report.md`:

```markdown
# Phase v{XX.YY} -- GitHub Issues Report

**Uploaded:** {date}
**Repository:** {github repo URL}
**Total issues:** {count}

## Issue Mapping

| ARENA ID | GitHub # | Title | Phase | Labels | URL |
|----------|----------|-------|-------|--------|-----|
| ARENA-001 | #5 | ... | v01.02 | v01.02::phase, v01.02::size:S, v01.02::area:games | {url} |

## Labels Created

- v{XX.YY}::phase
- v{XX.YY}::size:S, v{XX.YY}::size:M, v{XX.YY}::size:L
- v{XX.YY}::area:{list}
```

### Step 6: Report to user

Show the user: total issues created, link to the GitHub issues page, path to the
generated report file.

## Error Handling

- If `gh` is not authenticated, tell the user to run `gh auth login`
- If the repo has no GitHub remote yet, tell the user to create one (`gh repo create`) before uploading
- If an issue already exists with the same title, skip it and note in the report
- If label creation fails, continue (labels may already exist)
- On any failure, report what was created so far and what remains
