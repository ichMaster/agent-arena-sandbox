# AgentArena

A spectatable arena for LLM-powered agents. Two personas (or a human and a persona) play
Tic-Tac-Toe over a real-time WebSocket connection while a browser UI renders the board, the turn,
and their in-character banter live. The server is the sole authority on every move; the agents and
the UI are both just clients of it.

The full product vision lives in [spec/game_specification.md](spec/game_specification.md); the
complete technical contract — every seam, wire shape, and identity rule — lives in
[spec/architecture.md](spec/architecture.md). This README is a shorter, task-oriented summary of
both, enough to set up the project and run all three modes.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

If you plan to run a real agent (either run mode below that isn't the default test suite), add an
Anthropic API key to a `.env` file at the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored — the key never leaves your machine, and the server/UI never see it (only
`agent/` reads it). No key is needed to run the test suite: the LLM is mocked by default there.

State persists to `./arena.db` (SQLite, gitignored). It survives restarts across all three run
modes below; delete the file to reset every match back to nothing.

## The three run modes

All three assume the server is running:

```bash
.venv/bin/uvicorn server.main:app
```

The UI is served at **http://127.0.0.1:8000/ui** with `Cache-Control: no-store`, so an edit to
`web/` is always reflected on refresh.

### 1. Human vs. agent

1. Open `/ui` in a browser and click **Host New Match**. Note the full match ID shown in the app
   bar — it's the exact string the agent needs below.
2. In another terminal, launch an agent against that match:

   ```bash
   .venv/bin/python -m agent.agent --match-id <id> --profile profiles/aggressive.yml
   ```

   `--profile` points at a persona YAML (`profiles/aggressive.yml` — swaggering and forceful, or
   `profiles/cautious.yml` — wary and methodical). `--server-url` defaults to
   `http://127.0.0.1:8000`; `--player-name` defaults to the persona's own name.
3. Play from the browser — cells are clickable only on your turn.

### 2. Agent vs. agent

With the server running:

```bash
./scripts/run_arena.sh
```

This creates a match, launches two agents (defaulting to `profiles/aggressive.yml` and
`profiles/cautious.yml` — pass two different profile paths as positional args to use others),
waits for the first to actually claim its seat before launching the second (there's no way to
request a specific seat — connection order is what decides X vs. O), and prints the match ID plus
an instruction to **Observe** it. It then tails both agents' reasoning/banter to your terminal
until the game ends or you press Ctrl-C. Override the server address with `SERVER_URL` if it's not
running on the default host/port.

### 3. Observe

Open `/ui`, click **Observe**, and paste in a match ID (from either mode above). The board and
chat update live and the game plays out — an observer never claims a seat and can't post chat in
the MVP; it's a read-only window onto a match two other participants are actually playing.

## The WebSocket protocol, briefly

One WebSocket per connection: `GET /ws/match/{match_id}?token=<token>` (the token comes from
`POST /api/v1/lobby/join`). Every message is `{"event": ..., "payload": ...}` from the server or
`{"action": ..., "payload": ...}` from the client.

| Server → client event | When |
|---|---|
| `joined` | Once, right after connecting — carries your symbol (`X`/`O`/`null` if observing), the board, whose turn it is, and the legal moves. |
| `state_update` | After every valid move. |
| `chat_message` | After anyone sends chat. |
| `game_over` | When the game ends — the server closes the room right after. |
| `error` | Malformed input or an illegal action — the connection stays open. |

| Client → server action | Payload |
|---|---|
| `submit_move` | `{move}` — re-validated server-side regardless of what the client thinks is legal. |
| `chat` | `{message}` — non-authoritative flavor text, broadcast to everyone in the room. |

"Your turn" is never pushed as its own event — it's derived as `current_turn === yourSymbol` from
whatever `joined`/`state_update` most recently said. The full contract, including the REST lobby
endpoints, the seat-identity rules, and every non-negotiable design decision, is
[spec/architecture.md](spec/architecture.md) §5–§6.

## Testing

```bash
.venv/bin/pytest
.venv/bin/mypy games server agent
```

The LLM is mocked by default throughout the suite (a `ScriptedLLMClient` fake) — it's fully
deterministic and makes zero calls to Anthropic, so it's free to run as often as you like. A live
run against the real API is possible (either run mode above) but is never part of the default
suite. Integration tests run against a real `uvicorn` server and real WebSocket connections, not
just in-process mocks, so they exercise the actual protocol — including disconnect/reconnect,
observer-role, and full agent-vs-agent games.
