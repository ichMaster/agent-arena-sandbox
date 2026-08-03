---
name: harden-findings
description: Sweep the code-review reports in spec/implementation/ for still-unfixed HIGH/MEDIUM findings, fix each with a regression test, update the reports in place, and (opt-in) ship the result as a ZZ patch release. Runs standalone, or invoked automatically at each phase boundary by /ship-phase and /ship-solution.
---

# Skill: Harden Findings

Close out the serious code-review findings that were **deferred** ("real, but not recommended for
immediate fix"): sweep the review reports, fix every remaining **🔴 HIGH / 🟠 MEDIUM** finding with a
regression test, record the results in the same reports, and optionally cut a `ZZ` patch release so
the hardening actually ships.

Consent is carried by the **invocation of whatever ran this skill**. Called directly, invoking it is
the consent. Called from an orchestrator, the orchestrator's own invocation is: both `/ship-phase` and
`/ship-solution` sweep at every phase boundary by default, and `/ship-phase --no-harden` is the opt-out.

## Usage

```
/harden-findings [scope] [--release]
```

- `scope` — optional filter: a phase (`v02` → reports whose findings belong to that phase's code),
  a version (`v02.02`), or omitted → **all** `spec/implementation/*code-review*.md` reports.
- `--release` — after fixes land, cut the `ZZ` patch release automatically (e.g. `v02.03.00` →
  `v02.03.01`, tag `v02.03.01`). Without it, finish by **recommending** `/release-version` —
  never bump a version without explicit confirmation.

Examples: `/harden-findings` · `/harden-findings v01` · `/harden-findings v02 --release`

## Instructions

### Step 0: Baseline and the finding list

1. Confirm the working dev branch and a clean tree; establish a **green baseline** (`pytest` + strict
   `mypy`). Never harden on a red suite — fix a clear flake first (own commit) or surface it.
2. **Collect** the code-review reports: `spec/implementation/*code-review*.md`, filtered by `scope`
   if given.
3. **Select** every finding with severity **🔴 HIGH or 🟠 MEDIUM** whose **Status is not FIXED**
   (pending/`⏳ deferred`) — **regardless of its `DEFER → <home>` recommendation**. Ignore 🟡 LOW
   (it stays deferred to its documented home). Order the queue **HIGH before MEDIUM**, then by report.
4. Show the queue (finding, severity, source report, proposed fix) — then proceed. If the queue is
   empty, say so and stop.

### Step 1: Fix each finding, gated

For each finding in order:

1. **Implement the fix** following `CLAUDE.md` + `spec/architecture.md`. Keep it minimal and focused —
   one finding, one change.
2. **Add a regression test that would have caught the bug** (a concurrency finding gets a concurrent
   test, a protocol finding gets a wire-level test, …). The **LLM is mocked by default**; live calls are opt-in.
3. **Validate:** `pytest` (green, deterministic) + strict `mypy`. Only commit code that passes.
4. **Commit** one focused change referencing the finding (`fix(<area>): … (code review #N)`), with the
   `Co-Authored-By` trailer. A **seam change** (`GameInterface`/`LLMClient`/WS protocol/seat-by-token)
   carries its `spec/architecture.md` update **and** contract test in the same commit.
5. **Update the source report in place:** flip the finding's **Status** to `✅ FIXED — <commit>`,
   extend its **"Fixes applied"** section (change, test, verification), and add an **"Architecture
   impact"** note if the fix changed documented behavior/contracts — the next `/generate-issues`
   reconciliation reads exactly these notes. If the finding was homed to a *later* roadmap item
   (e.g. v05.01 resilience), note there that this scope is **already addressed** so it isn't re-done.

**Escape hatch:** if a fix genuinely can't land safely now (needs a design decision, or would balloon
into a large change), **do not force a broken or half-baked fix** — leave the finding deferred, record
*why* it's held in the report, and surface it to the user. Prefer fixing; hold only when a clean
landing isn't possible.

### Step 2: Final validation + optional patch release

1. Re-run the **full suite** once after the sweep — green and deterministic — plus strict `mypy`.
2. Commit the report updates (a `docs:` commit) and push everything.
3. **Release:** if `--release` was passed (or the user confirms when asked), invoke `release-version`
   for the `ZZ` patch bump on the affected released version (the roadmap's "post-release fix", e.g.
   `01.04.01`, tag `v01.04.01`). Otherwise just recommend the command and stop — releasing stays
   explicit.

### Step 2.5: Emit tracking events

`--emitter skill:harden-findings --scope phase=..,version=..`: on entry → `harden.start`; each landed
fix → `harden.finding.fixed` (`finding`, `sha`, **plus `pytest` with the full-suite counts after the
fix** — a hardening fix changes the suite, and `tests_passing` otherwise stays frozen at whatever the
last issue reported); each escape-hatch hold → `harden.finding.held` (`finding`, `reason`). When an
orchestrator skips the sweep it emits `harden.skipped` itself.

Which sweep closed a finding is the point: if hardening keeps fixing HIGH findings that review
deferred, the fix-now/defer classification is miscalibrated — a fact about the skills.

### Step 3: Report to chat

Summarize: findings fixed (severity, commit each), findings **held** via the escape hatch (with why),
LOW findings untouched (with homes), final suite/typing status, and the patch tag (or the recommended
`/release-version` command).

## Important Rules

- **Only HIGH and MEDIUM.** LOW findings are out of scope — they stay deferred to their documented homes.
- **Invocation = consent**, at whatever level the invocation happened. Direct call: the call is the
  consent. From an orchestrator: the orchestrator's invocation is, and both `/ship-phase` and
  `/ship-solution` sweep at every phase boundary by default. What is never implicit is the **release** —
  a `ZZ` patch still requires `--release` or an explicit confirmation (see below).
- **One finding = one focused commit**, each with a regression test; the LLM is mocked by default — no paid
  API call in any test.
- **Green before, green after.** Start from a green baseline; only commit passing code; end with a full
  deterministic green run.
- **Update the same review docs in place** — status + "Fixes applied" + "Architecture impact"; no new
  parallel documents.
- **Contracts stay recorded.** A seam change updates `spec/architecture.md` + its contract test in the
  same commit, so later reconciliation is accurate.
- **Release only with consent** (`--release` or an explicit confirmation) — and only as a `ZZ` patch on
  an already-released version.
- **Stop on failure.** A red `pytest`/`mypy` on any fix halts the sweep — report what landed and what
  remains; never paper over it.
- **Generate every line fresh.** Never `git checkout`/`cherry-pick`/merge code out of git history or any other ref.
