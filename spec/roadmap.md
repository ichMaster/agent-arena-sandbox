# Roadmap — AgentArena

Five self-contained versions, built in order: **v01** Game Core & Server Foundation (the game engine, SQLite persistence, seats, the WebSocket protocol) → **v02** Agent Client (the `LLMClient` seam, an Anthropic Haiku agent that plays a full match) → **v03** Web UI (a vanilla player & observer view) → **v04** Agent-vs-Agent Orchestration (two personas playing each other, watched in the browser — the headline demo) → **v05** Hardening & Polish (resilience, real-server integration tests, docs). Versions map to the roadmap-phase prefix; phases inside a version are numbered `vXX.YY` (XX = version, YY = phase), e.g. `v01.03`. Each phase lists a **Goal**, a short description, a **Tasks** list, a **Definition of Done (DoD)**, and the **Tests** that encode its DoD. This roadmap implements the phased plan in [game_specification.md](game_specification.md) §6 in detail; the contracts it builds are pinned in [architecture.md](architecture.md).

Arc: the **server is the single authority and is built first, never depending on a client** (v01). The two seams that keep games and models pluggable — `GameInterface` and `LLMClient` — plus the WebSocket wire contract are established early (v01–v02) and reused unchanged thereafter. The Agent Client (v02) and the Web UI (v03) are **independent clients of the same protocol**, talking to the server only over HTTP/WS. The arena demo (v04) merely composes them; hardening (v05) makes the whole loop resilient. Complexity is added by version, never all at once. Scope stays inside the MVP (Haiku-only, one live match, SQLite state, vanilla UI — [game_specification.md](game_specification.md) §2); a history-review UI, more games, more vendors, and an admin dashboard are explicitly out.

**Versioning (`vXX.YY.ZZ`).** `XX` = roadmap version (`v01`…`v05`), `YY` = phase within it (`v01.03` → `01.03`), `ZZ` = a post-release fix on that phase. Roadmap phase `vXX.YY` → release `vXX.YY.00`, cut when the phase's issues all land and its tests are green; a fix after it bumps `ZZ`. Never bump the version without explicit confirmation. **The LLM is mocked by default in tests**, so the suite stays deterministic and free. Live model calls are **permitted** — a real key lives in `.env` (gitignored) and a live agent run is a normal way to verify the seam.

---

## v01 — Game Core & Server Foundation

The authoritative substrate. This version builds the engine and a running server that owns a match end to end over the WebSocket protocol — **and nothing here depends on any client**. It establishes all three stable seams (the `GameInterface` game plug-in, the SQLite `Repository`, and the WebSocket event/action wire contract; [architecture.md](architecture.md) §4–§6) and the non-negotiable identity rule (seats keyed by a per-connection token, never by display name; observers never hold a seat; [architecture.md](architecture.md) §5.2). Every move is re-validated server-side. Depends on: nothing — this is the foundation.

### v01.01 — Project skeleton & the game engine

**Goal:** a fully-tested Tic-Tac-Toe engine behind the abstract game seam, in a runnable project.

Stand up the repo skeleton (`pyproject.toml`, pytest, mypy, `.gitignore` already present) and the `games/` package. Define the abstract **`GameInterface`** (`get_state`, `get_valid_moves`, `apply_move`, `is_game_over`) and the concrete **TicTacToe** module — pure logic, no server or transport imports. The **move payload is opaque** to everything but the game module; `apply_move` is the sole legality authority and never raises on bad input ([architecture.md](architecture.md) §4.1). This is the gate everything else builds on.

**Tasks:**
- Repo skeleton: `pyproject.toml` (pytest + mypy config), package layout per [architecture.md](architecture.md) §2.
- `games/interface.py`: the abstract `GameInterface` (the four methods, typed).
- `games/tictactoe.py`: 9-cell board, `X` first, 8 winning lines, `"draw"` when full; `apply_move` returns `False` for out-of-range/occupied/wrong-type moves.
- Exhaustive unit tests directly against the engine.

**DoD:** the TicTacToe engine correctly reports valid moves, applies legal moves, rejects illegal ones without raising, and detects win/loss/draw — verified in isolation, no server involved.

**Tests:** unit — win on every line, draw detection, illegal-move rejection (out of range, occupied, wrong type), `get_valid_moves` shrinks correctly. Contract — the `GameInterface` method signatures (pinned here; must change with the seam).

