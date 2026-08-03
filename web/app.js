// AgentArena — app.js (web_ui_specification.md §6-§8)
// A stateless renderer: one WebSocket, one routeEvent dispatcher. No client-side game truth.

let ws = null;
let currentMatchId = null;
let myToken = null;
let myPlayerName = "Human";
let mySymbol = null;
let isGameActive = true;

const API_BASE = "/api/v1";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

async function createMatch() {
  const response = await fetch(apiUrl("/lobby/match"), { method: "POST" });
  const data = await response.json();
  return data.match_id;
}

async function joinLobby(matchId, spectator) {
  const response = await fetch(apiUrl("/lobby/join"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      match_id: matchId,
      player_name: myPlayerName,
      spectator: spectator,
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    window.alert(`Could not join match: ${body.detail || response.statusText}`);
    return null;
  }
  const data = await response.json();
  return data.token;
}

async function hostMatch() {
  const matchId = await createMatch();
  const token = await joinLobby(matchId, false);
  if (!token) return;
  connectWebSocket(matchId, token);
}

async function joinMatch(spectator) {
  const matchId = window.prompt("Match ID:");
  if (!matchId) return;
  const token = await joinLobby(matchId, spectator);
  if (!token) return;
  connectWebSocket(matchId, token);
}

function connectWebSocket(matchId, token) {
  if (ws) {
    ws.close();
  }
  isGameActive = true;
  currentMatchId = matchId;
  myToken = token;

  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${wsProtocol}//${window.location.host}/ws/match/${matchId}?token=${token}`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    setConnectionStatus(true);
    setMatchIdDisplay(matchId);
  };
  ws.onclose = () => {
    setConnectionStatus(false);
  };
  ws.onmessage = (event) => {
    routeEvent(JSON.parse(event.data));
  };
}

// The full match id is the exact string copied into `agent/agent.py --match-id …` —
// never shortened, or a user copies an id that 404s.
function setMatchIdDisplay(matchId) {
  const el = document.getElementById("match-id");
  const row = document.getElementById("match-id-row");
  if (el) {
    el.textContent = matchId;
    el.title = matchId;
  }
  if (row) {
    row.hidden = false;
  }
}

function setConnectionStatus(connected) {
  const dot = document.getElementById("connection-dot");
  const label = document.getElementById("connection-label");
  if (dot) {
    dot.classList.toggle("disconnected", !connected);
  }
  if (label) {
    label.textContent = connected ? "Connected" : "Disconnected";
  }
}

// renderBoard draws marks into the 9 existing #cell-N buttons and toggles each cell's
// playable/disabled state (web_ui_specification.md §4.2). A cell is playable only when
// it's in validMoves, the game is active, and it's this client's turn — checking
// validMoves directly (not just "cell is empty") matches the spec exactly and doesn't
// assume TicTacToe's specific coincidence that "empty" and "legal" are the same set.
function renderBoard(board, currentTurn, validMoves, mySymbolParam, isGameActiveParam) {
  for (let i = 0; i < 9; i++) {
    const cell = document.getElementById(`cell-${i}`);
    if (!cell) continue;

    const mark = board[i];
    cell.textContent = mark || "";
    cell.classList.remove("x", "o", "empty", "playable");

    if (mark === "X") {
      cell.classList.add("x");
    } else if (mark === "O") {
      cell.classList.add("o");
    } else {
      cell.classList.add("empty");
    }

    const playable =
      validMoves.includes(i) && isGameActiveParam && currentTurn === mySymbolParam;
    if (playable) {
      cell.classList.add("playable");
    }
    cell.disabled = !playable;
  }
}

// Falls back to default X/O labels when `symbol` is null (the Observer case, v03.03) —
// never calls a method directly on `symbol` (web_ui_specification.md §5's
// null.toLowerCase() regression).
function initPlayerCards(symbol) {
  const isX = symbol === "X";
  const isO = symbol === "O";

  const xName = document.getElementById("player-x-name");
  const xRole = document.getElementById("player-x-role");
  const oName = document.getElementById("player-o-name");
  const oRole = document.getElementById("player-o-role");

  if (xName) xName.textContent = isX ? "You" : "Opponent";
  if (xRole) xRole.textContent = isX ? "Human · Player" : "Player";
  if (oName) oName.textContent = isO ? "You" : "Opponent";
  if (oRole) oRole.textContent = isO ? "Human · Player" : "Player";
}

