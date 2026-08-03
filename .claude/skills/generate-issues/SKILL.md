---
name: generate-issues
description: Decompose a roadmap phase into a per-phase GitHub-issues file at spec/implementation/, ready for /upload-issues.
---

# Skill: Generate Version Issues

Decompose one ROADMAP **phase** (`vXX.YY`) into a fine-grained, dependency-ordered
**issues file**, written to `spec/implementation/`. The output is the input to
`/upload-issues` (which pushes it to GitHub) and then `/execute-issues` (which
implements it).

## Usage

```
/generate-issues <phase>
```

- `/generate-issues 01.02` — decompose ROADMAP phase **v01.02** → `spec/implementation/v01.02-issues.md`
- `/generate-issues v02.01` — phase **v02.01** → `…/v02.01-issues.md`

One file per **phase** (`vXX.YY`). IDs (`ARENA-###`) are **globally sequential** and
continue across phase files **and across regeneration runs** — never reset.

## Instructions

### Step 0: Read inputs

1. Normalize the phase to `vXX.YY` (zero-padded, e.g. `1.2` → `v01.02`).
2. Read [spec/roadmap.md](../../../spec/roadmap.md) §`vXX.YY` — the phase's **Goal**,
   **Tasks**, **DoD**, and **Tests** (and the version heading it sits under).
3. Read [spec/architecture.md](../../../spec/architecture.md) for the contracts and
   components the phase touches, and [spec/game_specification.md](../../../spec/game_specification.md)
   for the product vision and scope (MVP vs later).
4. Read `CLAUDE.md` for code conventions, the module map, and the non-negotiable seams.
5. **Find the next free `ARENA-###` id — never restart the numbering.** Ids are globally
   sequential across every phase *and every regeneration run*. Check **both** sources and
   continue from whichever is higher:

   ```bash
   # (a) GitHub — the durable source: issues survive a wiped working tree
   gh issue list --state all --limit 1000 --json title \
     --jq '.[].title | capture("ARENA-(?<n>[0-9]+)").n' 2>/dev/null | sort -n | tail -1

   # (b) local issues files — covers ids drafted but not yet uploaded
   grep -rhoE 'ARENA-[0-9]+' --include='*-issues.md' spec/implementation/ 2>/dev/null \
     | grep -oE '[0-9]+' | sed 's/^0*//' | sort -n | tail -1
   ```

   (Pass the directory with `--include`, not a `*-issues.md` glob — under zsh an unmatched glob
   aborts the command before `2>/dev/null` can swallow it, and `spec/implementation/` may not exist.)

   The next id is **`max(a, b) + 1`**, zero-padded to three digits (`ARENA-001`, `ARENA-047`,
   `ARENA-118`). Start at `ARENA-001` **only if both sources come back empty**.

   > `spec/implementation/` is cleared between regeneration runs, so scanning it alone would
   > silently restart the sequence at 001 and collide with ids already on GitHub. That is why (a)
   > is checked first and the two are combined rather than either being trusted on its own. If
   > `gh` is unauthenticated or the repo has no issues, (a) yields nothing and (b) governs — say
   > so in the report rather than silently assuming the sequence is fresh.
6. If `…/v{XX.YY}-issues.md` already exists, ask whether to overwrite or append.

### Step 0.5: Reconcile with the real implementation

Before decomposing, ground the new `vXX.YY` in **what was actually built and fixed** — not just what
`architecture.md` describes. Earlier `vXX.YY`s may have drifted the code from the docs via review
fixes and hardening; the new issues must build on reality. This step is the **reconciliation after
fixes**: it always runs right after the previous `vXX.YY` was implemented + fixed (+ released, in the
`/ship-phase` pipeline), and its inputs are the real code plus the fix records listed below.

1. For the components this phase touches (route by [architecture.md](../../../spec/architecture.md) §2),
   read the **real current code** — the actual seams, method signatures, and behaviors as implemented,
   not only the design in `architecture.md`.
2. Read the completed phases' `spec/implementation/v*-execution-report.md` and any
   `spec/implementation/*code-review*.md` — especially their **"Fixes applied" / "Architecture impact"**
   notes — to see what changed during implementation, review, and hardening.
3. **Reconcile:** if `architecture.md` is stale relative to a landed fix (a seam or contract evolved),
   treat the **real implementation as ground truth** for this phase's issues, and note the drift. If a
   contract genuinely changed but the doc wasn't updated, flag it and prefer correcting `architecture.md`
   in the seam-touching issue (with its contract test). Decompose against the **actual** current
   contracts so the new issues don't re-assume a design the code has already moved past.

### Step 1: Decompose the phase

Turn the phase's **Tasks** into a small set of issues (typically **3–7**), each a
coherent, independently shippable slice:

- Size each **S** (1–2 d) / **M** (3–5 d) / **L** (5–8 d).
- Order by dependency; the first issue is usually the **gate** (the seam/structure
  everything else builds on).