### v01.02 — Persistence layer (SQLite)

**Goal:** a durable store for matches, seats, moves, and chat, reachable only through one `Repository`.

Add the SQLite persistence layer ([architecture.md](architecture.md) §3, §5.1): an async SQLAlchemy engine over `sqlite+aiosqlite:///./arena.db`, an `async_sessionmaker(expire_on_commit=False)`, a connect-time `PRAGMA foreign_keys=ON`, and `init_models()` to create tables. Four tables — `matches`, `participants`, `moves`, `chat_messages` — with `UNIQUE(match_id, symbol)` on seats. All access goes through the **`Repository`**; **live game state is reconstructed by replaying the move log** through a fresh `GameInterface`, so no serialize/deserialize is added to the seam. Depends on: v01.01.

**Tasks:**
- `server/database.py`: async engine + session maker, FK PRAGMA connect listener, `init_models()`.
- `server/models.py`: ORM models for the four tables ([architecture.md](architecture.md) §5.1), incl. the seat uniqueness constraint.
- `server/repository.py`: `create_match`, `get_match`, `add_participant`, `assign_symbol`, `release_seat`, `log_move`, `log_chat`, `reconstruct_game`, `current_turn`.
- `reconstruct_game`: load ordered moves → replay through a `TicTacToe` instance → the live game; `current_turn` derived from move-count parity, `None` once over.

**DoD:** matches/participants/moves/chat persist to SQLite and survive a process restart; the board and whose-turn are correctly reconstructed by replaying the move log; a second seat for the same symbol is rejected by the DB.

**Tests:** unit/integration against a **throwaway SQLite DB** (temp file or `:memory:`, `foreign_keys=ON`) — round-trip each table, `reconstruct_game` yields the right board/`current_turn`/result after N moves, `UNIQUE(match_id, symbol)` blocks a duplicate seat, FK violations rejected. Contract — the four table shapes.

### v01.03 — Match, seats & lobby REST

**Goal:** clients can create and join a match over REST and receive a seat-bearing token.

Build the seat/identity model over the Repository and the lobby REST surface ([architecture.md](architecture.md) §5.2, §6.1, §6.3). `POST /lobby/match` inserts a match; `POST /lobby/join` validates the match exists (**404 if not**), inserts a `participants` row carrying `is_spectator`, and returns an opaque **token that is the `participant_id`**. Seat assignment is keyed by token: observers are refused a seat permanently; at most two players (X, O). Depends on: v01.02.

**Tasks:**
- `server/auth.py`: `issue_token` / `validate_token`, `IssuedToken{match_id, player_name, is_spectator}`; the token is the participant PK.
- `server/schemas.py`: `JoinRequest{match_id, player_name, spectator?}`, responses for create/join.
- `server/main.py`: FastAPI app + `lifespan` (calls `init_models`), `GET /health`, `POST /api/v1/lobby/match`, `POST /api/v1/lobby/join` (404 on unknown match; `spectator:true` → observer participant).
- Seat rule in `server/match.py` over the Repository: `assign_symbol(match_id, token)` per the §5.2 algorithm; `release_seat`.

**DoD:** creating a match then joining returns a token; joining an unknown match 404s; two distinct tokens get X and O, a third player gets no seat, and a `spectator:true` join can never be assigned a seat — even two joins sharing the display name `"Human"` get distinct seats.

**Tests:** unit — `assign_symbol` (spectator → None, idempotent reconnect, third player → None, name collision stays distinct by token). Integration (`TestClient`) — create→join happy path, 404 on bad match, spectator token flagged.

### v01.04 — WebSocket protocol & move authority

**Goal:** two raw WebSocket clients play a full, server-validated game with chat, to game over.

Add the real-time layer ([architecture.md](architecture.md) §5.3–§5.4, §6.2): the **`ConnectionManager`** (per-match sockets, `broadcast` that serializes once and prunes dead sockets, `close_room`), the `GET /ws/match/{id}?token=` endpoint (bad token → close `4001`), and the event/action protocol. Server→client: `joined`, `state_update`, `chat_message`, `game_over`, `error`; client→server: `submit_move`, `chat`. "Your turn" is a **derived condition** (`current_turn == your symbol`), not an event, and `current_turn` is **`null` on the game-ending move** so no client acts into a closing room. Every `submit_move` runs the §5.4 authority flow. Depends on: v01.03.

