# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state — read this first

This is **`ichMaster/agent-arena-sandbox`**, a standalone, independently developed repository. It has a
single remote (`origin`) and no siblings. It was seeded from a branch of an earlier multi-model bake-off
repo, but that link is severed — there is no `upstream`, and nothing here should be pushed anywhere else.

`main` holds a **complete, working implementation** of Agent Arena at **v05.03.00** (MVP complete):
`server/`, `agent/`, `games/`, `web/`, `tests/`, `profiles/`, `scripts/`, plus `pyproject.toml`,
`VERSION`, and `RELEASE.txt`. Baseline on a clean checkout: **226 tests pass, `mypy --strict` clean.**

The durable assets — the things worth protecting — are **not** the application code:

- `spec/game_specification.md` — product vision + MVP scope + phased plan (the source of intent).
- `spec/architecture.md` — technical design (module layout, seams, wire contracts, identity model).
- `spec/roadmap.md` — the 5-version / 15-phase build plan (`vXX.YY`, each with Goal/Tasks/DoD/Tests).
- `spec/web_ui_specification.md` + `spec/ui_prototype.html` — the Web UI's behavior and visual design.
- `spec/implementation/vXX.YY-issues.md` — per-version issue breakdowns for all 15 versions
  (v01.01 → v05.03), with `ARENA-OPUS-###` ids. Plus each version's `-execution-report.md` and
  `-code-review.md`, and `ship-solution-report.md` from the run that produced the current `main`.
- `.claude/skills/*` — ten SDLC skills that generate the repo (below).

## What this project is actually for

**The application is the test fixture, not the product.** The goal is to make the SDLC skills in
`.claude/skills/` *observable*: instrument them so the process of code generation is tracked as it
happens, and surface that as a **real-time dashboard of code-generation statistics**.

Two work streams follow from that:

1. **Instrument the skills** — `.claude/skills/*` currently report after the fact (`ship-solution`
   stamps `date +%s` per version and writes one report at the end; `ship-phase` reports per phase to
   chat). Tracking needs to be emitted *during* the run, not reconstructed afterwards.
