# AgentArena

A real-time, LLM-agent Tic-Tac-Toe theater. Anthropic **Haiku**-powered agents play each other — or
a human — over WebSockets, watchable live in a browser as a **Player** (claims a seat, plays + chats)
or an **Observer** (no seat, watches board + chat).

## Architecture at a glance

Three cooperating processes over an event-driven WebSocket protocol (no REST polling for game state):

- **Game Server** (Python + FastAPI) — the sole authority. Owns state in SQLite, validates every move
  server-side, and pushes JSON events to connected clients.
- **Agent Client** (Python CLI) — a standalone LLM-driven process. The server pushes full turn state;
  the agent replies with one structured `{move, chat}` per turn. A pure external client over HTTP/WS —
  imports nothing from `server/`.
- **Web UI** — vanilla HTML/CSS/JS served at `/ui`; a stateless renderer of server events.

Two stable seams make this pluggable: **`GameInterface`** (how a game plugs into the server) and
**`LLMClient`** (how an agent talks to a model vendor — Anthropic Haiku today, swappable by config).

Details: [spec/game_specification.md](spec/game_specification.md) (product vision + scope),
[spec/architecture.md](spec/architecture.md) (module layout, contracts, identity model),
[spec/web_ui_specification.md](spec/web_ui_specification.md) (the Web UI's behavior + design).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Put your key in `./.env` (gitignored; copy from `.env.example`):

```
ANTHROPIC_API_KEY=sk-...
```

The key is read **only** by the agent process (`agent/agent.py`) — it is never sent to or logged by
the server or the Web UI. The server, the UI, and the test suite make **no paid calls** and need no
key at all.

## Run

Start the server first, in its own terminal:

```bash
uvicorn server.main:app
```

Then pick a mode:

### 1. Human vs. agent

Open `http://127.0.0.1:8000/ui` in a browser → **Host** a match, note the match id. Then run an agent
against it:

```bash
python agent/agent.py --match-id <id> --profile profiles/aggressive.yml
```

Play your moves in the browser; the agent (Ironclaw, an aggressive taunter) plays and chats back.

### 2. Agent vs. agent — the headline demo

```bash
./scripts/run_arena.sh
```

One command creates a match and launches two contrasting personas — **Ironclaw** (aggressive,
`profiles/aggressive.yml`) vs **Bastion** (cautious, `profiles/cautious.yml`) — against each other,
with deterministic seat assignment. It prints the match id and tails both agents' logs.

### 3. Observe

Open `/ui` → **Observe** → paste the match id from either mode above. Watch the board and chat update
live, without ever claiming a seat. **Use Observe, not Join** — Join claims a player seat.

## WebSocket protocol (summary)

One socket per client: `GET /ws/match/{match_id}?token=<token>` (the token comes from
`POST /api/v1/lobby/join`).

**Server → client events:** `joined`, `state_update`, `chat_message`, `game_over`, `error`.
**Client → server actions:** `submit_move {move}`, `chat {message}`.

"Your turn" is derived, not pushed: a client acts when `current_turn` in a `joined`/`state_update`
event equals its own seat symbol. Full contract: [spec/architecture.md](spec/architecture.md) §6.

## Testing

```bash
pytest
mypy
```

The `LLMClient` seam is **always mocked** in tests (an autouse `tests/conftest.py` guard enforces
this even for a test that forgets to mock it locally) — the suite makes **zero paid API calls**.

## Data & reset

State lives in `./arena.db` (SQLite, gitignored) and survives restarts. Delete the file to reset all
matches.
