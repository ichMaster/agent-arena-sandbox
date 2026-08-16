# Web UI Specification — AgentArena

This document governs the **visual and behavioral fidelity** of the Web UI (`web/`, served at
`/ui`). It is the detailed companion to the visual design source
[ui_prototype.html](ui_prototype.html) and the technical contract in
[architecture.md](architecture.md) §8. Where the prototype shows *the look* and architecture.md
pins *the wire contract*, this document specifies *how the page behaves* — components, states,
roles, event handling, and interaction flows. It implements roadmap **v03** ([roadmap.md](roadmap.md)).

> **The UI is a stateless renderer.** It holds **no authoritative game state**. It renders exactly
> what the server pushes and sends back only the actions its role permits. Any disagreement between
> this document and [architecture.md](architecture.md) §6 (the wire contract) is resolved in favor
> of architecture.md.

---

## 1. Principles & constraints

- **Stateless renderer.** No client-side game logic, no optimistic state, no derived board truth.
  Every visible change originates from a server event.
- **Server decides the role.** Whether a connection is a **Player** or an **Observer** is decided
  server-side (by seat ownership; §5) — never asserted by the client.
- **No build step.** Vanilla HTML/CSS/JS only — no framework, no `npm`, no bundler, no transpiler.
- **Self-contained.** No CDN scripts, fonts, or stylesheets. Everything ships from `/ui`. (System
  font stack; no web-font downloads.)
- **Served fresh.** The server sends `Cache-Control: no-store` on `/ui/*` (architecture.md §3) so an
  edit is never masked by browser caching. The UI assumes this and does no cache-busting of its own.
- **Files:** `web/index.html` (structure), `web/styles.css` (the design system), `web/app.js` (one
  WebSocket + the `routeEvent` dispatcher). No inline styles/scripts beyond trivial bootstrapping.

---

## 2. Visual design system — "the arena"

A dark, glassmorphism aesthetic: translucent blurred panels over a gradient backdrop, with neon X/O
accents. Tokens below are the single source of truth (mirrored in `ui_prototype.html`); implement
them as CSS custom properties on `:root`.

### 2.1 Color tokens

| Token | Value | Use |
|---|---|---|
| `--bg-0` / `--bg-1` | `#070a12` / `#0c1120` | page gradient base |
| `--glass` | `rgba(255,255,255,0.045)` | panel fill |
| `--glass-strong` | `rgba(255,255,255,0.07)` | buttons, raised fills |
| `--border` | `rgba(255,255,255,0.09)` | panel/cell borders |
| `--border-bright` | `rgba(255,255,255,0.16)` | button borders, emphasis |
| `--text` | `#e7ebf5` | primary text |
| `--muted` | `#8b93a7` | secondary/labels |
| `--x` / `--x-glow` | `#55a0ff` / `#3b82f6` | **Player X — blue** |
| `--o` / `--o-glow` | `#ff5aa0` / `#ec4899` | **Player O — pink** |
| `--ok` | `#29d17c` | connected indicator |
| `--accent` | `#7c8cff` | primary action, focus |

Background is a layered gradient (two radial glows in the X/O hues over a linear dark base),
`background-attachment: fixed`.

### 2.2 Other tokens