- Map each issue to part of the phase Tasks; together they must satisfy the phase **DoD**.
- **Bake tests into every issue** (the LLM is always mocked — no paid calls): unit for
  pure logic, contract for any seam, an integration turn where relevant.
- A seam change — `GameInterface` (§4.1), `LLMClient` (§4.2), the WebSocket event/action
  protocol (§6.2), or the seat-by-token identity model (§5.2) — carries a
  `spec/architecture.md` update + its contract test in the **same** issue.
- Stay **within the phase** — don't pull later phases' scope in early (MVP-first per
  the §2 scope table).

### Step 2: Write the issues file

Write `spec/implementation/v{XX.YY}-issues.md` using **exactly** this format:

````markdown
# v{XX.YY} — GitHub Issues

Issues for phase **v{XX.YY} — {phase title}** (version **v{XX} — {version title}**),
derived from the per-phase Tasks in [roadmap.md](../roadmap.md) (§v{XX.YY}) and the
contracts in [architecture.md](../architecture.md) ({the relevant § sections}).
This file is scoped to a single phase; IDs continue from the previous phase
(ARENA-{prev} → **ARENA-{first}…{last}**).

{1–3 sentences: what the phase does, the seams it extends, why now.}

## Issues Summary Table

| # | ID | Title | Size | Area | Phase | Dependencies |
|---|----|-------|------|------|-------|--------------|
| 1 | ARENA-{first} | {title} | M | {games/server/agent/web} | v{XX.YY} | -- |
| 2 | ARENA-{…} | {title} | S | {area} | v{XX.YY} | ARENA-{first} |
| … | … | … | … | … | … | … |

**Size legend:** S = 1–2 days, M = 3–5 days, L = 5–8 days

---

## Dependency Tree

```
ARENA-{first} ({gate})
  |
  +-- ARENA-{…} (…) --+
  |                   |
  +-- ARENA-{…} (…) --+
                      |
             ARENA-{…} (…)  => {phase DoD}
```

**Parallelization hints:** {which gate first; what runs in parallel after}.

---

## v{XX.YY} — {phase title}

### ARENA-{id} — {Title}

**Description:**
{1–3 sentences. Note which module(s) it touches: games/server/agent/web/profiles/scripts/tests.}

**What needs to be done:**
- {bullet}
- {bullet}

**Dependencies:** {ARENA-ids, or None}

**Expected result:**
{one sentence}

**Acceptance criteria:**
- [ ] {functional criterion}
- [ ] **Contract test:** {seam pinned} — *(only if a seam changes)*
- [ ] **Unit test:** {pure logic} with the **LLM mocked** (no paid call)
- [ ] {ties to the phase DoD}

---

{repeat the `### ARENA-{id} …` block per issue}

## v{XX.YY} scope notes

**Total effort:** {rough estimate}.
**Critical path:** ARENA-{…} → … → ARENA-{…}.
**Phase DoD (roadmap §v{XX.YY}):** {restate the DoD}.
**Contracts pinned this phase:** {the seams + their tests}.
**Model note:** the agent's model (Anthropic Haiku) runs behind the `LLMClient` seam;
**no paid APIs** — the seam is mocked for unit + integration tests.
**Companion documents:**
- [roadmap.md](../roadmap.md) — version goals, per-phase Tasks/DoD/Tests (§v{XX.YY}).
- [architecture.md](../architecture.md) — {the relevant § sections}.
- Generated on upload: `v{XX.YY}-github-report.md` (ARENA-### → GitHub #), then `v{XX.YY}-execution-report.md`.
````

### Step 3: Report

Show the user: the file path, the issue count, the `ARENA-###` id range, and the
critical path. Suggest the next step:

```
/upload-issues @spec/implementation/v{XX.YY}-issues.md
```

(Do **not** create GitHub issues here — that's `/upload-issues`. This skill only writes
the local issues file.)

## Important Rules

- **One file per phase** (`vXX.YY`) at `spec/implementation/v{XX.YY}-issues.md`.
- **IDs are globally sequential** (`ARENA-###`), continuing across phase files **and across
  regeneration runs** — never reset. Resolve the next id from `max(GitHub, local issues files) + 1`
  (Step 0.5); starting at `ARENA-001` is correct only when both sources are genuinely empty.
- **Tests in every issue.** Acceptance criteria include the unit/contract/integration tests; the LLM is mocked, never a paid call.
- **Seam = ARCHITECTURE + test together.** Any contract change lands its `spec/architecture.md` update and contract test in the same issue.
- **Scope to the phase.** Map issues to the phase's Tasks/DoD; don't pull later phases in early (MVP-first, simplicity-first).
- **Honor the DoD.** The issues together must satisfy the phase DoD in roadmap §v{XX.YY}.
- **Ask on ambiguity.** If the phase's Tasks are unclear or under-specified, ask the user before inventing scope.
- **Don't touch GitHub.** This skill writes only the local file; `/upload-issues` pushes it.
