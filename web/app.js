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

// One case per server event (web_ui_specification.md §6.1). Only `joined` does
// anything this phase — rendering lands in v03.02 (board/state_update) and
// v03.03 (chat/game_over/error).
function routeEvent({ event, payload }) {
  switch (event) {
    case "joined":
      mySymbol = payload.symbol;
      break;
    case "state_update":
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
}

init();
