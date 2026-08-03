# Ship-Solution Execution Report — 2026-07-21

**Branch:** `Anthropic-Opus4.8-Sonet5-dev` · **Executed by:** Claude Sonnet 5, via `/ship-solution`
**Mode:** commit-only, no push, no GitHub (standing constraints for this run) · every line generated
fresh — nothing read, checked out, or copied from any sibling branch.

## Total

- **Wall-clock:** 1h 46m 55s (all 15 versions, all 5 phases, end to end)
- **Phases:** 5 · **Versions:** 15 · **Issues executed:** 37 · **Commits:** 105
- **Releases:** `opus-sonnet-v01.01.00` → `opus-sonnet-v05.03.00` (all 15, one per version; see the by-version table)
- **Findings:** fix-now fixed **6** · hardened HIGH/MEDIUM via a phase-boundary sweep **0** (see Notes) · LOW deferred **8** (2 held beyond the MVP; see Notes) · held **0**
- **Reconcile:** issues corrected **2** · moot **2** · untouched **33** (of 37)
- **Suite:** 0 → **226** tests passing · `mypy --strict` clean (19 source files) throughout · zero paid model calls anywhere (LLM always mocked; enforced by an autouse guard since v05.02)

## By phase

| Phase | Versions | Duration | Issues | Commits | Reconciled (corr/moot) | Fix-now | Hardened | Release tags | HARDEN patch |
|-------|----------|----------|--------|---------|------------------------|---------|----------|--------------|--------------|
| v01 — Game Core & Server Foundation | 4 | 34m 50s | 15 | 31 | 0/0 | 1 | 0 | v01.01.00 → v01.04.00 | none (no-op sweep) |
| v02 — Agent Client (Haiku) | 3 | 19m 52s | 9 | 22 | 0/0 | 2 | 0 | v02.01.00 → v02.03.00 | none (no-op sweep) |
| v03 — Web UI (Player & Observer) | 3 | 22m 37s | 7 | 22 | 0/2 | 1 | 0 | v03.01.00 → v03.03.00 | none (no-op sweep) |
| v04 — Agent-vs-Agent Orchestration | 2 | 8m 19s | 2 | 10 | 0/0 | 0 | 0 | v04.01.00 → v04.02.00 | none (no-op sweep) |
| v05 — Hardening & Polish | 3 | 17m 41s | 4 | 20 | 2/0 | 2 | 0 | v05.01.00 → v05.03.00 | none (no-op sweep) |

Commit counts are `git rev-list --count` between consecutive release tags (includes every reconcile,
issue-implementation, execution-report, code-review, and release commit) — they sum to exactly **105**,
the branch's true total from the first `/ship-solution` commit (`313f13e`, exclusive) through the
final `v05.03.00` release.

## By version

| Version | Duration | Issues | Commits | Tests (before→after) | Reconcile (corr/moot/untouched) | Review (fix-now/deferred) | Release tag |
|---------|----------|--------|---------|----------------------|----------------------------------|----------------------------|--------------|
| v01.01 | 5m 42s | 3 | 7 | 0 → 36 (scaffolding: repo skeleton, `GameInterface`, TicTacToe) | 0/0/3 | 0/1 | opus-sonnet-v01.01.00 |
| v01.02 | 9m 26s | 4 | 8 | 36 → 62 | 0/0/4 | 1/1 | opus-sonnet-v01.02.00 |
| v01.03 | 6m 15s | 4 | 8 | 62 → 81 | 0/0/4 | 0/1 | opus-sonnet-v01.03.00 |
| v01.04 | 12m 30s | 4 | 8 | 81 → 115 | 0/0/4 | 0/1 | opus-sonnet-v01.04.00 |
| v02.01 | 5m 34s | 3 | 8 | 115 → 135 | 0/0/3 | 0/0 | opus-sonnet-v02.01.00 |
| v02.02 | 5m 54s | 3 | 7 | 135 → 162 | 0/0/3 | 2/0 | opus-sonnet-v02.02.00 |
| v02.03 | 8m 05s | 3 | 7 | 162 → 176 | 0/0/3 | 0/2 | opus-sonnet-v02.03.00 |
| v03.01 | 6m 43s | 3 | 7 | 176 → 186 | 0/0/3 | 0/0 | opus-sonnet-v03.01.00 |
| v03.02 | 8m 08s | 2 | 6 | 186 → 193 | 0/0/2 | 0/1 | opus-sonnet-v03.02.00 |
| v03.03 | 7m 46s | 2 | 9 | 193 → 203 | 0/2/0 | 1/1 | opus-sonnet-v03.03.00 |
| v04.01 | 3m 18s | 1 | 5 | 203 → 206 | 0/0/1 | 0/0 | opus-sonnet-v04.01.00 |
| v04.02 | 4m 13s | 1 | 5 | 206 → 213 | 0/0/1 | 0/0 | opus-sonnet-v04.02.00 |
| v05.01 | 7m 29s | 1 | 7 | 213 → 218 | 1/0/0 | 1/0 | opus-sonnet-v05.01.00 |
| v05.02 | 5m 30s | 2 | 6 | 218 → 220 | 0/0/2 | 0/0 | opus-sonnet-v05.02.00 |
| v05.03 | 4m 56s | 1 | 7 | 220 → 226 | 1/0/0 | 1/0 | opus-sonnet-v05.03.00 |