// Highlights whichever player card's symbol equals currentTurn; neither is active
// once currentTurn is null (game over) — web_ui_specification.md §4.3.
function updateActiveCard(currentTurn) {
  const cardX = document.getElementById("player-card-x");
  const cardO = document.getElementById("player-card-o");
  if (cardX) cardX.classList.toggle("active", currentTurn === "X");
  if (cardO) cardO.classList.toggle("active", currentTurn === "O");
}

// Freezes the board (every cell disabled) and shows the result — web_ui_specification.md
// §6.1. `isGameActive` only ever flips back to true at the start of a new match
// (connectWebSocket, §7) — without that reset a second match in the same tab would
// render every cell permanently disabled.
function handleGameOver(result) {
  isGameActive = false;
  for (let i = 0; i < 9; i++) {
    const cell = document.getElementById(`cell-${i}`);
    if (cell) {
      cell.disabled = true;
      cell.classList.remove("playable");
    }
  }
  updateActiveCard(null);

  const label = document.getElementById("connection-label");
  if (label) {
    label.textContent = `Game Over — ${result}`;
  }
  const banner = document.getElementById("turn-banner");
  if (banner) {
    banner.textContent = result === "draw" ? "It's a draw!" : `Game over — ${result} wins!`;
  }
}

function showError(detail) {
  const banner = document.getElementById("turn-banner");
  if (banner) {
    banner.textContent = `Error: ${detail}`;
  }
}

// Appends one chat bubble, styled by sender (web_ui_specification.md §4.4): the
// message whose sender equals this client's own seat symbol renders as "you"
// (left/blue, agent-x); everyone else renders right/pink (agent-o).
function renderChat(sender, message) {
  const messages = document.getElementById("messages");
  if (!messages) return;

  const isSelf = sender === mySymbol;
  const wrapper = document.createElement("div");
  wrapper.className = `msg ${isSelf ? "agent-x" : "agent-o"}`;

  const who = document.createElement("p");
  who.className = "who";
  who.textContent = isSelf ? "You" : sender;
  wrapper.appendChild(who);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = message;
  wrapper.appendChild(bubble);

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

// Chat is disabled entirely for Observers (web_ui_specification.md §4.4, §5) —
// the input/button ship `disabled` in the static HTML; a Player connection
// re-enables them once `joined` reports a real seat symbol.
function setChatEnabled(enabled) {
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  if (input) input.disabled = !enabled;
  if (send) send.disabled = !enabled;
}

function handleChatSubmit(submitEvent) {
  submitEvent.preventDefault();
  if (!ws || ws.readyState !== WebSocket.OPEN || !isGameActive) return;

  const input = document.getElementById("chat-input");
  if (!input) return;
  const message = input.value.trim();
  if (!message) return;

  ws.send(JSON.stringify({ action: "chat", payload: { message: message } }));
  input.value = "";
}

// One case per server event (web_ui_specification.md §6.1).
function routeEvent({ event, payload }) {
  switch (event) {
    case "joined":
      mySymbol = payload.symbol;
      initPlayerCards(mySymbol);
      renderBoard(payload.board, payload.current_turn, payload.valid_moves, mySymbol, isGameActive);
      updateActiveCard(payload.current_turn);
      setChatEnabled(mySymbol !== null);
      break;
    case "state_update":
      renderBoard(payload.board, payload.current_turn, payload.valid_moves, mySymbol, isGameActive);
      updateActiveCard(payload.current_turn);
      break;
    case "chat_message":
      renderChat(payload.sender, payload.message);
      break;
    case "game_over":
      handleGameOver(payload.result);
      break;
    case "error":
      showError(payload.detail);
      break;
    default:
      break;
  }
}

// Guards against every non-actionable state (web_ui_specification.md §6.3): the socket
// isn't OPEN, the game isn't active, or the cell is disabled. Never renders
// optimistically — the board only updates from the server's state_update.
function handleCellClick(index) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !isGameActive) return;

  const cell = document.getElementById(`cell-${index}`);
  if (!cell || cell.disabled) return;

  ws.send(JSON.stringify({ action: "submit_move", payload: { move: index } }));
}

function init() {
  document.getElementById("host-btn").addEventListener("click", () => {
    hostMatch();
  });
  document.getElementById("join-btn").addEventListener("click", () => {
    joinMatch(false);
  });
  document.getElementById("observe-btn").addEventListener("click", () => {
    joinMatch(true);
  });

  for (let i = 0; i < 9; i++) {
    const cell = document.getElementById(`cell-${i}`);
    if (cell) {
      cell.addEventListener("click", () => handleCellClick(i));
    }
  }

  const chatForm = document.getElementById("chat-form");
  if (chatForm) {
    chatForm.addEventListener("submit", handleChatSubmit);
  }
}

init();
