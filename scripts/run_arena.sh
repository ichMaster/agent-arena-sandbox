#!/usr/bin/env bash
# Arena orchestration: create a match, launch two agents with a connection
# order that guarantees distinct seats, print the human's Observe link, and
# tail both agents' banter live (architecture.md §12, run mode 2).
#
# Usage: scripts/run_arena.sh [profile-1] [profile-2]
#   profile-1, profile-2 default to profiles/aggressive.yml and
#   profiles/cautious.yml -- the v04.01 contrasting pair.
#
# Env: SERVER_URL (default http://127.0.0.1:8000)
#
# There is no --symbol flag on agent/agent.py, and Repository.assign_symbol
# (architecture.md §5.2) gives no way for a client to request a specific
# seat -- the first connection gets X, the second gets O. Connection order
# is therefore the only lever, which is exactly what the join-wait below is
# for: launching agent 2 only once agent 1's own "joined" line confirms it
# already has a seat.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
# Prefer the project's own venv (CLAUDE.md: `.venv/bin/pip install -e ".[dev]"`)
# over a bare `python3` on PATH -- an unactivated shell's system python has
# none of this project's dependencies installed, so agent/agent.py's own
# imports (httpx, websockets, ...) would fail immediately.
if [ -x "${REPO_ROOT}/.venv/bin/python3" ]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python3"
else
  PYTHON="python3"
fi

SERVER_URL="${SERVER_URL:-http://127.0.0.1:8000}"
PROFILE_1="${1:-profiles/aggressive.yml}"
PROFILE_2="${2:-profiles/cautious.yml}"
POLL_INTERVAL_S=0.2
JOIN_TIMEOUT_S=30
JOIN_MAX_POLLS=$("$PYTHON" -c "print(int(${JOIN_TIMEOUT_S} / ${POLL_INTERVAL_S}))")

if ! curl -sf "${SERVER_URL}/api/v1/health" >/dev/null 2>&1; then
  echo "Error: server not reachable at ${SERVER_URL}" >&2
  echo "Start it first with: uvicorn server.main:app" >&2
  exit 1
fi

MATCH_JSON=$(curl -sf -X POST "${SERVER_URL}/api/v1/lobby/match")
MATCH_ID=$("$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["match_id"])' <<<"$MATCH_JSON")

LOG1=$(mktemp)
LOG2=$(mktemp)
PID1=""
PID2=""
TAIL_PID=""
CLEANED_UP=false

cleanup() {
  # Trapped on both TERM/INT and EXIT: a signal runs this once via its own
  # trap, then the script falls off its own end afterward, firing the EXIT
  # trap a second time -- without this guard "Shutting down agents..." (and
  # the kill/wait loops) would run twice.
  if [ "$CLEANED_UP" = true ]; then
    return
  fi
  CLEANED_UP=true
  echo "Shutting down agents..."
  for pid in "$PID1" "$PID2" "$TAIL_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$PID1" "$PID2" "$TAIL_PID"; do
    if [ -n "$pid" ]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -f "$LOG1" "$LOG2"
}
trap cleanup EXIT INT TERM

echo "Match created: ${MATCH_ID}"
echo "Launching agent 1 (${PROFILE_1})..."
"$PYTHON" -m agent.agent --match-id "$MATCH_ID" --profile "$PROFILE_1" --server-url "$SERVER_URL" \
  >"$LOG1" 2>&1 &
PID1=$!

polls=0
until grep -q "joined as" "$LOG1" 2>/dev/null; do
  if ! kill -0 "$PID1" 2>/dev/null; then
    echo "Error: agent 1 exited before joining. Log:" >&2
    cat "$LOG1" >&2
    exit 1
  fi
  if [ "$polls" -ge "$JOIN_MAX_POLLS" ]; then
    echo "Error: agent 1 did not join within ${JOIN_TIMEOUT_S}s. Log:" >&2
    cat "$LOG1" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL_S"
  polls=$((polls + 1))
done

echo "Agent 1 joined. Launching agent 2 (${PROFILE_2})..."
"$PYTHON" -m agent.agent --match-id "$MATCH_ID" --profile "$PROFILE_2" --server-url "$SERVER_URL" \
  >"$LOG2" 2>&1 &
PID2=$!

echo ""
echo "Both agents launched. Watch the match at:"
echo "  ${SERVER_URL}/ui  -->  click Observe  -->  Match ID: ${MATCH_ID}"
echo "(Observe, not Join -- Join would claim one of the two seats the agents need.)"
echo ""
echo "Press Ctrl-C to stop."

# Run in the background and wait rather than tail -f as the foreground
# command directly: bash defers a trap's execution until a foreground
# pipeline returns, and tail -f never returns on its own -- a signal sent to
# just this script's PID (not the whole process group, e.g. any non-interactive
# stop) would otherwise never reach the trap, and the EXIT cleanup would
# never run.
tail -f "$LOG1" "$LOG2" &
TAIL_PID=$!
wait "$TAIL_PID"
