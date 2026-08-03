// AgentArena Web UI -- a stateless renderer of server events (architecture.md §8).
// It holds no authoritative game state: the board comes from the server on every
// state_update, and the Player/Observer role is decided server-side by seat ownership,
// never asserted here.

"use strict";

const API = "/api/v1";

const state = {
  socket: null,
  token: null,
  matchId: null,
  symbol: null,      // "X" | "O" | null (observer, or no seat available)
  seatAvailable: false,
  currentTurn: null,
  over: false,
};

// -- lobby ------------------------------------------------------------------

async function hostMatch() {
  const response = await fetch(`${API}/lobby/match`, { method: "POST" });
  const { match_id: matchId } = await response.json();
  await joinMatch(matchId, false);
}

async function promptAndJoin(spectator) {
  const matchId = window.prompt("Match ID:");
  if (!matchId) return;
  await joinMatch(matchId.trim(), spectator);
}

async function joinMatch(matchId, spectator) {
  const response = await fetch(`${API}/lobby/join`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      match_id: matchId,
      player_name: playerName(),
      spectator: Boolean(spectator),
    }),
  });
  if (!response.ok) {
    setStatus("closed", `Join failed (${response.status})`);
    return;
  }
  const { token } = await response.json();
  state.token = token;
  state.matchId = matchId;
  setMatchIdDisplay(matchId);
  openSocket(matchId, token);
}

function spectateMatch() {
  return promptAndJoin(true);
}

function playerName() {
  return "Human";
}

// -- the single socket ------------------------------------------------------

function openSocket(matchId, token) {
  if (state.socket) state.socket.close();
  resetPlayState();

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${scheme}://${window.location.host}/ws/match/${matchId}?token=${encodeURIComponent(token)}`
  );
  state.socket = socket;

  socket.addEventListener("open", () => setStatus("open", "Connected"));
  socket.addEventListener("close", () => setStatus("closed", "Disconnected"));
  socket.addEventListener("error", () => setStatus("closed", "Connection error"));
  socket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;               // a frame we cannot read is not a reason to die
    }
    routeEvent(message);
  });
}

// Starting a new match in the same tab must not inherit the last game's state.
function resetPlayState() {
  state.symbol = null;
  state.seatAvailable = false;
  state.currentTurn = null;
  state.over = false;
  const banner = document.getElementById("result-banner");
  if (banner) { banner.hidden = true; banner.textContent = ""; }
  const log = document.getElementById("chat-log");
  if (log) log.replaceChildren();
}

// -- event dispatch ---------------------------------------------------------

function routeEvent(message) {
  if (!message || typeof message !== "object") return;
  const payload = message.payload || {};
  switch (message.event) {
    case "joined":        return handleJoined(payload);
    case "state_update":  return handleStateUpdate(payload);
    case "chat_message":  return renderChat(payload);
    case "game_over":     return handleGameOver(payload);
    case "error":         return handleError(payload);
    default:              return;   // unknown events are ignored, never thrown on
  }
}

function handleJoined(payload) {
  state.symbol = payload.symbol ?? null;
  state.seatAvailable = Boolean(payload.seat_available);
  initPlayerCards(state.symbol);
  handleStateUpdate(payload);
}

function handleStateUpdate(payload) {
  state.currentTurn = payload.current_turn ?? null;
  renderBoard(payload.board || [], payload.valid_moves || []);
  markActivePlayer(state.currentTurn);
}

function handleGameOver(payload) {
  state.over = true;
  state.currentTurn = null;
  const banner = document.getElementById("result-banner");
  if (banner) {
    banner.textContent = payload.result === "draw" ? "Draw" : `${payload.result} wins`;
    banner.hidden = false;
  }
  disableBoard();
}

function handleError(payload) {
  setStatus(state.socket && state.socket.readyState === 1 ? "open" : "closed",
            payload.detail || "error");
}

// -- rendering --------------------------------------------------------------

function renderBoard(board, validMoves) {
  const legal = new Set(validMoves);
  document.querySelectorAll(".cell").forEach((cell) => {
    const index = Number(cell.dataset.cell);
    const mark = board[index];
    cell.textContent = mark || "";
    if (mark) cell.dataset.mark = mark; else delete cell.dataset.mark;
    // Enabled only on our own turn, and only for a cell the server calls legal.
    cell.disabled = state.over
      || state.symbol === null
      || state.currentTurn !== state.symbol
      || !legal.has(index);
  });
}

function disableBoard() {
  document.querySelectorAll(".cell").forEach((cell) => { cell.disabled = true; });
}

// null is a legitimate argument: an observer has no seat and must not crash the view.
function initPlayerCards(symbol) {
  const cards = { X: document.getElementById("card-X"), O: document.getElementById("card-O") };
  Object.entries(cards).forEach(([seat, card]) => {
    if (!card) return;
    const name = card.querySelector(".name");
    if (name) name.textContent = symbol === seat ? "You" : "-";
  });
}

function markActivePlayer(turn) {
  ["X", "O"].forEach((seat) => {
    const card = document.getElementById(`card-${seat}`);
    if (card) card.dataset.active = String(turn === seat);
  });
}

function renderChat(payload) {
  const log = document.getElementById("chat-log");
  if (!log) return;
  const item = document.createElement("li");
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = `${payload.sender}:`;
  item.append(who, document.createTextNode(payload.message || ""));
  item.dataset.self = String(payload.sender === playerName());
  log.append(item);
  log.scrollTop = log.scrollHeight;
}

// The full id, never truncated -- it is the string copied into the agent CLI.
function setMatchIdDisplay(matchId) {
  const element = document.getElementById("match-id");
  if (element) element.textContent = matchId;
}

function setStatus(stateName, text) {
  const element = document.getElementById("connection-status");
  if (!element) return;
  element.dataset.state = stateName;
  element.textContent = text;
}

// -- actions ----------------------------------------------------------------

function handleCellClick(event) {
  const cell = event.currentTarget;
  if (cell.disabled || state.over) return;
  if (!state.socket || state.socket.readyState !== 1) return;
  if (state.currentTurn !== state.symbol) return;
  send({ action: "submit_move", payload: { move: Number(cell.dataset.cell) } });
}

function handleChatSubmit(event) {
  event.preventDefault();
  const input = document.getElementById("chat-input");
  if (!input || !input.value.trim()) return;
  send({ action: "chat", payload: { message: input.value.trim() } });
  input.value = "";
}

function send(message) {
  if (state.socket && state.socket.readyState === 1) {
    state.socket.send(JSON.stringify(message));
  }
}

// -- wiring -----------------------------------------------------------------

function init() {
  document.getElementById("host-btn")?.addEventListener("click", hostMatch);
  document.getElementById("join-btn")?.addEventListener("click", () => promptAndJoin(false));
  document.getElementById("observe-btn")?.addEventListener("click", spectateMatch);
  document.getElementById("chat-form")?.addEventListener("submit", handleChatSubmit);
  document.querySelectorAll(".cell").forEach((cell) => {
    cell.addEventListener("click", handleCellClick);
  });
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", init);
}
