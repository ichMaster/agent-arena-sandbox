---
name: ship-solution
description: Ship the WHOLE solution end-to-end from the already-generated issues files. Per version - reconcile-issues, execute-issues-file (no GitHub), review-and-fix-issues, release-version vXX.YY.00 - timing each version. HARDEN automatically after each phase. At the end, generate a detailed execution report (per-version + per-phase + total statistics and timings). A simplified, file-driven, offline sibling of ship-phase.
---

# Skill: Ship Solution

Build the **entire solution end-to-end from the already-generated issues files** — no issue
generation, no GitHub. It walks every phase's versions in order and, per version, reconciles the
pre-written issues against reality, executes them from the file, reviews-and-fixes, and releases —
**timing each version** — hardens automatically at each phase boundary, and finally **generates a
detailed execution report** with statistics and timings summarized **by version, by phase, and in
total**.

This is a simplified, offline sibling of `/ship-phase`. The differences (by ship-phase step):

| ship-phase step | here |
|---|---|
| 0. reconcile (inside generate) | **`reconcile-issues`** — review the *pre-generated* issues file and correct drifted issues **in place, with a `⟳ Reconciled` change-mark** |
| 1. generate-issues | **skipped** — the `vXX.YY-issues.md` files already exist |
| 2. upload-issues | **skipped** — no GitHub |
| 3. execute-issues | **`execute-issues-file`** — implement straight from the file (no GitHub, no issue-closing) |
| 4. review-and-fix-issues | **kept** (unchanged) |
| 5. release-version | **kept** (unchanged) |
| end-of-phase HARDEN | **same** — automatic after every phase (ship-phase can opt out with `--no-harden`; here there is no opt-out) |
| per-phase chat report | **replaced** — a single **detailed report** generated after **all** phases |

A **thin orchestrator**: it sequences the sub-skills (`reconcile-issues`, `execute-issues-file`,
`review-and-fix-issues`, `harden-findings`, `release-version`), gates between them, **measures
per-version execution time**, and writes the final report.

> **This pipeline releases.** Invoking `/ship-solution` opts into automated per-version releases (real
> tags + pushes) **and** the automatic per-phase HARDEN. To build without releasing, use the
> individual skills.

## Usage

```
/ship-solution [phase|version|range]
```

- `/ship-solution` — ship **the whole solution**: every version with a `spec/implementation/
  vXX.YY-issues.md`, in roadmap order, then generate the final report.
- `/ship-solution v03` — just phase v03's versions (still hardened + reported at the end).
- `/ship-solution v02-v04` — phases v02 through v04.

## Instructions

### Step 0: Scope, baseline, plan — and start the clock

1. Normalize the argument to a **phase** (`vXX`), a **version** (`vXX.YY`), or a **range** — default:
   **all**.
2. Build the ordered plan from the **issues files present**: read
   [spec/roadmap.md](../../../spec/roadmap.md) for phase/version order and include each `vXX.YY` that
   has a `spec/implementation/vXX.YY-issues.md`. Group versions under their phase, in order.
3. Confirm the working dev branch + a clean tree; establish a **green baseline** (`pytest` + strict
   `mypy`) and **record the baseline test count** (the "before" for statistics). Never start red.
4. **Skip already-shipped versions** (release tag `vXX.YY.00` exists); resume a partial version
   from its remaining steps (sub-skills are idempotent).
5. **Start the run clock:** capture `RUN_START=$(date +%s)`. Keep a **running stats table** as you go
   (append each version's row as it finishes to **`.ship-solution-progress.md`** in the repo root — it
   is gitignored — so a long run never loses a measurement).
6. **Confirm the plan once**, then run — don't re-confirm each sub-step; pause only for the blockers in
   the rules.

### Step 1: For each phase → for each version — timed, gated

