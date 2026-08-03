# Tracking system — architecture

**Status:** design. Nothing here is implemented yet.
**Companion:** [ship-phase-tracking-vision.md](ship-phase-tracking-vision.md) is the *why* — the problem,
the event model, the dashboard's panels. This document is the *how*: contracts, formats, guarantees,
and the test strategy. Where the two disagree, this file wins on mechanics and the vision doc wins on
intent.

> **Not to be confused with [`spec/architecture.md`](../spec/architecture.md)**, which is the
> architecture of the *generated application*. This system observes that one and shares no code with it.

---

## 1. Components

Four pieces, one direction of dependency. Nothing downstream is required for the pipeline to run.

```
 skills ──emit──┐
                ├──►  events.jsonl  ──►  reducer  ──►  state.json  ──►  dashboard ──WS──► browser
 hooks  ──emit──┘      (append-only)      (pure)        (snapshot)
                                              ▲
 git ─────────────────────────────────────────┘  (reconciliation only, after the fact)
```

| Component | Path | Responsibility |
|---|---|---|
| **Emitter** | `codegen/tracker/emit.py` | The *only* writer. Appends one validated event. Never raises. |
| **Schema** | `codegen/tracker/schema.json` | The event contract, versioned. |
| **Reducer** | `codegen/tracker/reduce.py` | Pure `events → state`. No I/O beyond reading the log. |
| **Hooks** | `codegen/hooks/*.py` | Harness-invoked; translate tool calls into events. |
| **Dashboard** | `codegen/dashboard/server.py` | Tails the log, serves the UI, pushes over WS. |
| **Tests** | `codegen/tests/` | See §10. **Not** the app's `tests/`, which is deleted every run. |

**Dependency rule.** `tracker/` imports nothing. `hooks/` imports `tracker/`. `dashboard/` imports
`tracker/`. Nothing imports `server/`, `games/`, or `agent/` — those directories may not exist.

---

## 2. Event contract

### 2.1 Envelope

Every line in `events.jsonl` is one JSON object. Field order is not significant; **key set is**.

| Field | Type | Req | Notes |
|---|---|:--:|---|
| `v` | int | ✔ | Schema version. Currently `1`. See §11. |
| `ts` | string | ✔ | ISO-8601 UTC, millisecond precision, `Z`-suffixed. |
| `run_id` | string | ✔ | `run-YYYYMMDD-HHMMSS`, assigned at `run.start`. |
| `type` | string | ✔ | Dotted event type from §3. |
| `scope` | object | ✔ | `{phase?, version?, step?, issue?}` — the path through the tree. |
| `status` | string | — | `ok` \| `fail` \| `skip` \| `held` \| `running`. Absent on `*.start`. |
| `data` | object | — | Type-specific payload (§3). Absent means "no payload". |
| `emitter` | string | ✔ | `skill:<name>` or `hook:<name>`. Needed for the §10.4 reconciliation. |

```json
{"v":1,"ts":"2026-08-03T14:22:31.482Z","run_id":"run-20260803-142012",
 "type":"issue.validate.end","emitter":"skill:execute-issues",
 "scope":{"phase":"v01","version":"v01.01","step":"execute-issues","issue":"ARENA-003"},
 "status":"fail","data":{"attempt":1,"pytest":{"passed":41,"failed":1,"duration_s":6.1},"mypy":{"errors":0}}}
```

### 2.2 Ordering — `seq` is assigned on read, not on write

> **A `seq` written by the emitter cannot work**, which is why the envelope in §2.1 has no such field.
> Emitters are independent processes — a skill's Bash call, a hook, the orchestrator — with no shared
> counter and no lock, so no writer can know its own sequence number. (An earlier draft of the vision
> doc carried `seq` in the written envelope; it was corrected to match this.)

The resolution: **file line order is the sequence.** The reducer assigns `seq` as the 0-based line
ordinal while reading. Consumers may rely on `seq`; emitters must never write it. Ties in `ts` are
resolved by line order, which is exactly what `seq` was meant to provide.

### 2.3 Scope

`scope` is a path, not a label — every field present must name a real ancestor of the event.

| Event level | Required scope keys |
|---|---|
| `run.*` | *(none — may be `{}`)* |
| `phase.*` | `phase` |
| `version.*` | `phase`, `version` |
| `step.*`, `gate.*` | `phase`, `version`, `step` |
| `issue.*` | `phase`, `version`, `step`, `issue` |
| `finding.*`, `harden.*` | `phase`, `version` (+ `finding` id in `data`) |
| `release.*` | `phase`, `version` |

An event whose scope omits a required key is **malformed** and is quarantined by the reducer (§5.3),
not silently repaired.