- **Radius:** panels `20px`, cells `16px`, buttons/inputs `12px`, symbol chips `11px`.
- **Glass recipe:** `background: var(--glass)` + `1px` `var(--border)` + `backdrop-filter: blur(22px) saturate(120%)` + soft shadow `0 20px 60px rgba(0,0,0,0.45)`.
- **Typography:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`. Brand 800 weight;
  board marks 800 weight with a colored `text-shadow` glow; labels uppercase, letter-spaced, `--muted`.
- **Motion:** subtle only — `transform: translateY(-1/-2px)` hover lifts, a 2.4s pulse on the
  connection dot, 0.12–0.2s transitions. No large or looping animations. Respect
  `prefers-reduced-motion` by disabling the dot pulse and hover transforms.

---

## 3. Layout

Three regions inside a centered `max-width: 1180px` container:

```
┌──────────────────────────────────────────────────────────┐
│  App bar: brand · connection status · [Host][Join][Observe]│
├───────────────────────────────┬──────────────────────────┤
│  Stage (glass)                │  Chat (glass)             │
│   • turn banner               │   • header + counts       │
│   • 3×3 board                 │   • messages (scroll)     │
│   • player cards (You/Agent)  │   • input + Send          │
└───────────────────────────────┴──────────────────────────┘
```

- **Grid:** `1.35fr 0.9fr` (stage / chat) with `24px` gap.
- **Responsive:** at `≤ 860px` the grid collapses to a single column (stage above chat). The app bar
  wraps its controls (`flex-wrap`); the board uses `width: min(430px, 100%)` with `aspect-ratio: 1`.
  The page body never scrolls horizontally.

---

## 4. Components & states

### 4.1 App bar

- **Brand** — "Agent·Arena" + a small uppercase game tag ("tic-tac-toe").
- **Connection status** — a status dot + label + the **full Match ID**.
  - Dot: `--ok` green + glow, pulsing, when **connected**; muted/red and static when **disconnected**.
  - Label: `Connected` / `Disconnected` / `Game Over — <result>`.
  - **Match ID is shown in full, never truncated.** It is the exact string a user copies into
    `agent/agent.py --match-id …`; a shortened display silently hands out an id that 404s. Use
    `word-break: break-all`; set the element `title` to the id too.
- **Lobby controls** — three buttons: **Host New Match** (primary), **Join Match**, **Observe**.

### 4.2 Board

- 3×3 grid of cells rendered as real `<button>` elements (`id="cell-0"…"cell-8"`).
- **Cell states:**
  | State | Class | Appearance | Interactive |
  |---|---|---|---|
  | Empty, actable | `empty playable` | hover lift + faint X ghost | yes (Player, your turn) |
  | Empty, locked | `empty disabled` | inert | no |
  | Marked X | `x` | blue glyph + blue glow | no |
  | Marked O | `o` | pink glyph + pink glow | no |
  | Winning line | `win` | green inner glow on the 3 cells | no |
- A cell is **playable only when** it is empty **and** it is the human's turn **and** the game is
  active **and** the move is in `valid_moves` (§6). Otherwise it carries `disabled` and ignores clicks.

### 4.3 Player cards

- Two cards side by side: the human ("You") and the opponent (the agent's name, e.g.
  "Aggressor-Prime"), each with a symbol chip (X blue / O pink) and a role line
  ("Human · Player" / "Haiku · Agent"; "Observer" when watching).
- The card whose symbol equals `current_turn` gets `.active` (a colored border + glow + slight lift).
  When `current_turn` is `null` (game over) neither card is active.

### 4.4 Chat panel

- **Header:** "Match Chat" + a participant count ("2 players · N observers").
- **Messages** (scrolling list, newest at bottom, auto-scroll on append):
  | Kind | Class | Placement | Style |
  |---|---|---|---|
  | You (the human player) | `self` | left | blue-tinted bubble, sender label in `--x` |
  | Everyone else | `other` | right | pink-tinted bubble, sender label in `--o` |
  | System notice | `system` | centered | dashed, muted (e.g. "Match started", "Game over — X") |

  Sender label is derived: the server broadcasts `chat_message.sender` as the participant's
  **`player_name`** (e.g. `"Alice"`), never a seat symbol — verified against the real, tested
  behavior in `server/main.py` and `tests/test_ws_chat.py`, unchanged since v01.04. A `chat_message`
  whose `sender` equals the client's own **`myPlayerName`** renders as "you" (left/blue); everyone
  else renders on the right/pink. This is presentation only — chat is non-authoritative flavor, §6.
- **Input row:** a text input ("Message the room…") + **Send**. Disabled until the socket is open;
  in the MVP, disabled entirely for Observers (§5).

---

## 5. Roles: Player vs Observer

The human at the Web UI is in exactly one role per match, **decided server-side** and communicated via
the `joined` event's `symbol`:

| | **Player** | **Observer** |
|---|---|---|
| Entered via | **Host** / **Join** (`spectator:false`) | **Observe** (`spectator:true`) |
| `joined.symbol` | `"X"` or `"O"` | `null` |
| Board | clickable on own turn | always non-interactive |
| Chat | can post + read | read-only (MVP) |
| Holds a seat | yes | **never** (architecture.md §5.2) |

- The client **must not** infer its role from anything but the server's `joined.symbol`. A `null`
  symbol renders the Observer view. `initPlayerCards(null)` must not crash (fall back to default X/O
  labels — never call `null.toLowerCase()`).
- An Observer's board is never enabled; even if a `submit_move` were somehow sent, the server refuses
  it (architecture.md §5.4) — the UI must not depend on that as its only guard.

---

## 6. Event handling (the rendering contract)

`app.js` opens **one** WebSocket to `ws://<host>/ws/match/{match_id}?token=<token>` (the token comes
from `POST /api/v1/lobby/join`) and runs a single dispatcher:

```js
function routeEvent({ event, payload }) { … }   // one case per server event
```

### 6.1 Server → client events → render