Run versions **strictly in sequence** — version N+1 only after N is **released** (so N+1's issues
reconcile against N's real, fixed, released code). Invoke each sub-skill via the **Skill tool**.

**At the phase's first version, stamp `PHASE_START=$(date +%s)`.** For **each version**:

- **Stamp `V_START=$(date +%s)`** (before reconcile).
1. **`reconcile-issues vXX.YY`** — correct the pre-generated issues **in place with a dated `⟳
   Reconciled` mark**; commit the file. (No code implemented here.)
2. **`execute-issues-file vXX.YY`** — implement each issue from the reconciled file in dependency order
   → validate (`pytest` + strict `mypy`, **LLM mocked**) → commit (one issue = one commit) → push;
   write `vXX.YY-execution-report.md`. **No GitHub.**
3. **`review-and-fix-issues vXX.YY`** — the ranked review doc + **fix-now** fixes only (with regression
   tests), recorded in that doc.
4. **`release-version vXX.YY.00`** — bump + tag `vXX.YY.00` + push.
- **Stamp `V_END=$(date +%s)`** (after release). **Record the version's row:** duration
  `V_END − V_START`, plus the stats collected below.

**Per-version statistics to record** (for the final report):
- **duration** (mm:ss);
- **reconcile:** # issues corrected / marked moot / untouched;
- **execute:** # issues implemented, commit count (or hash range), **tests before → after**;
- **review:** # findings fix-now (fixed) / deferred (by severity);
- **release tag.**

Gate the hand-offs: reconcile → execute → review → release; **release only after the review's fix-now
items are committed and the suite is green**; the **next version only after this one is released**.
Do **not** report to chat between versions.

### Step 2: End of every phase — HARDEN (automatic), then close the phase clock

When a phase's last version is released, run the sweep **automatically** (invoking `/ship-solution` is
the standing consent): invoke **`harden-findings vXX --release`** — it fixes every still-unfixed 🔴
HIGH / 🟠 MEDIUM finding from the run's code-review reports (each with a regression test), updates those
reports, and ships a **`ZZ` patch** on the phase's latest version (🟡 LOW stays deferred; the escape
hatch still applies). **Stamp `PHASE_END=$(date +%s)`** and record the phase's row: total duration
(`PHASE_END − PHASE_START`), versions, issues, commits, HARDEN findings fixed + patch tag. Then
continue. **No per-phase chat report.**

### Step 3: Generate the final execution report (statistics + timings)

Only after the **whole scope** is shipped (or the run stops), stamp `RUN_END=$(date +%s)` and
**generate `spec/implementation/ship-solution-report.md`** — a detailed report with **timings and
statistics summarized by version, by phase, and in total**. Commit + push it, and print its summary to
chat. Structure:

```markdown
# Ship-Solution Execution Report — <date>

## Total
- Wall-clock: <Hh Mm Ss>  (RUN_END − RUN_START)
- Phases: <n> · Versions: <m> · Issues executed: <k> · Commits: <c>
- Releases: <all vXX.YY.ZZ tags>
- Findings: fix-now fixed <a> · hardened HIGH/MEDIUM <b> · LOW deferred <c> · held <d>
- Reconcile: issues corrected <x> · moot <y> · untouched <z>
- Suite: <baseline> → <final> tests passing · mypy --strict clean · zero paid calls

## By phase
| Phase | Versions | Duration | Issues | Commits | Reconciled (corr/moot) | Fix-now | Hardened | Release tags | HARDEN patch |
|-------|----------|----------|--------|---------|------------------------|---------|----------|--------------|--------------|
| v0X   | …        | mm:ss    | …      | …       | …                      | …       | …        | …            | …            |

## By version
| Version | Duration | Issues | Commits | Tests (before→after) | Reconcile (corr/moot/kept) | Review (fix-now/deferred) | Release tag |
|---------|----------|--------|---------|----------------------|----------------------------|---------------------------|-------------|
| v0X.YY  | mm:ss    | …      | …       | … → …                | …                          | …                         | v0X.YY.00 |

## Timings
- Fastest / slowest version (with durations); average per version; per-phase totals.

## Notes
- Anything held via an escape hatch, anything that stopped early (with what remains), the reconcile
  highlights (notable issue corrections).
```

Durations: compute from the epoch stamps (`end − start`); render `mm:ss` per version, `Hh Mm` for
phases/total. Every number must trace to the run (execution reports, review docs, release tags).

## Important Rules

- **File-driven, no GitHub.** Issues come from `spec/implementation/*-issues.md`; nothing is uploaded to
  or closed on GitHub.
- **Reconcile, don't regenerate.** Step 1 corrects the pre-generated issues in place (with `⟳
  Reconciled` marks), the file-driven analogue of ship-phase's reconcile.
- **Time every version.** Stamp `date +%s` at each version's start/end (and each phase's start/end and
  the run's start/end); persist rows as you go so no measurement is lost.
- **Release per VERSION**, after its fix-now items are fixed; **next version only after the previous is
  released**. Never batch versions; never release mid-version.
- **HARDEN runs automatically at each phase boundary** and ships a `ZZ` patch; only LOW stays deferred.
- **One report, at the end** — the generated `ship-solution-report.md` (statistics + timings by
  version/phase/total) plus its chat summary. No per-version or per-phase chat report.
- **Sequential and gated; stop on failure.** Any sub-skill failure or a red `pytest`/`mypy` halts the
  pipeline; report what completed and what remains, and still generate the report for the versions that
  shipped. Never release a version whose suite isn't green.
- **Every fix ships a regression test; the LLM is always mocked** (no paid calls); the suite stays green
  and deterministic.
- **Delegate, never duplicate.** This skill sequences the sub-skills, gates, times, and reports — no
  other logic. Each sub-skill keeps its discipline (one issue = one commit, seam changes carry
  `spec/architecture.md` + contract test, unprefixed `vXX.YY.ZZ` tags, every line generated fresh).
- **Surface real decisions** — a tag collision, a held HARDEN finding, an ambiguous reconcile, or any
  execution/validation failure.
