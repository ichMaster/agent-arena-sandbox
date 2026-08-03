"""Stop hook — close out a run that died without saying so.

A run killed mid-flight leaves ``*.start`` with no terminator. Without this, the only
signal is staleness, which the dashboard would have to guess from. Writing
``run.aborted`` is the honest version (vision §8, architecture §9.2).

This does not decide anything: the *next* orchestrator invocation still asks whether
to resume or supersede (architecture §9.3). It only records that the run stopped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker import emit, paths  # noqa: E402

EMITTER = "hook:on-stop"
TERMINAL = {"run.end", "run.aborted"}


def run_is_open(run_id: str) -> bool:
    """True when the run has events but no terminal one."""
    path = paths.events_path(run_id)
    if not path.is_file():
        return False
    seen = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        # Any content at all means a run was underway. A torn line is *evidence* the
        # run died mid-write -- exactly the case this hook exists for -- so it must
        # count, not be skipped into "nothing ever happened".
        seen = True
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in TERMINAL:
            return False
    return seen


def main() -> int:
    try:
        run_id = emit.current_run_id()
        if run_id and run_is_open(run_id):
            emit.emit(
                "run.aborted", emitter=EMITTER, status="fail",
                data={"reason": "session-stopped"},
            )
    except BaseException:  # noqa: BLE001 - a hook must never disturb its session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
