# Next session — run the validation

Written for a session with none of the previous one's context. Everything needed is here
or linked from here.

## What to run

```
/ship-phase v03
```

Ten versions (v01.01 → v03.03) across three phases — the validation workload, and why that
cut, are in [implementation-plan.md](implementation-plan.md) § *Validation workload*.
Dependency fill adds v01 and v02 automatically, so `v03` is the whole command.

## The one instruction that is easy to miss

**Validate the tracking after every version, and treat a failure as a stop.**

```
python3 codegen/validate_run.py --version vXX.YY
```

This is a gate on the **record**, not on the build. The generated code can be perfect while
the log of it is wrong, and that is the failure this project cannot afford. Instrumentation
fails *quietly*: a skill that forgets an emit still produces a log that parses, reduces and
renders — the gap only appears when someone asks the question that event was meant to answer.
Discovering it at version ten means nine versions were recorded wrong.

The gate is written into `ship-phase` Step 1 as well, so following the skill is enough. This
note exists because it is the requirement most likely to be skipped under momentum.

Exit codes: `0` pass · `2` a check failed · `1` no active run.

## State as of the handoff

| | |
|---|---|
| Branch | `codegen-tracking`, clean, synced with `origin` |
| Tags | **none** — deliberately. Both orchestrators skip a version whose tag exists |
| GitHub issues | **none** — `upload-issues` will create the first ones |
| `spec/implementation/` | empty — `generate-issues` writes into it |
| Application code | absent; that is the normal state between runs |
| Tracker | 263 tests, `mypy --strict` and `ruff` clean |
| Hooks | registered in `.claude/settings.json` — **this is why the session was restarted**, they load at session start |

## Check before starting

```bash
git status --short                 # must be clean
git tag                            # must be empty
gh auth status                     # must be logged in
python3 -c "import json;print(json.load(open('.claude/settings.json'))['hooks'].keys())"
```

If `git tag` returns anything matching `vXX.YY.ZZ`, the run will skip those versions and
appear to succeed while doing nothing. Delete them first.

## Watching it

```bash
python3 -m uvicorn dashboard.server:app --port 8420   # from codegen/
```

Then <http://127.0.0.1:8420/>. Two known-good behaviours to sanity-check early: the burn-down's
uncertainty band should be **widest at the start** and narrow as versions decompose, and the
"NOW" line should name the deepest running node.

## If something in the tracking is wrong

Fix the emit, do not fix the log. The log is evidence; if it disagrees with the tree, that
disagreement *is* the finding. `python3 -m tracker.reconcile` reports skill-emit compliance as
a rate — a falling rate means the skill files have grown too long for their instructions to
survive, which is the observer effect the vision doc names.

## Afterwards

`/reset-generated` clears what the run created, by reading the run's own log. Dry by default.
It never touches `codegen/`, the run logs, `.claude/`, or GitHub issues — the logs are the
product, and the issues carry the `ARENA-###` counter.

## The documents

| | |
|---|---|
| [ship-phase-tracking-vision.md](ship-phase-tracking-vision.md) | why, and what each panel shows |
| [architecture.md](architecture.md) | event contract, log format, guarantees, test strategy |
| [dashboard-specification.md](dashboard-specification.md) | how the UI is built |
| [implementation-plan.md](implementation-plan.md) | 24 tasks, all done, plus the validation workload |