**Tasks:**
- `server/websockets.py`: `ConnectionManager` (connect with `participant_id`, disconnect releasing the seat, broadcast, `send_to`, `close_room`); the `{event|action, payload}` envelopes.
- `server/main.py`: the WS endpoint — validate token, `connect`, send `joined`, run the receive loop, cleanup in a **`finally`** block ([architecture.md](architecture.md) §10).
- Handlers: `chat` → persist + broadcast `chat_message`; `submit_move` → assign seat → reconstruct game → check turn → `apply_move` → persist → broadcast `state_update` (`current_turn: null` if over) → on game over broadcast `game_over` + `close_room`.
- Reject out-of-turn / illegal / no-seat moves with an `error` event.

**DoD:** two raw WS clients connect to one match, alternate server-validated legal moves, exchange chat, and reach `game_over` (room then closed); illegal, out-of-turn, and no-seat moves are rejected; the terminal `state_update` reports `current_turn: null`. **This is the v01 release gate.**

**Tests:** contract — every server→client event and client→server action shape (pinned here). Integration — a real WS end-to-end game (connect → alternate moves → win and draw), out-of-turn/illegal/no-seat rejection, `current_turn: null` on the winning move, disconnect releases the seat (cleanup runs via `finally`).

---

## v02 — Agent Client (Haiku)

A standalone CLI agent that plays a full match through the server, driven by **Anthropic Haiku**. It is a true external client — it imports nothing from `server/` and talks only over HTTP/WS. This version establishes the **`LLMClient`** vendor seam (Haiku is the only implementation, but the seam is vendor-agnostic; [architecture.md](architecture.md) §4.2, §7) and the single structured `{move, chat}` response the agent gives per turn. Depends on: v01 (the protocol it speaks).

### v02.01 — `LLMClient` seam & the Anthropic Haiku client

**Goal:** a mockable model seam with one real implementation — Anthropic Haiku — that returns structured output.

Define the **`LLMClient`** abstract seam (`generate_structured_response(prompt, schema) -> schema`) and the **`AnthropicHaikuClient`** (the only implementation), plus `create_llm_client(model_type, api_key, temperature)` for config-driven selection so `agent/agent.py` never imports a concrete client ([architecture.md](architecture.md) §4.2). Structured output is forced at the client (tool-use / JSON schema) and validated into `AgentResponse{move, comment}`; the caller never parses raw text. The model id is a single config constant (Anthropic Haiku, e.g. `claude-haiku-4-5`). Depends on: v01.01 (only the schema types).

**Tasks:**
- `agent/llm.py`: `LLMClient` (generic over a `BaseModel` schema), `AnthropicHaikuClient` via the Anthropic SDK, `create_llm_client` dispatch.
- `agent/schemas.py`: `AgentResponse{move: int, comment: str}`.
- Fail-fast key handling: `ANTHROPIC_API_KEY` required at startup (clear error if missing) — the secret lives only in the agent process.
- A model-id config constant; note to confirm it against the live model list rather than hardcoding a guess.

**DoD:** `create_llm_client("haiku", …)` returns a client whose `generate_structured_response` yields a validated `AgentResponse`; the agent code references only the seam; a missing API key aborts startup with a clear message.

**Tests:** unit — `create_llm_client` dispatch; the client returns a parsed `AgentResponse` from a **mocked** SDK (Anthropic client patched, so the unit test costs nothing); malformed model output surfaces as a validation error; missing key aborts. Contract — the `LLMClient` method + `AgentResponse` schema.

### v02.02 — Profile, persona, memory & prompt

**Goal:** an agent's identity — persona, temperament, and short memory — assembled into a prompt.

Add the **Agent Designer** surface for the MVP: `AgentProfile` (YAML: `name`, `model_type`, `temperature`, `system_prompt`, `memory_limit`), a rolling **`MemoryWindow`**, and the **prompt builder** that composes persona + memory window + the **pushed** board/valid-moves ([architecture.md](architecture.md) §7.2). Because the server pushes full turn state (v01.04), the agent never round-trips to read state. Ship one sample profile. Depends on: v02.01.

