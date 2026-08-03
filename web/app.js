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
// it's empty, the game is active, and it's this client's turn — the interactivity gate
// *is* the client-side legality signal (§1: no move validation beyond it).
function renderBoard(board, currentTurn, mySymbolParam, isGameActiveParam) {
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

    const playable = mark === null && isGameActiveParam && currentTurn === mySymbolParam;
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

// One case per server event (web_ui_specification.md §6.1).
function routeEvent({ event, payload }) {
  switch (event) {
    case "joined":
      mySymbol = payload.symbol;
      initPlayerCards(mySymbol);
      renderBoard(payload.board, payload.current_turn, mySymbol, isGameActive);
      updateActiveCard(payload.current_turn);
      break;
    case "state_update":
      renderBoard(payload.board, payload.current_turn, mySymbol, isGameActive);
      updateActiveCard(payload.current_turn);
      break;
    case "chat_message":
      break;
    case "game_over":
      isGameActive = false;
      break;
    case "error":
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
}

init();
