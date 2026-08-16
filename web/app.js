// Agent Arena -- Web UI client (architecture.md §8, web_ui_specification.md §6-8).
//
// A stateless renderer: no client-side game logic, no optimistic state. Every
// visible change originates from a server event, dispatched through routeEvent().
// Board rendering (v03.02) and chat rendering + Observer polish (v03.03) fill in
// routeEvent's bodies further -- this file wires the lobby, the connection, and
// the dispatch skeleton only.

(() => {
  "use strict";

  // ---- Client-side state (architecture.md §8 / web_ui_specification.md §7) ----
  // None of this is authoritative game truth -- it's just what the UI needs to
  // render what the server last told it.
  const state = {
    ws: null,
    currentMatchId: null,
    myToken: null,
    myPlayerName: null,
    mySymbol: null,
    isGameActive: true,
    // The last board renderBoard() drew -- game_over's payload carries only
    // `result`, no board (architecture.md §6.2), so this is what lets the
    // win-line highlight be computed client-side (presentational only).
    lastBoard: null,
  };

  // ---- DOM handles ----
  const statusDot = document.getElementById("status-dot");
  const statusLabel = document.getElementById("status-label");
  const matchIdEl = document.getElementById("match-id");
  const matchIdWrap = document.getElementById("match-id-wrap");
  const matchIdSep = document.getElementById("match-id-sep");
  const turnBanner = document.getElementById("turn-banner");
  const btnHost = document.getElementById("btn-host");
  const btnJoin = document.getElementById("btn-join");
  const btnObserve = document.getElementById("btn-observe");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  const boardEl = document.getElementById("board");
  const statusError = document.getElementById("status-error");
  const playerXCard = document.getElementById("player-x");
  const playerXName = document.getElementById("player-x-name");
  const playerXRole = document.getElementById("player-x-role");
  const playerOCard = document.getElementById("player-o");
  const playerOName = document.getElementById("player-o-name");
  const playerORole = document.getElementById("player-o-role");
  const messagesEl = document.getElementById("messages");
  const chatCountEl = document.getElementById("chat-count");
  const chatForm = document.getElementById("chat-form");

  // ---- Connection status ----

  function setConnected(connected) {
    statusDot.classList.toggle("connected", connected);
    statusLabel.textContent = connected ? "Connected" : "Disconnected";
    updateChatEnabled();
  }

  // Gated on role as well as connection state: an Observer (mySymbol === null)
  // never gets to post, even once the socket is OPEN -- posting isn't a
  // Player-only *board* action like submit_move, but web_ui_specification.md
  // §4.4/§5 make chat input Observer-disabled just the same, "in the MVP".
  function updateChatEnabled() {
    const open = state.ws !== null && state.ws.readyState === WebSocket.OPEN;
    const enabled = open && state.mySymbol !== null;
    chatInput.disabled = !enabled;
    chatSend.disabled = !enabled;
  }

  // The full match id, never truncated -- it's the exact string a user copies
  // into the agent CLI (web_ui_specification.md §4.1).
  function setMatchIdDisplay(matchId) {
    matchIdEl.textContent = matchId;
    matchIdWrap.hidden = false;
    matchIdSep.hidden = false;
  }

  // ---- Board rendering (web_ui_specification.md §4.2) ----

  // Created once on first render, then only updated in place -- no click-listener
  // churn on every state_update.
  let cellButtons = null;

  function ensureCells() {
    if (cellButtons) return cellButtons;
    cellButtons = [];
    for (let i = 0; i < 9; i++) {
      const btn = document.createElement("button");
      btn.id = `cell-${i}`;
      btn.type = "button";
      btn.className = "cell empty disabled";
      btn.disabled = true;
      btn.addEventListener("click", () => handleCellClick(i));
      boardEl.appendChild(btn);
      cellButtons.push(btn);
    }
    return cellButtons;
  }

  // submit_move guarded against every non-actable state (web_ui_specification.md
  // §6.3): a stale/late click after the socket closes, the game ends, or the
  // cell becomes disabled is a silent no-op, never a send or a thrown error. No
  // optimistic update -- the board only ever changes from a real state_update.
  function handleCellClick(index) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    if (!state.isGameActive) return;
    const cells = ensureCells();
    const cell = cells[index];
    if (!cell || cell.disabled) return;
    state.ws.send(JSON.stringify({ action: "submit_move", payload: { move: index } }));
  }

  function renderBoard(board, validMoves, currentTurn, mySymbol, isGameActive) {
    state.lastBoard = board;
    const cells = ensureCells();
    // Observers (mySymbol === null) are never playable, regardless of currentTurn
    // (web_ui_specification.md §5) -- mySymbol !== null makes that fall out of
    // the same formula rather than needing a separate branch.
    const isMyTurn = isGameActive && mySymbol !== null && currentTurn === mySymbol;
    for (let i = 0; i < 9; i++) {
      const cell = cells[i];
      const mark = board[i];
      if (mark === "X" || mark === "O") {
        cell.textContent = mark;
        cell.className = `cell ${mark.toLowerCase()}`;
        cell.disabled = true;
      } else {
        const playable = isMyTurn && validMoves.includes(i);
        cell.textContent = "";
        cell.className = playable ? "cell empty playable" : "cell empty disabled";
        cell.disabled = !playable;
      }
    }
  }

  const WIN_LINES = [
    [0, 1, 2], [3, 4, 5], [6, 7, 8],
    [0, 3, 6], [1, 4, 7], [2, 5, 8],
    [0, 4, 8], [2, 4, 6],
  ];

  // Presentational only: the server never names the winning cells (game_over's
  // payload is `{result}` only, architecture.md §6.2) -- this is derived from
  // the board the server already pushed, not an independent legality decision.
  function computeWinningLine(board, result) {
    for (const line of WIN_LINES) {
      if (line.every((i) => board[i] === result)) return line;
    }
    return null;
  }

  function freezeBoard() {
    for (const cell of ensureCells()) {
      cell.disabled = true;
    }
  }

  // ---- Player cards (web_ui_specification.md §4.3) ----

  // Must not crash when mySymbol is null (Observer, §5) -- index.html's own
  // "Player X"/"Player O" markup is already the fallback the spec asks for,
  // so the null branch just restores it rather than deriving anything.
  function initPlayerCards(mySymbol) {
    if (mySymbol === "X") {
      playerXName.textContent = "You";
      playerXRole.textContent = "Player";
      playerOName.textContent = "Opponent";
      playerORole.textContent = "Player";
    } else if (mySymbol === "O") {
      playerOName.textContent = "You";
      playerORole.textContent = "Player";
      playerXName.textContent = "Opponent";
      playerXRole.textContent = "Player";
    } else {
      playerXName.textContent = "Player X";
      playerXRole.textContent = "Observing";
      playerOName.textContent = "Player O";
      playerORole.textContent = "Observing";
    }
  }

  // currentTurn === null (game over, or not yet known) leaves neither card
  // active -- both toggles simply evaluate false, no separate branch needed.
  function updateActiveCard(currentTurn) {
    playerXCard.classList.toggle("active", currentTurn === "X");
    playerOCard.classList.toggle("active", currentTurn === "O");
  }

  // Starting a new match in the same tab must not show the previous match's
  // frozen board, win highlight, or active-turn state before the new match's
  // own joined arrives (web_ui_specification.md §7; code review #1, v03.01,
  // for the same principle applied to the WebSocket itself).
  function resetBoardAndCards() {
    state.lastBoard = null;
    // A prior match's mySymbol must not leak into the new connection's chat
    // gate (updateChatEnabled) during the window before the new match's own
    // joined confirms the real role.
    state.mySymbol = null;
    for (const cell of ensureCells()) {
      cell.textContent = "";
      cell.className = "cell empty disabled";
      cell.disabled = true;
    }
    initPlayerCards(null);
    updateActiveCard(null);
    statusError.hidden = true;
    turnBanner.textContent = "Not connected";
    messagesEl.innerHTML = "";
    chatCountEl.textContent = "";
    updateChatEnabled();
  }

  // ---- Chat (web_ui_specification.md §4.4) ----

  function appendMessage(kind, sender, text) {
    const msg = document.createElement("div");
    msg.className = `msg ${kind}`;
    if (sender !== null) {
      const who = document.createElement("p");
      who.className = "who";
      who.textContent = sender;
      msg.appendChild(who);
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    msg.appendChild(bubble);
    messagesEl.appendChild(msg);
    // Auto-scroll to the newest message (web_ui_specification.md §4.4).
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // Self vs other is derived by comparing sender to state.myPlayerName -- the
  // real, tested contract (server/main.py broadcasts participant.player_name
  // as chat_message.sender, never a seat symbol; see this phase's
  // reconciliation note correcting web_ui_specification.md §4.4).
  function renderChat(sender, message) {
    const kind = sender === state.myPlayerName ? "self" : "other";
    appendMessage(kind, sender, message);
  }

  function renderSystemNotice(text) {
    appendMessage("system", null, text);
  }

  // Guarded the same way handleCellClick is (web_ui_specification.md §6.3): a
  // closed socket or an empty/whitespace-only message is a silent no-op. No
  // optimistic render -- the sender sees their own message via the server's
  // broadcast echo, same non-optimistic principle as the board.
  function sendChat(rawMessage) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    const message = rawMessage.trim();
    if (!message) return;
    state.ws.send(JSON.stringify({ action: "chat", payload: { message } }));
  }

  chatForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    sendChat(chatInput.value);
    chatInput.value = "";
  });

  // ---- Lobby REST calls ----

  async function createMatch() {
    const resp = await fetch("/api/v1/lobby/match", { method: "POST" });
    const body = await resp.json();
    return body.match_id;
  }

  async function joinMatch(matchId, playerName, spectator) {
    const resp = await fetch("/api/v1/lobby/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: matchId, player_name: playerName, spectator }),
    });
    const body = await resp.json();
    return body.token;
  }

  function promptPlayerName() {
    return window.prompt("Your name?", "Player") || "Player";
  }

  function promptMatchId() {
    return window.prompt("Match ID?", "");
  }

  // ---- WebSocket connect ----

  function wsUrl(matchId, token) {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/ws/match/${matchId}?token=${token}`;
  }

  function connect(matchId, token, playerName) {
    // Re-hosting/joining in the same tab (web_ui_specification.md §7) must not
    // leak the previous connection: an abandoned socket the client never closes
    // leaves its server-side seat held forever (websocket_endpoint's cleanup
    // only runs once the socket actually closes).
    if (state.ws) {
      state.ws.close();
    }

    state.currentMatchId = matchId;
    state.myToken = token;
    state.myPlayerName = playerName;
    // A new match in the same tab must start fully interactive again -- game_over
    // is the only thing that ever sets this false (web_ui_specification.md §7).
    state.isGameActive = true;
    resetBoardAndCards();

    setMatchIdDisplay(matchId);

    const ws = new WebSocket(wsUrl(matchId, token));
    state.ws = ws;

    // Closing the old socket above fires its own "close" event asynchronously --
    // without this guard, that stale event could arrive after the new socket's
    // "open" and incorrectly flip the status back to "Disconnected".
    ws.addEventListener("open", () => { if (state.ws === ws) setConnected(true); });
    ws.addEventListener("close", () => { if (state.ws === ws) setConnected(false); });
    ws.addEventListener("error", () => { if (state.ws === ws) setConnected(false); });
    ws.addEventListener("message", (ev) => {
      if (state.ws !== ws) return;
      const envelope = JSON.parse(ev.data);
      routeEvent(envelope);
    });
  }

  // ---- Lobby actions ----

  async function host() {
    const playerName = promptPlayerName();
    const matchId = await createMatch();
    const token = await joinMatch(matchId, playerName, false);
    connect(matchId, token, playerName);
  }

  async function join() {
    const matchId = promptMatchId();
    if (!matchId) return;
    const playerName = promptPlayerName();
    const token = await joinMatch(matchId, playerName, false);
    connect(matchId, token, playerName);
  }

  async function observe() {
    const matchId = promptMatchId();
    if (!matchId) return;
    const playerName = promptPlayerName();
    const token = await joinMatch(matchId, playerName, true);
    connect(matchId, token, playerName);
  }

  btnHost.addEventListener("click", () => { host(); });
  btnJoin.addEventListener("click", () => { join(); });
  btnObserve.addEventListener("click", () => { observe(); });

  // ---- routeEvent: one case per server event (architecture.md §6.2) ----
  // Full rendering lands in v03.02 (board) and v03.03 (chat, Observer polish) --
  // this dispatcher exists now so every event has somewhere to go.

  function routeEvent({ event, payload }) {
    switch (event) {
      case "joined":
        state.mySymbol = payload.symbol;
        turnBanner.textContent =
          state.mySymbol === null ? "Observing" : `You are ${state.mySymbol}`;
        chatCountEl.textContent = state.mySymbol === null ? "Observing" : "Playing";
        updateChatEnabled();
        initPlayerCards(state.mySymbol);
        updateActiveCard(payload.current_turn);
        renderBoard(
          payload.board, payload.valid_moves, payload.current_turn,
          state.mySymbol, state.isGameActive
        );
        renderSystemNotice("Match started");
        break;
      case "state_update":
        updateActiveCard(payload.current_turn);
        renderBoard(
          payload.board, payload.valid_moves, payload.current_turn,
          state.mySymbol, state.isGameActive
        );
        break;
      case "chat_message":
        renderChat(payload.sender, payload.message);
        break;
      case "game_over":
        state.isGameActive = false;
        turnBanner.textContent = `Game Over — ${payload.result}`;
        statusLabel.textContent = `Game Over — ${payload.result}`;
        freezeBoard();
        // game_over carries no current_turn -- neither card should read as
        // active once the game has ended.
        updateActiveCard(null);
        if (payload.result === "X" || payload.result === "O") {
          const line = computeWinningLine(state.lastBoard, payload.result);
          if (line) {
            const cells = ensureCells();
            for (const i of line) cells[i].classList.add("win");
          }
        }
        renderSystemNotice(`Game over — ${payload.result}`);
        break;
      case "error":
        console.error("Agent Arena server error:", payload.detail);
        // Surfaced, connection kept open (web_ui_specification.md §6.1) -- an
        // error event is never itself a reason to disconnect.
        statusError.textContent = payload.detail;
        statusError.hidden = false;
        break;
      default:
        console.warn("Agent Arena: unknown event", event);
    }
  }

  // Exposed for the acceptance criteria / tests and any later module split.
  window.routeEvent = routeEvent;
  window.setMatchIdDisplay = setMatchIdDisplay;
})();