(Commits: `git rev-list --count` between consecutive release tags, verified against the branch's
true total of 105.)

*(v01.01's tests-before figure is a true `0` — the very first commit of this run; `pytest`/`mypy`
tooling was scaffolded incrementally within that issue itself, so a couple of intermediate,
not-independently-meaningful counts were observed en route to 36 and are folded into the "36" figure
above rather than reported as their own column.)*

## Timings

- **Fastest version:** v04.01 (3m 18s) — a single small, self-contained persona-data issue, no findings.
- **Slowest version:** v01.04 (12m 30s) — the v01 release gate: implementing the full WS move-authority
  flow plus finding and fixing a real concurrency bug (a client-drop surfacing as task cancellation
  rather than `WebSocketDisconnect`, leaking a seat) during its own execution.
- **Average per version:** 6m 46s (15 versions).
- **Per-phase totals:** v01 34m 50s · v02 19m 52s · v03 22m 37s · v04 8m 19s · v05 17m 41s.

## Notes

- **Every HIGH/MEDIUM finding was fixed at its own version's review step — no phase ever needed a
  HARDEN patch.** All 5 end-of-phase HARDEN sweeps were genuine no-ops (verified by scanning every
  phase's `*-code-review.md` files for unresolved 🔴/🟠 markers before moving on): v01 (0 found), v02
  (0 found), v03 (v03.03's one MEDIUM was fixed in-flow, not deferred), v04 (0 found), v05 (v05.01's
  MEDIUM and v05.03's HIGH were both fixed in-flow). No `opus-sonnet-vXX.YY.01` patch tag exists
  anywhere on this branch.
- **Two LOW findings remain deferred beyond the MVP**, correctly held there since HARDEN sweeps
  (by design) only ever touch HIGH/MEDIUM: `v01.04-code-review.md` #1 (redundant move-log
  reconstruction per `submit_move` — a perf item, harmless at MVP's ≤9-move scale) and
  `v03.02-code-review.md` #1 (the opponent card shows a generic "Player X/O" / "Haiku · Agent" label
  instead of the real persona name — needs a protocol addition the wire payloads don't carry, out of
  MVP scope). Both were explicitly re-homed to "before the v05 release gate" during v05.01's review,
  but the pre-generated `v05.01`/`v05.02`/`v05.03` issues files never actually included them as
  in-scope work — flagged there rather than silently pulled in as scope creep on an unrelated issue,
  and flagged again here rather than silently dropped.
- **Reconciliation caught real, not cosmetic, drift more than once** — not just namespace renames.
  Notable corrections: (1) v03.03 — a stale "v01.04 #3" citation claiming the server already refused
  an observer's `chat`; it didn't, and the real gap was closed as a MEDIUM fix in that version's own
  review. (2) v04.01/v05.02 — the pre-generated files assumed the aggressive persona was named
  "Blaze"; the real, test-pinned shipped name is `Ironclaw`. (3) v05.01 — the file cited a
  `v02.03.01` HARDEN patch and a `test_ws_resilience.py` file that don't exist on this branch; the
  real seat-release/shield behavior landed as core v01.04 scope, and — more importantly — the
  malformed-JSON DoD line the file claimed was already shipped had **never actually been
  implemented**, verified empirically (a raw non-JSON WS frame crashed the connection) before being
  fixed as part of that version's own issue. (4) v05.03 — the install-extra name `[test]` doesn't
  exist; the real one is `[dev]`.
- **Two review findings were severity HIGH** despite this being a "hardening" run late in the
  roadmap: v05.03's missing `uvicorn` dependency (the README's own first command would have failed on
  a genuinely clean install) was caught by checking the dependency manifest against the documented
  command rather than trusting an already-populated `.venv`.
- **Nothing stopped early; nothing was held.** All 15 versions, all 5 phases, and this final report
  completed in one continuous run. The scratch timing file
  (`spec/implementation/.ship-solution-progress.md`, gitignored) is left in place per its own header
  now that this report has rolled its content in — it is never committed.
