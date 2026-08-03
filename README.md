# AgentArena Sandbox

A workspace for **instrumenting LLM-driven code generation**. The deliverable here is not an
application — it is the *process* that builds one, made observable.

The repo holds two things: a complete specification for a non-trivial application, and a set of SDLC
skills that generate that application from the spec. Running the skills produces a working codebase;
the point of this project is to **track that run as it happens** and surface it as a real-time
dashboard of generation statistics.

The application is therefore a **test fixture, not the product** — deliberately regenerable, and
deliberately absent from the working tree between runs.

## What's here

```
spec/              the specification the skills build from
  game_specification.md    product vision, MVP scope, phased plan
  architecture.md          module layout, seams, wire contracts, identity model
  roadmap.md               5 versions × 15 phases, each with Goal/Tasks/DoD/Tests
  web_ui_specification.md  the Web UI's behavior
  ui_prototype.html        its visual design source

.claude/skills/    the ten SDLC skills that generate the code
  generate-issues · upload-issues · execute-issues · execute-issues-file
  reconcile-issues · review-and-fix-issues · harden-findings · release-version
  reset-generated                   ← clears a run's output, from the run's own log
  ship-phase · ship-solution        ← the two orchestrators
```

Plus `CLAUDE.md` (conventions and current state), `.env.example`, and this file.

## What's not here

`server/`, `agent/`, `games/`, `web/`, `tests/`, `profiles/`, `scripts/`, `pyproject.toml`, `VERSION`,
`RELEASE.txt` — all generated output, cleared ahead of a fresh instrumented run. The last complete
build reached v05.03.00 (226 tests passing, `mypy --strict` clean) and remains in git history on
`main`.

`spec/implementation/` is also empty. The skills write their issues files, execution reports, and code
reviews there as they run.

## The application the skills build

Agent Arena: a real-time, LLM-agent Tic-Tac-Toe theater. Anthropic Haiku-powered agents play each
other — or a human — over WebSockets, watchable live in a browser as a **Player** (claims a seat,
plays and chats) or an **Observer** (no seat, watches).

Three cooperating processes over an event-driven WebSocket protocol: a FastAPI **game server** that is
the sole authority over state, a standalone **agent CLI** that is a pure external client, and a vanilla
HTML/CSS/JS **web UI** that only renders server events. Two seams keep it pluggable — `GameInterface`
(how a game plugs in) and `LLMClient` (how an agent reaches a model vendor).

Full detail in [spec/game_specification.md](spec/game_specification.md) and
[spec/architecture.md](spec/architecture.md).

## Regenerating the application

Two orchestrators drive the full pipeline. They are not meant to be mixed within one version.

**`/ship-phase <selector>[,<selector>…] [--no-harden]`** — GitHub-driven. Takes one selector or a
comma-separated list; missing prerequisite versions are filled in and already-released ones skipped.
Per version:
`generate-issues` → `upload-issues` → `execute-issues` → `review-and-fix-issues` →
`release-version vXX.YY.00`, then a hardening sweep at the phase boundary (default; `--no-harden` to
skip) and a chat report. Requires an authenticated `gh`.

**`/ship-solution [<selector>[,<selector>…]] [--no-harden]`** — offline, file-driven. Same selector
list, dependency fill and ordering as `/ship-phase`, but it reconciles *pre-existing* issues files
instead of generating them, skips GitHub entirely, and writes one timed statistics report at the end.
Default scope is the whole solution.

> **`/ship-solution` cannot run in the current state.** It executes from `spec/implementation/
> vXX.YY-issues.md` files and cannot generate one, so with none present it stops at Step 0.4 naming the
> versions it would need. Use `/ship-phase`, which generates them as its step 1, or author the files
> first.

> **A version whose release tag exists is skipped** by both orchestrators. The repo currently has no
> tags at all — the 63 inherited from an earlier multi-build repo were deleted, and `origin` has never
> had any — so a run covers everything. Re-adding a tag by hand removes that version from the plan.

Individual skills can also be invoked directly to build without releasing.

## Setup

No dependencies to install until code exists — `pyproject.toml` is itself generated. After a run:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

A model API key is needed only to run a **live agent**, never to generate or test. Copy
[.env.example](.env.example) to `./.env` (gitignored) and fill it in:

```
ANTHROPIC_API_KEY=sk-...
```

The key is read only by the agent process. It is never sent to or logged by the server or the UI, and
the test suite makes **zero paid API calls** — the `LLMClient` seam is always mocked.

## Status

The tracking instrumentation and the dashboard are **not built yet**. Today the skills report only
after the fact: `/ship-phase` reports once per phase to chat, `/ship-solution` stamps a timestamp per
version and writes a single report at the end. Neither emits anything consumable during a run.

The design for changing that lives in `codegen/`:

- [ship-phase-tracking-vision.md](codegen/ship-phase-tracking-vision.md) — the problem, the event
  model, where the instrumentation points are in each skill, and what the dashboard renders.
- [architecture.md](codegen/architecture.md) — the contracts: event schema, log format and its
  concurrency rules, the emitter's never-raise guarantee, redaction, and the test strategy.
- [implementation-plan.md](codegen/implementation-plan.md) — 22 `TRK-###` tasks in 7 steps, each with
  implementation detail and acceptance criteria.
- [dashboard-specification.md](codegen/dashboard-specification.md) — how the UI is built: tokens,
  components, DOM, rendering, interaction, accessibility.
- [dashboard/prototype.html](codegen/dashboard/prototype.html) — a self-contained working prototype
  of the dashboard, with mock data shaped to the event schema.
