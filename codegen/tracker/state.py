"""Persist and rebuild ``state.json``.

Written atomically — a temp file in the same directory, then ``os.replace``. The
dashboard polls this file while the pipeline appends to the log, so a reader must
never observe a half-written snapshot.

``state.json`` is disposable by design: deleting it loses nothing, because
:func:`rebuild` reconstructs it from ``events.jsonl``, which is the source of truth.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracker import paths
from tracker.reduce import State, reduce


def write(run_id: str, state: State) -> Path:
    """Atomically replace this run's ``state.json``."""
    target = paths.state_path(run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.as_dict(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def read(run_id: str) -> dict[str, Any] | None:
    path = paths.state_path(run_id)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            result: dict[str, Any] = json.load(fh)
        return result
    except (OSError, json.JSONDecodeError):
        return None


def rebuild(run_id: str, now: datetime | None = None) -> State:
    """Reduce this run's log and persist the result."""
    events = paths.events_path(run_id)
    lines = events.read_text(encoding="utf-8").splitlines() if events.is_file() else []
    state = reduce(lines, now or datetime.now(UTC))
    state.run_id = run_id
    write(run_id, state)
    return state


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="tracker.state", description="Rebuild state.json from a run's event log."
    )
    parser.add_argument("run_id", nargs="?", help="defaults to the active run")
    args = parser.parse_args(argv)

    run_id = args.run_id
    if not run_id:
        pointer = paths.current_pointer()
        run_id = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    if not run_id:
        print("no run id given and no active run", flush=True)
        return 1

    state = rebuild(run_id)
    print(
        f"{run_id}: {state.counts.get('events', 0)} events, "
        f"{len(state.quarantine)} quarantined, status {state.status}",
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    import sys

    sys.exit(_main(sys.argv[1:]))