---

## 3. Event catalogue

`data` columns list **required** keys; any event may carry extra keys, which consumers ignore.

| Type | status | `data` (required) |
|---|---|---|
| `run.start` | — | `command`, `plan` (ordered version ids), `baseline` `{tests,mypy_errors}`, `git` `{branch,head_sha,remote}` |
| `run.estimate` | — | `source` (`estimated`\|`counted`), `versions` `[{id,issues_low,issues_high,points_low,points_high,duration_s}]`, `total`, `rate_basis` |
| `run.end` | ok/fail | `versions_done`, `issues_done` |
| `run.aborted` | fail | `reason` |
| `phase.start` | — | — |
| `phase.end` | ok | `versions` |
| `version.start` | — | — |
| `version.end` | ok | `tag` |
| `version.skipped` | skip | `reason` (`already-released`) |
| `step.start` | — | — |
| `step.end` | ok/fail | — |
| `version.decomposed` | ok | `issues` (ids + `size`) — **the moment scope becomes known**, see §3.2 |
| `issue.uploaded` | ok | `issue`, `gh_number`, `url` |
| `issue.closed` | ok | `issue`, `gh_number` |
| `gate.blocked` | fail | `gate`, `reason` |
| `issue.start` | — | `size` (`S`/`M`/`L`), `area` |
| `issue.implement.end` | ok/fail | `files_changed` |
| `issue.validate.end` | ok/fail | `attempt`, `pytest` `{passed,failed,duration_s}`, `mypy` `{errors}` |
| `issue.commit` | ok | `sha`, `files` |
| `issue.failed` | fail | `attempt`, `reason` |
| `issue.reverted` | fail | `attempt` |
| `issue.end` | ok/fail/skip | `attempts` |
| `finding.raised` | — | `finding`, `severity` (`HIGH`/`MEDIUM`/`LOW`), `title` |
| `finding.classified` | — | `finding`, `disposition` (`fix-now`/`defer`), `home?` |
| `finding.fixed` | ok | `finding`, `sha` |
| `finding.deferred` | skip | `finding`, `home` |
| `harden.start` | — | — |
| `harden.skipped` | skip | `reason` (`--no-harden`) |
| `harden.finding.fixed` | ok | `finding`, `sha` |
| `harden.finding.held` | held | `finding`, `reason` |
| `release.tagged` | ok | `tag` |
| `release.pushed` | ok | `tag`, `remote` |

**Pairing rule.** Every `*.start` has exactly one matching `*.end` / `*.skipped` / `*.aborted` in the
same scope. An unmatched `*.start` means the run died mid-node (§9.2).

### 3.1 The estimate, and why it must stay independent

`run.estimate` is emitted once, immediately after the plan is confirmed and **before any version is
decomposed**. It gives the burn-down a total at t=0 and the ETA a value before the first version
finishes — otherwise both are blank for the first several minutes of a run.

`source` distinguishes the two orchestrators, and the difference is real:

- **`/ship-phase` → `estimated`.** Issues do not exist yet, so counts are inferred from each version's
  roadmap Tasks list. Carries genuine uncertainty; the burn-down draws the band.
- **`/ship-solution` → `counted`.** Every planned version already has an issues file (its Step 0.4
  guarantees it), so counts are read, not guessed. `issues_low == issues_high`, and the burn-down has
  **no scope band** — only the time axis is projected.

> **The estimate is never an input to `generate-issues`.** If it were, the decomposer would be told how
> many issues to produce and the comparison would measure nothing but its own suggestion. Estimate and
> actual are *expected* to diverge; keeping them independent is what makes the divergence informative.

**Estimate accuracy** is therefore a derived metric, not an event: at each `version.decomposed` the
reducer compares the real issue count and points against this event's figures, and records signed
error per version plus a run-level bias. A consistent one-directional bias is a finding about the
roadmap or the decomposer — the kind of thing this project exists to surface. It is never used to
correct the estimate mid-run, which would destroy the measurement.

### 3.2 Scope is discovered, not declared

The plan on `run.start` lists **versions**, not issues — because issue counts do not exist yet.
`generate-issues` decomposes one version at a time into 3–7 issues, so a version's issue count is
unknown until its `version.decomposed` event fires, partway through the run.

This is why `version.decomposed` is a first-class event rather than an implementation detail of
`step.end{generate-issues}`: it is the instant total scope changes, and every consumer that shows
progress — burn-down, ETA, "issues done / planned" — must distinguish **known** work from
**estimated** work. A consumer that treats the plan as a fixed issue total will be wrong for most of
the run and will not know it.

