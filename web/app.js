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

  // ---- Connection status ----

  function setConnected(connected) {
    statusDot.classList.toggle("connected", connected);
    statusLabel.textContent = connected ? "Connected" : "Disconnected";
    chatInput.disabled = !connected;
    chatSend.disabled = !connected;
  }

  // The full match id, never truncated -- it's the exact string a user copies
  // into the agent CLI (web_ui_specification.md §4.1).
  function setMatchIdDisplay(matchId) {
    matchIdEl.textContent = matchId;
    matchIdWrap.hidden = false;
    matchIdSep.hidden = false;
  }

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
    state.currentMatchId = matchId;
    state.myToken = token;
    state.myPlayerName = playerName;
    // A new match in the same tab must start fully interactive again -- game_over
    // is the only thing that ever sets this false (web_ui_specification.md §7).
    state.isGameActive = true;

    setMatchIdDisplay(matchId);

    const ws = new WebSocket(wsUrl(matchId, token));
    state.ws = ws;

    ws.addEventListener("open", () => setConnected(true));
    ws.addEventListener("close", () => setConnected(false));
    ws.addEventListener("error", () => setConnected(false));
    ws.addEventListener("message", (ev) => {
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
        break;
      case "state_update":
        // Board re-render lands in v03.02.
        break;
      case "chat_message":
        // Chat bubble rendering lands in v03.03.
        break;
      case "game_over":
        state.isGameActive = false;
        turnBanner.textContent = `Game Over — ${payload.result}`;
        break;
      case "error":
        console.error("Agent Arena server error:", payload.detail);
        break;
      default:
        console.warn("Agent Arena: unknown event", event);
    }
  }

  // Exposed for the acceptance criteria / tests and any later module split.
  window.routeEvent = routeEvent;
  window.setMatchIdDisplay = setMatchIdDisplay;
})();