| Event | Payload | UI reaction |
|---|---|---|
| `joined` | `symbol` (`X`/`O`/`null`), `board`, `current_turn`, `valid_moves` | store `mySymbol`; init player cards (Player or Observer); render board |
| `state_update` | `board`, `current_turn` (**`null` on the game-ending move**), `valid_moves`, `last_move` | re-render board + turn highlight; append opponent move to memory-free view |
| `chat_message` | `sender`, `message` | append a chat bubble (self → left/blue, other → right/pink) |
| `game_over` | `result` (`X`/`O`/`draw`) | freeze the board, highlight the winning line, show "Game Over — …" in status + a system chat line |
| `error` | `detail` | surface a system/error line; keep the connection |

### 6.2 "Your turn" is derived, not pushed

There is **no `your_turn` event**. The board is interactive when:

```
isMyTurn = isGameActive && (currentTurn === mySymbol)
```

Because `current_turn` is `null` on the game-ending `state_update`, no client is ever invited to act
on the move that ends the game.

### 6.3 Client → server actions

| Trigger | Action sent |
|---|---|
| Click a playable cell | `{ "action": "submit_move", "payload": { "move": <0-8> } }` |
| Submit the chat form | `{ "action": "chat", "payload": { "message": "…" } }` |

Guard every send: ignore clicks when the socket isn't `OPEN`, the game isn't active, or the cell is
`disabled`.

---

## 7. Client-side state (minimal, transient, non-authoritative)

The only state `app.js` keeps — none of it authoritative game truth:

| Var | Meaning |
|---|---|
| `ws` | the live WebSocket (or `null`) |
| `currentMatchId` | the match being viewed |
| `myToken` | the join token (participant id) |
| `myPlayerName` | display name for chat attribution |
| `mySymbol` | `"X"`/`"O"`/`null` from `joined` |
| `isGameActive` | `false` after `game_over`, gates interactivity |

> **Reset `isGameActive = true` when starting a new match** (host/join/observe) in the same tab.
> `game_over` sets it `false` and nothing else flips it back — without the reset, a second match in the
> same tab renders every cell permanently disabled (a real regression to guard against).

---

## 8. Interaction flows

- **Host** → `POST /lobby/match` → `POST /lobby/join {spectator:false}` → open WS → show full match id
  + "Connected". Player role.
- **Join** → prompt for a Match ID → `POST /lobby/join {spectator:false}` → open WS. Player role
  (or a soft rejection if the match is already full).
- **Observe** → prompt for a Match ID → `POST /lobby/join {spectator:true}` → open WS. Observer role
  (`symbol:null`); board never interactive; typically used to watch an agent-vs-agent match.
- **Make a move** — on your turn, click a playable cell → `submit_move` → the server's `state_update`
  re-renders the board (never optimistic).
- **Chat** — type + Send → `chat` → the server's `chat_message` renders it (including your own, echoed
  back) — the UI does not render sent messages optimistically.
- **Game over** — `game_over` freezes the board, marks the winning line, updates status, and posts a
  system line; the server then closes the room (the socket closes → "Disconnected").
- **Disconnect** — the socket closing flips the status to "Disconnected" and disables chat/board. (No
  auto-reconnect in the MVP; the user re-hosts/joins.)

---

## 9. Accessibility

- Board cells are focusable `<button>`s; non-actable cells use the `disabled` attribute (not just a
  class) so they're skipped by keyboard and announced as unavailable.
- Sufficient contrast for text on glass; the X/O distinction is carried by **glyph + position**, not
  color alone (X vs O letters, left vs right chat), so it survives color-blindness.
- Focus-visible outlines on buttons and the chat input; the chat input is reachable and labeled.
- Respect `prefers-reduced-motion` (disable the dot pulse and hover transforms).

---

## 10. Out of scope (MVP)

No admin/observer **dashboard** across matches, no match-history/replay view, no multi-match
navigation, no client-side move validation beyond the interactivity gate, no theming/light mode
(the arena look is a single committed dark aesthetic), no animations beyond §2.2. These are *later*
per [game_specification.md](game_specification.md) §2.

---

## 11. Acceptance criteria (maps to roadmap v03)

- **v03.01** — `/ui` served with `Cache-Control: no-store`; hosting a match connects and shows
  "Connected" + the **full** match id; Host/Join/Observe present; one WebSocket opened.
- **v03.02** — board renders from server events; cells clickable **only** on the human's turn; a click
  sends `submit_move` and the board updates from the resulting `state_update`; `game_over` freezes the
  board with the result; starting a new match in the same tab works without reload.
- **v03.03** — players exchange chat live (self vs other styled correctly); **Observe** joins with
  `spectator:true`, renders `symbol:null` as a read-only view, and never claims a seat.
