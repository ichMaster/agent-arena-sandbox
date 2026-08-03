# AgentArena Specification

## 1. Vision

AgentArena is a **spectatable arena for LLM-powered agents** to compete — and trash-talk — at 2-player, turn-based board games, in real time, against humans or each other.

The game itself is deliberately the *substrate*, not the point: Tic-Tac-Toe is near-trivial to play well, so the interesting thing is never "can the AI win." The product is the **theater** — distinct agent personas reasoning aloud, taunting, and clashing under live observation, on top of a clean, game-agnostic engine that more interesting games can be plugged into later.

**MVP in one sentence:** a human plays Tic-Tac-Toe against an Anthropic Haiku agent (or watches two agents play) in a single live match, with real-time chat, in the browser.

## 2. Scope

The framework is designed broad but built narrow. This table is the contract for what "done" means *now* versus what the design must merely leave room for.

| Capability | MVP (build now) | Later (design for, don't build) |
|---|---|---|
| Games | Tic-Tac-Toe | Connect 4, Russian Checkers, Chess |
| Match concurrency | One live match at a time | Many concurrent matches |
| Players | 1 human + 1 agent, or 2 agents | — |
| Agent model | Anthropic **Haiku** only | Other Anthropic tiers / other vendors, via the `LLMClient` seam |
| Web UI | Player view (play + chat) | Admin/observer dashboard across all games |
| Persistence | **SQLite** (matches, seats, moves, chat) via SQLAlchemy — survives a server restart | A **UI to review** past matches (the data is already persisted) |
| Watching a match | **Observer role** — a human can watch the single live match (especially agent-vs-agent) without holding a seat | Many concurrent spectators; a cross-match observer/admin dashboard |
| Operator input | Read-only (watch the agent think) | Human co-piloting the agent mid-game |

## 3. Architecture & Core Components

A decoupled **client–server** architecture. The server is the single authority; every client is a thin renderer or a thin actor.

### 3.1 Game Server (central authority)
- Owns the authoritative game state and **validates every move** — client claims are never trusted.
- **Tech:** Python + FastAPI. Real-time transport over WebSockets (§3.6); a small REST surface for non-real-time actions only (lobby/join, auth). REST is never used to poll game state.
- Holds a **Connection Manager** mapping `match_id` → connected sockets, and routes/broadcasts events.

### 3.2 Agent Client (CLI)
- A standalone Python process running the LLM loop. **Model: Anthropic Haiku** (only implemented client for now).
- Waits for the server to push its turn, assembles a prompt from **persona + memory window + the pushed board/valid-moves**, asks Haiku for a single structured decision, and pushes it back.
- **Observability:** the agent CLI prints its reasoning and actions to stdout so whoever runs the process can watch it think. This is strictly **read-only** — watching the CLI never influences the agent's play. (Distinct from the Web UI *observer* role in §3.3, which is a browser viewer of the match.)

### 3.3 Web UI (player & observer)
The browser frontend. It holds **no authoritative state** — it renders whatever the server pushes and sends back only the actions its role permits. **Stack:** vanilla HTML/CSS/JS, no build step, served by FastAPI at `/ui` (a stateless renderer — a framework's client-side state is exactly what this architecture forbids).

A human at the Web UI is in one of two roles for a given match:
- **Player** (human-vs-agent) — claims a seat, sees the board graphically, takes their turn (`submit_move`), and chats (`send_chat_message`).
- **Observer** (agent-vs-agent, or simply watching) — holds **no seat**, cannot move, and watches the board and chat update live. This is the natural role when two agents play each other.

The role is decided **server-side** by whether the connection holds a seat (§4) — never by the client asserting it. In the MVP, only players post chat; observers watch (board + chat) read-only.

### 3.4 Game Modules (the pluggable seam)
Every game implements one abstract **`GameInterface`** on the server and is otherwise fully decoupled from transport:
- `get_state()` — structured representation of the current board.
- `get_valid_moves()` — legal moves for the player to move.
- `apply_move(move)` — validate and apply a move, updating state.
- `is_game_over()` — the result (win / loss / draw) if the game has ended, else "ongoing."

The **move payload is opaque to the transport layer** — a cell index `0–8` for Tic-Tac-Toe, algebraic notation for chess, etc. Only the game module interprets and validates it; the server, WebSocket layer, and UI pass it through unexamined. New games are added as **new modules**, never by generalizing an existing game's code.

### 3.5 Chat
- A real-time chat channel per match. Humans chat via the Web UI; agents chat via `send_chat_message`; every message is broadcast to all connections in the room.
- Chat is **non-authoritative flavor** — taunts, strategy-talk, banter. It never affects move legality or game state.

### 3.6 Event-Driven Networking (WebSockets)
No polling. Clients hold a persistent WebSocket; the server **pushes** JSON events as they happen.

- **On a client's turn, the server pushes the full context it needs** — the board, the legal moves, and which symbol the client is — in a single event. The client never has to pull state back to reason about its move.
- **The agent responds with one structured decision per turn: `{ move, chat }`** — its chosen move plus an optional taunt — in a single message. There is no multi-step "ask the server what the moves are, then decide" round-trip in the MVP. (An optional `get_game_status()` resync tool is a *later* affordance, only if a future game needs mid-turn refresh; the design leaves room for it but the MVP omits it.)
- Illustrative event set (exact JSON schemas are pinned separately when the server is built): server→client `joined`/`your_turn`, `state_update`, `chat_message`, `game_over`, `error`; client→server `submit_move`, `send_chat_message`.

## 4. Identity, Authority & Secrets

These are non-negotiable and were the sharpest gaps in the original vision — call them out explicitly:

- **Seats are claimed by a unique per-connection token, never by display name.** Two clients can share a display name (a UI may default everyone to "Human"); they must never collide onto the same player seat. Display names are for labels (chat, logs) only.
- **A spectator connection never holds a player seat** — even if it later tries to submit a move. (Spectators are a *later* capability, but the seat model is designed for them from the start.)
- **The server is the ultimate authority.** LLM output is untrusted text; every move is re-validated against the game module server-side regardless of what the agent claims is legal. A client may only move for the seat it was assigned.
- **Secrets stay in the agent process.** The LLM API key lives in the agent's `.env` and is never transmitted to, or logged by, the server or Web UI.

## 5. Agent Model & Designer

### 5.1 LLM abstraction (`LLMClient`)
The agent talks to a model vendor only through an `LLMClient` seam, keeping agent logic free of any specific SDK. The seam is **vendor-agnostic by design** — other Anthropic tiers or other vendors can be added as new client implementations without touching agent logic. For now, **the only implemented client is Anthropic Haiku, and every agent uses it.**

### 5.2 Agent Designer
A configuration layer for building distinct agent identities without touching core logic. It packages a config into a runnable standalone Agent Client. Configurable parameters:
- **Persona / System Prompt** — who the agent is: playstyle, skill level, tone (this is what makes the arena interesting).
- **Memory** — the short-term history length (recent moves + chat) the agent carries into each prompt.
- **Model** — fixed to Anthropic Haiku for now; a field the seam in §5.1 will later let vary.

## 6. Phased Implementation Plan

Five dependency-ordered phases. Each is **independently demoable** and leaves the system in a working state — no phase depends on a later one. A history-review UI, additional games, additional vendors, and the admin dashboard are all **out of these phases** (see the §2 scope table).

Phases map onto the `vXX` version prefix (Phase 1 → `v01`, …); the build workflow later decomposes each into `vXX.YY` sub-versions and `ARENA-xxx` issues. Every phase ships its own tests, and **the LLM is mocked by default in tests**; live calls are permitted and opt-in.

### Phase 1 — Game Core & Server Foundation *(the gate)*
**Goal:** the authoritative engine and a running server that owns a match and speaks the WebSocket protocol.
**Delivers:**
- `GameInterface` (abstract) + a fully unit-tested **Tic-Tac-Toe** module (`get_state`/`get_valid_moves`/`apply_move`/`is_game_over`); move payload opaque to transport.
- FastAPI app skeleton, health endpoint, and the `/ui` static mount (stubbed until Phase 3).
- **SQLite persistence** (SQLAlchemy async + a `Repository`): `matches`, `participants`/seats, `moves`, `chat` tables; durable across restart.
- **Match + seat state** over that store: token-based seat assignment per §4 (seats by per-connection token, never by name; observers hold no seat); board reconstructed from the move log.
- **Connection Manager** (connect/disconnect/broadcast, match routing) and the server-push event set (`joined`/`your_turn`, `state_update`, `chat_message`, `game_over`, `error`).
- Lobby REST (create match, join → issue token). Every move **re-validated server-side**.

**Done when:** two raw WebSocket clients connect to one match, alternate server-validated legal moves, exchange chat, and reach `game_over`; illegal and out-of-turn moves are rejected; a third connection gets no seat.

### Phase 2 — Agent Client (Haiku)
**Goal:** a standalone CLI agent that plays a full match through the server, driven by Anthropic Haiku.
**Delivers:**
- The `LLMClient` seam + the **Anthropic Haiku** client (only implementation), mocked in all tests.
- `AgentProfile` (persona/system prompt, memory limit, model=Haiku) and the prompt builder (persona + memory window + the pushed board/valid-moves).
- WS event loop: on `your_turn`, produce **one structured `{move, chat}`**, submit it, retry on an invalid/hallucinated move, fall back to a legal move rather than stalling.
- Memory window; CLI observability (agent prints its reasoning to stdout, read-only).

**Done when:** `agent.py --match-id … --profile …` joins a match and plays a complete game against a second connection; all model calls are mocked in tests (zero paid calls).

### Phase 3 — Web UI (Player & Observer)
**Goal:** the browser renderer — a human plays a match, and can watch an agent match.
**Delivers:**
- Vanilla HTML/CSS/JS served at `/ui`: lobby controls (host / join / observe), connection status, full match-id display; `Cache-Control: no-store` on `/ui`.
- Board render (3×3 buttons, disabled off-turn), player cards, chat panel; a single `routeEvent` dispatcher over the server events.
- **Player** role (claims a seat, plays + chats) and **Observer** role (no seat, watches board + chat live), with the role decided server-side.

**Done when:** a human hosts a match in the browser and plays a full game against a Phase-2 agent with working chat; opening an agent-vs-agent match renders the live board + chat as an observer without claiming a seat.

### Phase 4 — Agent-vs-Agent Orchestration *(the headline demo)*
**Goal:** two personas playing each other in one match, watchable in the browser — the arena theater.
**Delivers:**
- An orchestration script that launches two agent CLIs against one match with correct connection/seat ordering (no seat-stealing, no races).
- Two contrasting sample personas so the chat banter lands.
- The end-to-end observer flow (a human watches two agents to `game_over`).

**Done when:** one command starts an agent-vs-agent match and a human, opening the browser as observer, watches the whole game and its banter to completion.

### Phase 5 — Hardening & Polish
**Goal:** resilience and the rough edges that only surface under real play.
**Delivers:**
- Reconnect handling (match state survives a client reconnect; a dropped seat is reclaimable) and graceful handling of disconnects, malformed input, and model errors.
- End-to-end integration tests against a **real** server + real WebSocket connections (not just mocked units).
- UI polish (the arena aesthetic) and a README that lets a newcomer run all three modes (human-vs-agent, agent-vs-agent, observe).

**Done when:** the full loop survives disconnects/reconnects and bad input; integration tests pass; the three run modes are reproducible from the README.
