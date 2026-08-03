---
name: ship-phase
description: Full delivery pipeline over the roadmap. Takes one selector or a comma-separated LIST of phases/versions/ranges (e.g. v01,v03.02,v04-v05), expanded and de-duplicated into a single roadmap-ordered plan. For each phase (vXX) run its versions (vXX.YY) in order - RECONCILE with the real implementation, generate-issues, upload-issues, execute-issues, review-and-fix-issues, release-version vXX.YY.00 (release per VERSION). At the END of the phase, an OPT-IN HARDEN sweep (--harden flag or explicit user approval) fixes the deferred HIGH/MEDIUM findings, then the phase is reported to chat. Gated; stops on failure; surfaces real decisions.
---

# Skill: Ship Phase — the full delivery pipeline

Drive the entire SDLC loop over the roadmap: **phases contain versions; each version is released;
the next version is generated only after the previous one is implemented and fixed** — reconciled
against the real (post-fix) implementation. Hardening of deferred findings is an **opt-in,
end-of-phase** step, never automatic.

> **Terminology (per [game_specification.md](../../../spec/game_specification.md) §6):** a **phase**
> is a top-level roadmap block `vXX` (Phase 1 → `v01` … Phase 5 → `v05`); a **version** is a `vXX.YY`
> sub-version inside it, released as `vXX.YY.00`. ⚠️ The roadmap's header and the four sub-skills use
> these words the other way around (they call `vXX.YY` a "phase" — hence the GitHub label
> `vXX.YY::phase` and the invocation `generate-issues <vXX.YY>`). The sub-skill invocations below are
> exactly as they've always been; only this skill's flow description uses the spec's wording.

**The loop:**

```
PLAN = selectors → versions → de-duplicated → sorted into roadmap order → grouped by phase

for each PHASE vXX in PLAN (in roadmap order):
    for each VERSION vXX.YY of that phase in PLAN (in order):
        0. RECONCILE   — ground this version in the real implementation + all prior fixes
        1. generate-issues vXX.YY
        2. upload-issues @spec/implementation/vXX.YY-issues.md
        3. execute-issues vXX.YY::phase        (implement → validate → commit → push → close)
        4. review-and-fix-issues vXX.YY        (review → ranked doc → fix-now fixes → same doc)
        5. release-version vXX.YY.00           ← RELEASE PER VERSION (tag vXX.YY.00)
    → END OF PHASE: HARDEN (skill: harden-findings) — OPT-IN ONLY (--harden, or ask; skipped otherwise)
    → REPORT the phase to chat
→ next phase; after the whole scope: overall summary to chat
```

This skill is a **thin orchestrator** — it sequences the sub-skills, adds the reconcile gate and the
opt-in end-of-phase hardening sweep, and releases per version; each sub-skill keeps its discipline.

> **This pipeline releases.** Invoking `/ship-phase` is the explicit opt-in to the automated
> per-version releases (real tags + pushes). `release-version`'s own rules still hold — it never
> downgrades and confirms the changelog. To build without releasing, use the individual skills.

## Usage

```
/ship-phase <selector>[,<selector>…] [--harden]
```

A **selector** is a phase (`vXX`), a version (`vXX.YY`), or a range (`vXX-vYY`). Pass **one or a
comma-separated list of any mix** — the whole list is expanded into a single ordered plan.

- `/ship-phase v02` — ship **phase v02**: every version in it (v02.01 → v02.02 → v02.03), each through
  its five steps incl. its own release; at the phase's end **ask** whether to run the HARDEN sweep;
  then the phase report to chat.
- `/ship-phase v02 --harden` — same, but the end-of-phase HARDEN sweep is **pre-approved** by the
  flag (no prompt).
- `/ship-phase v02.02` — ship the single **version v02.02** (steps 0–5, incl. its release). No HARDEN
  unless `--harden` is passed or the user approves when asked at the end.
- `/ship-phase v02-v03` — ship phase v02, then phase v03 (HARDEN asked/applied per phase), then an
  overall summary.
- `/ship-phase v01,v03,v05` — a **list of phases**, shipped in roadmap order.
- `/ship-phase v01.01,v01.03,v02` — a **mixed list**: two individual versions plus a whole phase.
- `/ship-phase v01-v02,v04.01 --harden` — a range plus a single version, hardening pre-approved.

Whitespace around commas is ignored, so `v01, v03` works. `--harden` applies to **every** phase in the
plan; there is no per-phase form.

## Instructions

### Step 0: Scope, baseline, and the phase → version plan

1. **Parse the selector list.** Split the argument on commas and trim whitespace. Each element is a
   **phase** (`vXX`), a **version** (`vXX.YY`), or a **range** (`vXX-vYY`); a single element is just a
   list of one. Record whether `--harden` was passed (it applies to the whole plan).