**Tasks:**
- `agent/profile.py`: `AgentProfile.load_from_yaml`; strict typing.
- `agent/memory.py`: `MemoryWindow(maxlen=…)` recording recent moves + chat.
- `agent/prompt.py`: `build_prompt(memory, board, valid_moves, persona)`.
- `profiles/aggressive.yml`: a first sample persona.

**DoD:** a profile loads from YAML; the memory window keeps the last *N* events; the prompt builder produces a persona-driven prompt embedding the current board and legal moves.

**Tests:** unit — profile load (incl. defaults/validation), memory windowing/eviction, prompt assembly contains persona + board + valid moves. No model call.

### v02.03 — Agent event loop & decision play

**Goal:** the agent joins a match and plays a complete game, one structured `{move, chat}` per turn.

Build the CLI entrypoint and `AgentSession` ([architecture.md](architecture.md) §7.1): join via REST, open the WS, and on every `joined`/`state_update` where `current_turn == my symbol`, ask Haiku for a decision, **validate the move against `valid_moves`, retry up to `MAX_MOVE_ATTEMPTS`, and fall back to a random legal move** rather than stalling; then send `chat` (the taunt) + `submit_move`. Print reasoning to stdout (**line-buffered** so redirected logs flush) — read-only observability. Depends on: v02.02, v01.04.

**Tasks:**
- `agent/agent.py`: arg parsing (`--match-id`, `--profile`, `--server-url`, optional `--player-name`), `join_match`, WS event loop, `AgentSession`.
- Act only on my turn; decide → validate → retry/fallback → `chat` + `submit_move`.
- Record opponent moves + chat into the memory window; handle `game_over` cleanly.
- Line-buffer stdout/stderr; direct-run shim so `python agent/agent.py …` works.

**DoD:** `python agent/agent.py --match-id <id> --profile profiles/aggressive.yml` joins a match and plays a full game to `game_over` against a second connection; an illegal model move is retried then falls back to a legal one; the process exits cleanly when the room closes. **v02 release gate.**

**Tests:** integration — a full game driven by a **mocked** `LLMClient` (scripted moves incl. one illegal → fallback) against a real server; the agent acts only on its turn and never on the terminal `state_update`. Unit — retry/fallback logic. The default suite makes no model call; a live run is opt-in.

---

## v03 — Web UI (Player & Observer)

The browser renderer: **vanilla HTML/CSS/JS, no build step, served at `/ui`**, holding no authoritative state ([architecture.md](architecture.md) §8). A human is a **Player** (claims a seat, plays + chats) or an **Observer** (no seat, watches board + chat) — the role decided server-side by seat ownership. Depends on: v01 (the protocol). It renders the same events the agent consumes, so it needs no server changes beyond the static mount.

### v03.01 — Static UI shell & connection

**Goal:** the served page connects to a match over WebSocket and shows live connection status.

Ship `web/index.html`, `web/styles.css`, `web/app.js` mounted at `/ui`, plus the **`Cache-Control: no-store`** middleware so edits aren't masked by browser caching ([architecture.md](architecture.md) §3, §8). Lobby controls — **Host**, **Join**, **Observe** — call the REST lobby then open one WebSocket; a `routeEvent({event, payload})` dispatcher is stubbed; the **full match id** is displayed (never truncated — it's the string copied into the agent CLI). Depends on: v01.03/v01.04.

**Tasks:**
- `server/main.py`: mount `StaticFiles("/ui", html=True)`; add the `no-store` middleware for `/ui/*`.
- `web/index.html` + `styles.css`: layout (header, board container, chat panel, lobby controls), dark arena aesthetic.
- `web/app.js`: Host/Join/Observe → `POST /lobby/*` → open WS; connection-status indicator; `setMatchIdDisplay` (full id); `routeEvent` skeleton.

**DoD:** opening `/ui`, hosting a match, connecting shows "Connected" and the full match id; `/ui/*` responses carry `Cache-Control: no-store`.

**Tests:** integration (`TestClient`) — `/ui/` and assets served with `no-store`; the served JS exposes the expected entry points and shows the full (untruncated) match id; non-`/ui` routes keep normal caching.

### v03.02 — Board & gameplay (Player role)

**Goal:** a human claims a seat and plays a full game in the browser.