Estimating the unknown remainder: for each version not yet decomposed, use the observed mean issue
count so far; before there is one, use the roadmap's 3–7 band. Consumers must carry the low and high
separately (§6 `state.scope`) rather than collapsing to a midpoint.

---

## 4. The log

### 4.1 Layout

```
codegen/runs/<run-id>/events.jsonl     append-only; the source of truth
codegen/runs/<run-id>/state.json       reducer output; disposable, rebuildable
codegen/runs/current                   text file holding the active <run-id>
```

`codegen/runs/` and `codegen/var/` are gitignored. Everything else under `codegen/` is committed.

### 4.2 Append discipline — the concurrency contract

Independent processes append concurrently. The rules that make that safe:

1. Open with `O_WRONLY | O_APPEND | O_CREAT`. **Never** seek; never `r+`.
2. Serialize the event and write it in **exactly one `write()` call**, newline included. Never
   `write(json)` then `write("\n")` — that is two calls and interleaves.
3. **Budget each line to ≤ 4096 bytes.** If `data` would exceed it, truncate the payload (§4.3)
   rather than splitting the line.
4. Close promptly. Do not hold the fd across a long operation.

> **Measured, not assumed.** 12 concurrent processes × 300 lines each, single `write()` per line, on
> macOS/APFS: **0 corrupt lines at 230 B, 430 B, 930 B and 4030 B**. Note `getconf PIPE_BUF` is **512**
> on this platform — the usual "atomic below PIPE_BUF" folklore would have suggested a far tighter
> budget than reality requires. But this is a filesystem-specific observation, not a POSIX guarantee:
> keep the 4 KB budget, keep the single-write rule, and keep the reducer tolerant of a torn final line
> (§5.3) for the crash case, which no atomicity rule can prevent.

### 4.3 Payload truncation

Oversized string values are cut to 512 chars with a `"…"` suffix and the event gains
`data._truncated: true`. Never drop the event; a truncated event is far better than a missing one.

### 4.4 Retention

One directory per run, kept until deleted by hand. `runs/` is gitignored, so growth is a local-disk
concern only. A run worth keeping is promoted by copying it somewhere committed — deliberately, never
automatically.

---

## 5. Emitter

### 5.1 API

```python
def emit(type: str, *, scope: dict | None = None, status: str | None = None,
         data: dict | None = None, emitter: str) -> None:
    """Append one event. Never raises. Never blocks longer than one write()."""
```

CLI form, for hooks and any shell context:

```bash
python3 codegen/tracker/emit.py issue.validate.end \
  --scope version=v01.01,step=execute-issues,issue=ARENA-003 \
  --status fail --data '{"attempt":1}' --emitter skill:execute-issues
```

### 5.2 The never-raise guarantee

This is the load-bearing property. From vision-doc principle 2: *emission must never gate the
pipeline.* Concretely, `emit` catches **every** exception — disk full, missing directory, unwritable
path, malformed input, absent `runs/current` — and returns normally. On failure it appends one line to
`codegen/var/emit-errors.log` on a best-effort basis and gives up.

A tracker that can fail a build is worse than no tracker.

### 5.3 Reader tolerance

The reducer must survive what the writer cannot prevent:

- **A torn final line** (process killed mid-write) — skip it, count it, continue.
- **A malformed line** (bad JSON, missing required key, unknown `type`) — quarantine to
  `state.json.quarantine[]` with its line number, and continue.
- **An unknown `type`** — retain in quarantine rather than discard; a newer emitter may be writing
  events this reducer predates.

Quarantine counts are surfaced in the dashboard footer. Silent discarding is forbidden — an
observability system that loses data quietly is lying.

---

## 6. Reducer & derived state

```python
def reduce(lines: Iterable[str]) -> State:   # pure; no clock, no filesystem, no network
```

**Purity is the testability lever.** `reduce` takes lines and returns state — no `datetime.now()`, no
env reads. Elapsed time for *open* nodes is computed by the caller, which passes `now` in explicitly.
That is what makes golden-fixture tests (§10.2) possible at all.

`state.json` shape:

```json
{
  "run_id": "run-20260803-142012", "schema": 1, "status": "running",
  "command": "/ship-phase v01", "started": "…", "ended": null,
  "plan": ["v01.01","v01.02","v01.03","v01.04"],
  "tree": [ { "id":"v01.01", "kind":"version", "status":"ok", "start":"…", "end":"…",
              "children":[ {"id":"execute-issues","kind":"step", "…":"…"} ] } ],
  "metrics": { "issues_done": 15, "first_pass_rate": 0.80,
               "mean_issue_s": 302.9, "tests_passing": 156, "findings_open": 2 },
  "scope":   { "known": 17, "est_low": 20, "est_high": 24, "undecomposed": ["v01.04"] },
  "github":  { "created": 17, "closed": 15, "open": 2, "commits": 19,
               "branch": "codegen-tracking", "head_sha": "f069fb6" },
  "eta": { "low_s": 2280, "high_s": 3120, "basis": {"issues_sampled":15,"undecomposed_versions":1} },
  "quarantine": [], "counts": {"events": 412, "torn": 0, "malformed": 0}
}
```