2. **Expand to a version set.** Read [spec/roadmap.md](../../../spec/roadmap.md) and resolve every
   selector down to individual versions (`### vXX.YY` headings under `## vXX`, in file order):
   a phase → all its versions; a range → all versions of all phases it spans; a version → itself.
   Then:
   - **De-duplicate.** Overlapping selectors (`v01,v01.02`) contribute each version once.
   - **Sort into roadmap order**, regardless of the order given. `/ship-phase v03,v01` ships v01 first.
     This is not cosmetic: the pipeline's whole premise is that each version is generated against the
     previous one's real, released code, so executing out of roadmap order would reconcile against a
     codebase that doesn't exist yet.
   - **If the sorted order differs from what was typed, say so** in the plan confirmation — the user
     asked for one order and is getting another.
   - **Group the versions back under their phases** for the per-phase HARDEN and reporting.
3. **Check the plan for gaps.** A list may legitimately skip versions (`v01,v03` omits all of v02), but
   a skipped version is a dependency hole: v03's issues reconcile against code v02 never wrote. Before
   confirming, **list the omitted versions explicitly and flag the gap** — then let the user decide.
   A gap is a warning, never a silent reorder or a refusal. Versions already shipped (step 5) are not
   gaps; they are satisfied dependencies.
4. **Reject nothing silently.** If a selector doesn't resolve to a real roadmap phase/version — a typo,
   an out-of-range `v09`, a reversed range (`v03-v01`) — name the offending element and ask. Never drop
   an unparseable element and proceed with the rest.
5. Confirm we are on the working dev branch and the tree is clean; establish a **green baseline**
   (`pytest` + strict `mypy`). Never start on a red suite — fix a clear flake first or surface it.
6. **Skip already-shipped versions** (release tag `vXX.YY.00` exists). A version partially done
   (issues/report exist but no tag) resumes from its remaining steps — each sub-skill is idempotent
   (`generate` asks overwrite, `upload` dedupes, `execute` skips closed issues, `release` refuses a
   downgrade).
7. **Confirm the plan once** — show it as the resolved, ordered version list grouped by phase, with any
   reordering, gaps, or already-shipped skips called out. Then run: do not re-confirm before each
   sub-step; pause only for the genuine blockers in the rules below.

**Worked example** — `/ship-phase v03.02,v01,v01.02 --harden`:

```
selectors : v03.02 · v01 · v01.02
expanded  : v03.02 | v01.01 v01.02 v01.03 v01.04 | v01.02
de-duped  : v01.02 appears twice → once
ordered   : v01.01 → v01.02 → v01.03 → v01.04 → v03.02      (typed order was v03 first)

PLAN
  v01  v01.01, v01.02, v01.03, v01.04   → HARDEN (pre-approved) → report
  v03  v03.02                            → HARDEN (pre-approved) → report

⚠ reordered: v03.02 was listed first, but ships last — roadmap order is required.
⚠ gaps: all of v02 (v02.01–v02.03) and v03.01 are not in the plan. v03.02's issues will
  reconcile against code those versions never wrote. Proceed?
```

### Step 1: For each phase → for each version — the five steps, gated