Render the board and wire player moves ([architecture.md](architecture.md) §8): `renderBoard` from `joined`/`state_update`, cells as real `<button>`s **enabled only when `current_turn === mySymbol`**, a click sends `submit_move`; player cards show the two symbols and whose turn it is; `handleGameOver` disables the board on `game_over`. The `joined` event's `symbol` selects the Player view. Depends on: v03.01.

**Tasks:**
- `routeEvent` cases: `joined` (store symbol, init cards, render), `state_update` (re-render), `game_over` (freeze + banner), `error` (surface).
- `renderBoard`: draw marks, toggle cell `disabled` by turn + legality.
- `handleCellClick` → `submit_move`; guard against off-turn / finished / closed socket.
- Player cards + active-turn highlight; reset play state when starting a new match in the same tab.

**DoD:** a human hosts a match and plays a full game against a v02 agent; cells are clickable only on the human's turn; the board freezes with the result at game over; starting a new match in the same tab works without reload.

**Tests:** integration — served JS wires `renderBoard`/`handleCellClick`/`handleGameOver`; play-state resets on a new match. (DOM behavior validated at the served-asset level, consistent with the no-build UI.)

### v03.03 — Chat & the Observer role

**Goal:** chat works for players, and a human can watch an agent-vs-agent match as a seat-less observer.

Add the chat panel (post + render `chat_message`, sender-labelled) and the **Observer** role ([game_specification.md](game_specification.md) §3.3, [architecture.md](architecture.md) §8): **Observe** joins with `spectator:true`, the `joined` event carries `symbol: null` → a read-only view (board non-interactive, chat visible, no posting) that never claims a seat. `initPlayerCards(null)` must not crash. Depends on: v03.02.

**Tasks:**
- Chat form → `chat` action; `renderChat` labels self vs others; auto-scroll.
- `spectateMatch()` → `promptAndJoin(spectator=true)`; the join body carries the flag.
- Observer rendering: `symbol === null` → default X/O labels, cells never enabled, chat input suppressed; no null-deref.

**DoD:** players exchange chat live; clicking **Observe** on an agent-vs-agent match shows the board + chat updating live without claiming a seat; a spectator's `submit_move` (if forced) is refused server-side. **v03 release gate.**

**Tests:** integration — the served JS carries a real spectate action distinct from Join and sends `spectator:true`; observer join yields `symbol:null` and no seat; host/join still default to non-spectator.

---

## v04 — Agent-vs-Agent Orchestration

The headline demo: two contrasting personas playing each other in one match, watched in the browser. Nothing new in the protocol — this version **composes** v02 (agents) and v03 (the observer view) and adds the orchestration that launches two agents safely against one match. Depends on: v02, v03.

### v04.01 — Contrasting personas (the theater)

**Goal:** two personas whose banter and play styles make a watched match entertaining.

The product is the *theater* ([game_specification.md](game_specification.md) §1), so author two distinct persona profiles whose `system_prompt`s produce a real clash — e.g. an aggressive taunter vs a wary defender — tuned so the chat lands and the play styles differ. Depends on: v02.02.

**Tasks:**
- `profiles/aggressive.yml` (refined) and `profiles/cautious.yml`: contrasting names, tones, temperatures, memory limits.
- Tune each `system_prompt` for in-character banter that stays within the move contract.

**DoD:** running each profile produces visibly different tone and taunting; both still emit valid `{move, comment}` every turn.

**Tests:** unit — both profiles load and validate; (persona quality is judged by demo, not asserted). The unit tests make no model call.

### v04.02 — Arena orchestration script

**Goal:** one command starts an agent-vs-agent match a human can watch to completion.