**ETA carries its own basis.** The panel is contractually required to show sample size and how much
scope is undecomposed (vision §6.1), so the reducer emits those fields rather than leaving the UI to
invent confidence. `eta` is `null` until at least one `version.end` exists.

**`scope` is a range, never a scalar.** `known` counts issues from versions already decomposed;
`est_low`/`est_high` add the estimated remainder for versions that are not (§3.2). There is
deliberately no `issues_planned` field — a single number there would be a guess wearing the costume
of a fact, and every consumer would render it as certain.

**`github.commits`** counts every commit the run produced — `issue.commit`, `finding.fixed`,
`harden.finding.fixed`, and the release commits — not just issue commits.

---

## 7. Hook contract

Registered in `.claude/settings.json` — the single permitted file outside `codegen/` (vision §4.1) —
holding only a matcher and a command:

```json
{ "hooks": { "PostToolUse": [ { "matcher": "Bash",
    "hooks": [ { "type": "command", "command": "python3 codegen/hooks/on_tool_use.py" } ] } ] } }
```

Hook scripts receive the harness payload on **stdin** as JSON, and must:

- **Exit 0, always.** A non-zero hook exit can disrupt the session it is observing. Wrap everything.
- **Complete in < 50 ms.** They run on every tool call; a slow hook taxes the whole pipeline.
- **Never print to stdout.** Output may be interpreted by the harness. Diagnostics go to
  `codegen/var/`.
- **Redact before writing** (§8).

Hooks supply the deterministic floor: they observe that `pytest` ran and with what exit code, without
knowing which issue it belonged to. Attribution comes from `runs/current` plus the most recent
`issue.start` — a best-effort join, deliberately, since guessing wrong is better than recording
nothing.

---

## 8. Redaction — the one security requirement

Hooks see **every Bash command**. A command line can contain a model API key. The repo's standing rule
is that secrets live only in the agent's `.env` and are never logged; a naive tracker would break that
rule on day one and write the key to disk in plaintext.

Therefore, before any event is written:

1. **Never record raw command strings.** Record the tool name, argv[0], exit code and duration. If an
   argument sample is genuinely needed, record a hash, not the text.
2. **Redact by pattern** anything resembling a credential — `sk-…`, `ghp_…`, `AKIA…`,
   `*_API_KEY=*`, `Authorization: *` — replacing the value with `«redacted»`.
3. **Never read `.env`**, and never record the environment.
4. **Redaction is the emitter's job, not the caller's** — one implementation, tested (§10.3), so no
   call site can forget.

`codegen/runs/` is gitignored, so a leak would not reach the remote — but "it is only on local disk"
is not a security model.

---

## 9. Failure modes & guarantees

### 9.1 What is guaranteed

- A run that completes normally produces a log whose `*.start`/`*.end` pairs are balanced.
- No emitter failure can fail a pipeline step (§5.2).
- `state.json` is always rebuildable from `events.jsonl`; deleting it loses nothing.
- The log is append-only. Nothing rewrites history.

### 9.2 What is not, and how it surfaces

| Failure | Behaviour |
|---|---|
| Run killed mid-flight | Unmatched `*.start`. A `Stop` hook writes `run.aborted`; if even that is missed, the dashboard marks the run stale after no events for 10 min. |
| Skill forgets an emit | Gap is invisible in the log itself — caught by §10.4 reconciliation against hooks. |
| Two runs concurrently | **Unsupported.** `runs/current` is a single pointer. The second `run.start` should refuse when `current` names a run with no `run.end`. |
| Disk full | `emit` fails silently, pipeline continues, `state.counts` stop advancing. |
| Clock skew across emitters | `ts` may go backwards; ordering uses line order (§2.2), so this is cosmetic. |

---

## 10. Test strategy

Tests live in **`codegen/tests/`** and run with `pytest`. They must not touch the network, must not
call a model, and must not depend on `server/`, `games/`, or `agent/` existing.

### 10.1 Schema conformance