Run the versions **strictly in sequence** — version N+1 starts only after version N is **released**
(implemented, reviewed, fixed, tagged). That sequencing is the point: the next version's issues are
generated against the previous version's *real, fixed* implementation. Invoke each sub-skill via the
**Skill tool** (it loads that skill's instructions; follow them fully).

**0. RECONCILE** — the first act of every version's cycle, carried out **inside `generate-issues`
   (its Step 0.5)**: before decomposing `vXX.YY`, read (a) the **real current code** of the components
   it touches, (b) prior `spec/implementation/*-execution-report.md`, and (c) prior
   `spec/implementation/*code-review*.md` — especially their **"Fixes applied"** and **"Architecture
   impact"** notes from review/harden work. Where fixes drifted the code from `architecture.md`, the
   implementation is ground truth; doc corrections ride along in the seam-touching issue. This is
   where "changes in architecture after fixes" enter the next version's issues.
1. **`generate-issues vXX.YY`** → `spec/implementation/vXX.YY-issues.md` (reconciled, per step 0).
2. **`upload-issues @spec/implementation/vXX.YY-issues.md`** → the GitHub issues + labels + deps +
   `vXX.YY-github-report.md`.
3. **`execute-issues vXX.YY::phase`** → implement → validate → commit → **push** → close each issue in
   dependency order (statuses change; one issue = one commit), then `vXX.YY-execution-report.md`.
4. **`review-and-fix-issues vXX.YY`** → code review, the criticality-ranked recommendations doc, the
   **fix-now** fixes only (with regression tests, LLM mocked), results recorded **in that same doc**
   (incl. "Architecture impact" notes). Deferred findings stay deferred — they are the HARDEN sweep's
   input, at the end of the phase, if the user opts in.
5. **`release-version vXX.YY.00`** → bump `VERSION`/`RELEASE.txt`/the app version, tag `vXX.YY.00`
   (unprefixed — this repo is standalone and nothing collides), and push. **Release per version.**

Gate the hand-offs: upload only after generate wrote the file; execute only after the issues exist;
review only after execute closed the issues with a green report; **release only after the review's
fix-now items are committed and the suite is green**; the **next version only after this one is
released**.

### Step 2: END OF PHASE — HARDEN (opt-in only)

When the phase's last version is released, the deferred 🔴 HIGH / 🟠 MEDIUM findings accumulated in the
run's code-review reports *may* be swept — **but only with explicit user consent**:

- **`--harden` was passed** → the sweep is pre-approved; run it.
- **No flag** → **ask the user now** (one clear question at the phase boundary, listing the
  outstanding HIGH/MEDIUM findings and their sources): run the hardening sweep for this phase, or
  skip? **If declined — or no approval is available — skip the sweep entirely.**
- **Never run HARDEN un-asked.** Skipped findings simply remain deferred to their documented homes
  (e.g. v05.01) and are listed in the phase report.

**When approved, delegate the sweep to the dedicated skill:** invoke **`harden-findings vXX
--release`** via the Skill tool and follow its instructions fully. That skill collects the run's
code-review reports, fixes every still-unfixed 🔴 HIGH / 🟠 MEDIUM finding (🟡 LOW stays deferred) —
each with a regression test, validated green, one focused commit — updates the reports in place
("Fixes applied" + "Architecture impact", which the next phase's RECONCILE reads), and, because the
phase's versions are already released, ships the result as a **`ZZ` patch release** on the phase's
latest version (e.g. `v02.03.01`). Its escape hatch (a fix that can't land safely is held with a
reason and surfaced) applies unchanged.

### Step 3: REPORT the phase to chat

After the phase (and its HARDEN sweep, if approved), **report the phase to chat** (not a file):
- **Per version:** ARENA id range → GitHub #s, execution commit range + test/typing status, review
  finding counts (**fixed-now / deferred**, with homes), any **Architecture impact** deltas, and the
  release tag.
- **HARDEN outcome:** ran (which findings were fixed, the patch tag) / declined / not offered — plus
  the still-outstanding HIGH/MEDIUM findings and their homes if skipped.
- **Phase rollup:** what the phase delivered against its roadmap goal.

Then continue to the next phase. After the whole scope, add a short **overall summary** (phases
shipped, versions skipped as already-released, anything stopped early and what remains, what's next).

## Important Rules

- **Release per VERSION (`vXX.YY.00`)** — after that version is built, reviewed, and its fix-now items
  fixed. Never batch several versions into one release; never release mid-version.
- **HARDEN is end-of-phase and OPT-IN only.** It runs solely when `--harden` was passed or the user
  explicitly approves at the phase boundary. Never run it unrequested; when skipped, the deferred
  HIGH/MEDIUM findings stay in their documented homes and are surfaced in the phase report. When it
  does run and lands fixes, ship them as a `ZZ` patch release on the phase's latest version.
- **Next version only after the previous is released.** The strict sequencing is what makes the
  RECONCILE step meaningful: version N+1's issues are generated against version N's real, fixed code.
- **Reconciliation is step 0 of every version** (via `generate-issues` Step 0.5): real code + execution
  reports + review docs' "Fixes applied"/"Architecture impact" are the input to the next version's
  issues; `architecture.md` corrections ride along in seam-touching issues.
- **Sequential and gated.** Each step's output is the next step's input. Never start a step whose
  predecessor didn't finish cleanly; never interleave two versions' pipelines.
- **Stop on failure — do not paper over it.** If any sub-skill fails, or any fix hits a red
  `pytest`/`mypy`, halt, report what completed and what remains, and let the user decide. Never release
  a version whose suite isn't green.
- **Every fix ships a regression test**, the LLM is always mocked (no paid calls), and the suite stays
  green and deterministic.
- **Surface real decisions.** Pause for an **ID/tag collision**, an **overwrite/append** prompt, the
  **HARDEN approval question**, a held
  finding, or any execution/validation failure. Routine plan confirmations run straight through.
- **Delegate, never duplicate.** This skill only sequences the sub-skills (`generate-issues`,
  `upload-issues`, `execute-issues`, `review-and-fix-issues`, `harden-findings`, `release-version`)
  and adds the gating; no logic of its own. Each sub-skill keeps its discipline — one issue = one
  commit, seam changes carry `spec/architecture.md` + contract test, IDs stay in this branch's
  `ARENA-###` namespace, releases use unprefixed `vXX.YY.ZZ` tags, every line generated fresh.
- **Ask on a bad target.** If **any** element of the selector list doesn't resolve to a real roadmap
  phase/version, name that element and ask — never silently drop it and ship the rest.
- **The plan is roadmap-ordered, always.** A selector list is a *set* of versions, not a running order.
  Sort it, de-duplicate it, and surface both the reordering and any dependency gaps at confirmation
  time. Honoring a user-supplied order over roadmap order would break the reconcile premise.