2. **Build the dashboard** — a live view of generation statistics. **Not built yet**; nothing in
   `web/` serves this today (`web/` is the game's UI). Design it deliberately rather than assuming it
   exists.

Consequently: **the application code is regenerable output.** The intended cycle is to delete it and
regenerate from `spec/` + the issues files via the skills, using each run as a subject for tracking.
Treat `server/`, `agent/`, `games/`, `web/`, `tests/` as reproducible; treat `spec/` and
`.claude/skills/` as the real source.

> Before any regeneration run, check the **stale tags** caveat under *Versioning* — it will silently
> skip every version otherwise.

## Two build workflows — pick one deliberately

Both live in `.claude/skills/`; they are not meant to be mixed within one version.

**A. File-driven, offline (uses the issues files already in the repo):**
`reconcile-issues vXX.YY` (correct the pre-generated issues file against the real code, in place, with
a dated `⟳ Reconciled` mark — no code written) → `execute-issues-file vXX.YY` (implement straight from
the file: implement → validate → commit → push per issue, dependency-ordered, **no GitHub**) →
`review-and-fix-issues vXX.YY` → `release-version vXX.YY.00`. Orchestrated end-to-end (all versions,
one final timed statistics report) by **`/ship-solution`**. This is the workflow that produced the
current `main`, and the natural default here.

**B. GitHub-driven:**
`generate-issues` → `upload-issues` → `execute-issues` (implements from real GitHub issues, closing
them as it goes) → `review-and-fix-issues` → `release-version`. Orchestrated per phase/version, with
per-phase chat reports and an opt-in end-of-phase hardening sweep, by **`/ship-phase`**.

> **Before using workflow B:** this repo has **no GitHub issues at all** — the `ARENA-OPUS-###` issues
> that the issues files reference lived in the old bake-off repo and are not reachable. `upload-issues`
> would create them fresh here. Confirm that's intended before running it.

Rules that hold across all skills, either workflow:
- **One issue = one commit.** Never mix work from multiple issue IDs; never work on more than one at a time.
- **Respect the Dependency Tree** in each issues file — don't start an issue whose dependencies aren't committed.
- **Tests ship with the feature**, and **the LLM is always mocked** in tests — never make a paid model call in tests/validation/CI.
- **A seam change** (WebSocket payload schema, `GameInterface`, `LLMClient`, seat-by-token identity) **updates `spec/architecture.md` + its contract test in the same commit.**
- If an issue's scope is ambiguous, or an issues file disagrees with the real code/specs, ask or reconcile rather than guessing.
- `release-version`/`harden-findings` never bump the version or release without it being an explicit, confirmed step.

## Target architecture (from `spec/game_specification.md` + `spec/architecture.md`)

Three cooperating processes over an **event-driven WebSocket** protocol (no REST polling):

- **Game Server** (Python + FastAPI) — central authority: owns authoritative state (SQLite via a
  `Repository`), validates every move, pushes JSON events (`joined`, `state_update`, `chat_message`,
  `game_over`, `error`) to clients. Holds a `ConnectionManager` mapping `match_id` → connected sockets.
  "Your turn" is a *derived* condition (`current_turn == your symbol`), not a separate event; live game
  state is **reconstructed by replaying the move log**, never stored as mutable fields.
- **Agent Client** (Python CLI) — standalone LLM-driven process (Anthropic Haiku). The server pushes
  full turn state; the agent replies with **one structured `{move, comment}`** per turn (no pull-tools
  round-trip), with a bounded retry-then-random-legal-fallback if the model hallucinates a move.
  Imports nothing from `server/` — a pure external client over HTTP/WS.
- **Web UI** — vanilla HTML/CSS/JS served at `/ui`, no build step; a stateless renderer of server
  events, with **Player** and **Observer** roles decided server-side (never asserted by the client).

Two seams are the whole point of the design — keep them clean:

- **`GameInterface`** is the only way a game plugs in: `get_state()`, `get_valid_moves()`,
  `apply_move(move)`, `is_game_over()`. `apply_move` is the sole legality authority and never raises on
  bad input. Tic-Tac-Toe is the first implementation; future games (Checkers, Connect 4, Chess) are
  added as new modules, not by generalizing Tic-Tac-Toe. The move payload is opaque to transport.
- **`LLMClient`** is the only way an agent talks to a model vendor — the abstraction that lets the
  vendor be swapped by config (`create_llm_client`), keeping agent logic free of any specific SDK.

Non-negotiables: the **server is the ultimate authority** (LLM output is untrusted; re-validate every
move server-side); **seats are keyed by per-connection token, never display name** (`UNIQUE(match_id,
symbol)`; observers never hold a seat, permanently); **secrets (model API keys) live only in the
agent's `.env`** and are never sent to or logged by the server/UI; WS cleanup runs in a `finally` block
(a client-initiated drop can surface as async cancellation, not `WebSocketDisconnect`); an **Agent
Designer** (`AgentProfile` YAML — name/system_prompt/model_type/temperature/memory_limit) packages a
persona/model/memory config into a runnable agent.

## Tech & style

- Python + FastAPI + WebSockets for the server; Python for the agent CLI; vanilla HTML/CSS/JS (no build
  step) for the Web UI, served at `/ui` with `Cache-Control: no-store`.
- Persistence: **SQLite** via SQLAlchemy (async + `aiosqlite`) behind a `Repository`; four tables
  (`matches`, `participants`, `moves`, `chat_messages`); live state reconstructed from the move log
  (no serialize seam on `GameInterface`).
- **Use strict typing in Python** throughout `games/`, `server/`, `agent/`.

## Commands

- Setup: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- Tests: `pytest` (repo-wide) or a single file/test, e.g. `pytest tests/test_tictactoe.py` or
  `pytest tests/test_server.py -k <expr>`.
- Typing: `mypy games server agent` (strict via `[tool.mypy] strict = true` in `pyproject.toml` — no
  separate `mypy.ini`).
- Server: `uvicorn server.main:app`; UI at `http://127.0.0.1:8000/ui`.
- **Packaging gotcha:** if `pyproject.toml` declares no `[build-system]`/`[tool.setuptools]` package
  list, `pip install -e ".[dev]"` fails with *"Multiple top-level packages discovered in a
  flat-layout"* — setuptools auto-discovers `web/`, `profiles/`, `spec/`, etc. as false package
  candidates alongside `games/server/agent`. Pin `[tool.setuptools] packages = ["games", "server",
  "agent"]` explicitly, and remember `uvicorn` must be a declared runtime dependency (not just
  installed by hand into `.venv/`) if the README tells users to run it after `pip install`.
- SQLite `*.db` files and caches are gitignored; the DB path is config-driven (`./arena.db`).

## Versioning

Strict `vXX.YY.ZZ` tied to the roadmap: `XX` = roadmap version (v01–v05), `YY` = version within it,
`ZZ` = bugfix/patch. Releases are cut per **version** (`vXX.YY.00`), after that version's issues all
land and its tests are green — **never bump the version without explicit user confirmation.**

> **⚠️ Stale tags block regeneration.** This repo carries **63 local tags inherited from the old
> bake-off repo** — `opus-vXX.YY.ZZ`, `opus-opus-vXX.YY.ZZ`, `opus-sonnet-vXX.YY.ZZ`, and plain
> `vXX.YY.ZZ` — spanning several *different* builds. **None are pushed to `origin`.** Both `/ship-phase`
> and `/ship-solution` skip any version whose release tag already exists, so a regeneration run would
> skip essentially everything. Decide with the user whether to delete these local tags and what tag
> prefix this repo uses going forward, **before** the first `release-version` call.

## Retired conventions — do not reintroduce

- **`<vendor><model>-dev` branch names** (e.g. `Anthropic-Opus4.8-Sonet5-dev`). That scheme existed to
  keep seven parallel model-built implementations apart in a shared repo. Neither the parallel builds
  nor the shared repo applies here. Name branches for the **work**, not the model.
- **The "never copy from sibling branches" rule.** There are no sibling branches and no remote that
  hosts them.
- **The `.agents/` skillset** (a simpler, separate `generate-issues`/`upload-issues`/`execute-issues`
  set) has been deleted. Use `.claude/skills/*`.
- The `opus-` tag prefix and `ARENA-OPUS-###` issue namespace are **legacy** from the bake-off, still
  hardcoded throughout `.claude/skills/*` and the issues files. They no longer prevent any collision.
  Changing them is a deliberate, repo-wide decision — ask rather than doing it piecemeal.