- Every event type in §3 has a valid example that validates against `schema.json`.
- For each type, an example **missing each required `data` key** is rejected.
- Scope requirements (§2.3) hold: an `issue.*` event without `version` fails validation.
- Round-trip: `emit` → read back → parse → identical dict.

### 10.2 Reducer — golden fixtures

The core of the suite. Committed fixture logs under `codegen/tests/fixtures/`, each with its expected
state:

| Fixture | Asserts |
|---|---|
| `clean-run.jsonl` | Balanced pairs → complete tree, correct metrics |
| `retry-run.jsonl` | Multiple `issue.validate.end` attempts → `first_pass_rate` correct |
| `aborted-run.jsonl` | Unmatched `version.start` → status `aborted`, no crash |
| `torn-tail.jsonl` | Truncated final line → skipped, `counts.torn == 1` |
| `malformed.jsonl` | Bad JSON + unknown type mid-file → quarantined, rest still reduces |
| `skipped-versions.jsonl` | `version.skipped` → excluded from ETA and velocity |
| `no-review.jsonl` | Version with no review step → **excluded** from findings, not reported as zero |

That last one exists because the prototype got it wrong: it drew a not-yet-reviewed version as a
zero-findings bar, which reads as "clean" when it means "nobody looked." A regression test pins the
distinction.

**Determinism:** reducing the same fixture twice yields byte-identical `state.json`. `reduce` is pure,
so this is cheap to assert and catches accidental clock or environment reads.

### 10.3 Emitter properties

- **Never raises:** parametrized over unwritable path, missing parent dir, non-serializable `data`,
  absent `runs/current`, and a read-only filesystem — every case returns `None` and writes nothing to
  stdout/stderr.
- **Single write:** monkeypatch `os.write` and assert exactly one call per event.
- **Line budget:** a 100 KB `data` payload produces a line ≤ 4096 bytes with `_truncated: true`.
- **Concurrency:** N processes appending M events each yields exactly N×M parseable lines
  (the §4.2 measurement, as an executable test).
- **Redaction:** a table of secret-shaped strings (`sk-ant-…`, `ghp_…`, `AKIA…`, `Authorization:`
  headers) never appears in the output; the redaction marker does.

### 10.4 Reconciliation — testing the untestable part

Skill compliance cannot be unit-tested: whether a model followed an emit instruction is a property of a
*run*, not of code. It is checked **after** a run, as an analysis:

- Every `pytest` invocation seen by hooks has a corresponding skill-emitted `issue.validate.end`.
- Every `issue.commit` has a real commit in `git log`, and vice versa.
- Discrepancies are reported as a **compliance rate**, not a failure. A falling rate is a signal the
  skill files have grown too long — which is the observer-effect risk the vision doc names.

### 10.5 Dashboard

- Reducer output → WS frame shape, asserted against the schema.
- A client connecting mid-run receives a snapshot then a delta stream, and ends in the same state as
  one connected from the start.
- The HTML prototype's palette stays validated: a test shells out to the palette validator and fails
  on a regression, so a colour tweak cannot silently break CVD safety.

### 10.6 What is deliberately not tested

Visual layout. Screenshots are checked by eye during development (that is how the four prototype bugs
surfaced); pixel-diffing a dashboard against a golden image is a maintenance cost with a poor
detection rate. The palette validator covers the part of "looks right" that is actually computable.

---

## 11. Schema evolution

`v` is the schema version, currently `1`. Rules:

- **Additive changes** (new event type, new optional `data` key) do not bump `v`. Readers ignore
  unknown keys and quarantine unknown types (§5.3), so old readers survive new writers.
- **Breaking changes** (renaming a field, changing a type, making an optional field required) bump `v`.
  The reducer keeps handling `v-1` for at least one version.
- A log may contain mixed `v` — the tracker can be upgraded mid-run. Reduce per-event by its own `v`.
- `schema.json` is the single source of truth; §2 and §3 of this document are its prose mirror and are
  updated in the same commit as any change to it.

---

## 12. Build order

Mirrors vision §7; each step is independently useful and none is a prerequisite for the pipeline
itself.

| # | Deliverable | Tests that must land with it |
|---|---|---|
| 1 | `schema.json`, `emit.py`, `runs/` layout | §10.1, §10.3 |
| 2 | `reduce.py` + `state.json` | §10.2 |
| 3 | `ship-phase` spine emits (run/phase/version/step) | fixture from a real run |
| 4 | `execute-issues` emits (issue level, incl. the failure path) | §10.2 retry + no-review fixtures |
| 5 | Hooks + reconciliation | §10.4 |
| 6 | Dashboard server + UI | §10.5 |

Step 4 is where the system starts earning its keep: it is the first point at which the log contains
something git cannot tell you afterwards.
