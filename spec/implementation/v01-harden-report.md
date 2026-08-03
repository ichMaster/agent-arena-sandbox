# v01 — HARDEN sweep

**Date:** 2026-08-03
**Scope:** every code-review document produced by phase **v01** (v01.01 → v01.04).
**Baseline:** 310 passed · `mypy games server agent` clean · tracker suite 293.

## What the sweep found

| Version | 🔴 HIGH | 🟠 MEDIUM | 🟡 LOW | Still unfixed after the sweep |
|---|---|---|---|---|
| v01.01 | 0 | 1 | 3 | 2 LOW (documented homes) |
| v01.02 | 0 | 2 | 3 | 1 LOW (out of MVP scope) |
| v01.03 | 0 | 2 | 3 | 1 LOW (CORS, documented) |
| v01.04 | 0 | 3 | 3 | **1 MEDIUM (held)** + 3 LOW |
| **total** | **0** | **8** | **12** | 1 MEDIUM + 7 LOW |

**No 🔴 HIGH finding was raised anywhere in v01.** Seven of the eight MEDIUMs were fixed in their own
phase's review pass; the eighth is held below.

## Record corrections

Five findings were still reading `⏳ deferred` although a later phase had already resolved them. The
sweep decides what to fix by reading these documents, so a stale status inflates the backlog — and the
opposite error, a finding reading *fixed* when it is not, would be worse. Corrected in `0ea8342`:

| Finding | Deferred to | Actually resolved by | Commit |
|---|---|---|---|
| v01.02 #4 — Repository commits per method | v01.04 | ARENA-014 (callers own the transaction) | `51b605b` |
| v01.02 #5 — `session_scope()` unused | v01.03 | ARENA-011 (adopted, not deleted) | `b007785` |
| v01.03 #2 — per-request transaction is a fiction | v01.04 | ARENA-014 | `51b605b` |
| v01.03 #3 — observer vs. full match indistinguishable | v01.04 | ARENA-015 (`seat_available`) | `bd7646a` |
| v01.03 #4 — `validate_token` unused | v01.04 | ARENA-015 (WS connect) | `bd7646a` |

That the roadmap's own sequencing closed all five — each in the phase the review had named as its
home — is the useful signal here: the deferrals were real scheduling, not a way of avoiding work.

## Held — not fixed, with the reason

### 🟠 MEDIUM — v01.04 #2: a momentary drop releases the seat immediately

**Escape hatch invoked.** This is the sweep's one genuine HIGH/MEDIUM candidate, and it is **held**
rather than forced.

Cleanup releases a player's seat the instant their socket goes away. Correct for someone who leaves,
wrong for someone whose wifi hiccups: their seat becomes available at once, and another client can
take it and continue their game.

The fix is a **grace period** — hold the seat for N seconds, release on expiry, and let `joined` say
"your seat is being held". That needs a timer mechanism, a policy decision about N, and a protocol
addition. It is a design, not a patch, and roadmap **v05.01 — Resilience & reconnection** exists for
precisely this work.

Forcing it here would mean inventing a reconnection policy three phases before the phase that owns
it, without the integration suite (v05.02) that would show whether it holds. The finding stays open
with its home named.

**One consequence is already visible and is worth recording**, because it will look like a defect to
whoever reads the tests: `test_a_move_into_a_finished_match_is_refused` asserts only that the move is
refused and writes nothing, not *which* refusal comes back. A returning player currently gets "you
have no seat" rather than "this game is over", because the seat was released while they were away.
Once v05.01 lands, that test can pin the better message.

## Not swept (🟡 LOW, by design)

`games/` has no `py.typed` (→ v05.03) · `WINNING_LINES`/`BOARD_SIZE` coupling and `game_type` ignored
(→ out of MVP scope, §14) · engine does not enforce turn order (→ owned by the server, §5.4) ·
permissive CORS (→ documented local-dev choice, §3) · `ConnectionManager` not cleared on shutdown
(→ v05.02) · no chat rate limit or observer bound (→ v05.01) · long-lived session identity map
(→ v05.01).

## Outcome

**No patch release.** Nothing was fixed by this sweep, so there is nothing to ship — `v01.04.00`
stands as the phase's release. A `ZZ` patch with an empty changelog would be noise.

The v01 phase closes with: 0 HIGH, 1 held MEDIUM with a named home, 7 LOW deferred to phases that
exist for them.