Add `scripts/run_arena.sh` ([architecture.md](architecture.md) §12): create a match via REST, launch the two agent processes with **correct connection ordering so seats never race or collide** (wait for the first agent's join confirmation before starting the second), print the **Observe** link + match id, and tail both agents' logs until interrupted. The instructions must point at **Observe**, never Join (which would steal a player seat). Depends on: v04.01, v02.03, v03.03.

**Tasks:**
- `scripts/run_arena.sh`: `POST /lobby/match`; launch agent 1 (`--symbol`/profile), wait for its "joined" log line, launch agent 2; print the observe URL; `tail -f` both logs; clean shutdown on Ctrl-C.
- Guard the connection order so X/O assignment is deterministic (no race); instruct the human to **Observe**.

**DoD:** `./scripts/run_arena.sh` starts a full agent-vs-agent match; a human opening `/ui` → **Observe** with the printed id watches the whole game and its banter to `game_over`; the two agents reliably get distinct seats. **v04 release gate.**

**Tests:** script checks — valid bash, references both real profiles and the lobby endpoint, waits for the first agent before the second, and tells users to Observe (not Join).

---

## v05 — Hardening & Polish

Resilience and the rough edges that only surface under real play, then the docs that let a newcomer run everything. No new features — this makes the v01–v04 loop robust. Depends on: v01–v04.

### v05.01 — Resilience & reconnection

**Goal:** the system survives disconnects, reconnects, malformed input, and model errors without stranding a match.

Harden the connection lifecycle ([architecture.md](architecture.md) §9, §10): a dropped seat is **reclaimable** (release on disconnect so a reconnect can take it); malformed JSON yields an `error` event without dropping the connection; a bad token closes with `4001`; model/agent errors degrade to a legal fallback move. Cleanup runs in **`finally`** because a client-initiated drop (with a DB session open) can surface as an async cancellation rather than `WebSocketDisconnect`. Depends on: v01.04.

**Tasks:**
- Release the seat on disconnect (via the `ConnectionManager` owner map → `Repository.release_seat`); allow a reconnect to reclaim it.
- `finally`-based cleanup in the WS handler; treat cancellation and `WebSocketDisconnect` alike.
- Broadcast prunes a socket that fails mid-send without aborting delivery to the rest.
- Graceful handling: malformed JSON → `error`; missing/invalid token → close `4001`.

**DoD:** a player disconnecting mid-game frees their seat for a reconnect; a malformed message is rejected without killing the socket; a dead socket doesn't block broadcasts to others; the server never leaks a seat on any disconnect path.

**Tests:** integration — disconnect frees the seat and a new connection reclaims it; a client-initiated drop still runs cleanup (the cancellation path); broadcast survives one dead socket and reaches the rest; malformed JSON → `error`, connection kept.

### v05.02 — End-to-end integration suite

**Goal:** a real-server, real-WebSocket test suite covering the full loop and the DB.

Add integration coverage that unit mocks miss ([architecture.md](architecture.md) §11): a real uvicorn server + real WS connections exercising connect → play → `game_over`, including the observer and disconnect paths, plus Repository tests on a throwaway SQLite DB. The LLM stays mocked throughout. Depends on: v05.01.

**Tasks:**
- A live-server fixture (real uvicorn + real `websockets`/`TestClient`) for end-to-end games.
- End-to-end scenarios: human-vs-agent, agent-vs-agent, observer join, disconnect/reconnect.
- Repository suite against a temp/`:memory:` SQLite DB (`foreign_keys=ON`).
- Confirm the default test path makes no model call, so CI stays free and deterministic; a live
  end-to-end run remains available and opt-in.

**DoD:** the suite runs a full match over real connections and passes deterministically and free; disconnect/observer/reconnect paths are covered; the DB layer is exercised against a throwaway database.

**Tests:** this phase *is* tests — the acceptance criterion is a green, deterministic, paid-call-free suite spanning unit + contract + integration.

### v05.03 — Polish & docs

**Goal:** a newcomer can run all three modes from the README, and the arena looks the part.

Final polish: the "arena" visual aesthetic on the Web UI, and a README that walks through the three run modes — human-vs-agent, agent-vs-agent, observe — plus setup (`ANTHROPIC_API_KEY` in `.env`, SQLite `./arena.db` is gitignored and resettable by deletion). Depends on: v05.02.

**Tasks:**
- UI polish: consistent glass/arena styling, player cards, board and chat readability.
- `README.md`: setup, the three run modes, the WS protocol summary, testing, links to `game_specification.md` / `architecture.md`.
- Confirm the run scripts and commands in the README actually work from a clean checkout.

**DoD:** following the README from a clean checkout, a newcomer can set up the project and run human-vs-agent, agent-vs-agent, and observe modes; the UI presents the arena cleanly. **v05 release gate — the MVP is complete.**

**Tests:** doc/smoke — the README's commands are accurate; the served UI carries the expected structure. (Visual polish judged by inspection.)
