#!/usr/bin/env bash
# AgentArena — agent-vs-agent orchestration (architecture.md §12, mode 2, roadmap §v04.02).
#
# One command starts a full agent-vs-agent match: creates it via the lobby REST, launches the two
# persona agents in an order that makes X/O deterministic (agent 1 = X, agent 2 = O), prints the
# Observe link, and tails both agents' logs until Ctrl-C.
#
# Usage: ./scripts/run_arena.sh [profile-x] [profile-o]
#   defaults: profiles/aggressive.yml (X) vs profiles/cautious.yml (O)
# Requires: the server already running (uvicorn server.main:app), ANTHROPIC_API_KEY in .env.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, so .env / profiles/ / agent/ resolve

PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

SERVER_URL="${SERVER_URL:-http://127.0.0.1:8000}"
PROFILE_X="${1:-profiles/aggressive.yml}"
PROFILE_O="${2:-profiles/cautious.yml}"

LOG_X="$(mktemp -t arena-x.XXXXXX)"
LOG_O="$(mktemp -t arena-o.XXXXXX)"
PID_X=""
PID_O=""

cleanup() {
  for pid in "$PID_X" "$PID_O"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  rm -f "$LOG_X" "$LOG_O"
}
trap cleanup INT TERM EXIT

echo "[run_arena] creating a match on $SERVER_URL ..."
MATCH_JSON="$(curl -sf -X POST "$SERVER_URL/api/v1/lobby/match")"
MATCH_ID="$(printf '%s' "$MATCH_JSON" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["match_id"])')"

echo "[run_arena] match: $MATCH_ID"
echo "[run_arena] watch it: open $SERVER_URL/ui -> Observe -> paste the match id above"
echo "[run_arena] use Observe, NOT Join -- Join would claim a player seat"

echo "[run_arena] launching agent 1 (X, $PROFILE_X) ..."
"$PYTHON" agent/agent.py --match-id "$MATCH_ID" --profile "$PROFILE_X" \
  --server-url "$SERVER_URL" >"$LOG_X" 2>&1 &
PID_X=$!

# Wait for agent 1's join confirmation before starting agent 2 -- this ordering (not a --symbol
# flag, which doesn't exist) is what makes the seat assignment deterministic: agent 1 = X, agent 2 = O.
for _ in $(seq 1 100); do
  if grep -q "joined as" "$LOG_X" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$PID_X" 2>/dev/null; then
    echo "[run_arena] agent 1 exited before joining -- aborting. Log:" >&2
    cat "$LOG_X" >&2
    exit 1
  fi
  sleep 0.1
done
if ! grep -q "joined as" "$LOG_X" 2>/dev/null; then
  echo "[run_arena] timed out waiting for agent 1 to join. Log:" >&2
  cat "$LOG_X" >&2
  exit 1
fi
echo "[run_arena] agent 1 joined."

echo "[run_arena] launching agent 2 (O, $PROFILE_O) ..."
"$PYTHON" agent/agent.py --match-id "$MATCH_ID" --profile "$PROFILE_O" \
  --server-url "$SERVER_URL" >"$LOG_O" 2>&1 &
PID_O=$!

echo "[run_arena] both agents running -- tailing logs until Ctrl-C."
tail -f "$LOG_X" "$LOG_O"
