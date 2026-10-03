(async function () {
  const { id: userId, name: userName } = await SD.ensureIdentity();
  const root = document.querySelector(".debate");
  const sessionId = root.dataset.sessionId;

  const titleEl = document.getElementById("debate-topic-title");
  const descEl = document.getElementById("debate-topic-description");
  const strip = document.getElementById("phase-strip");
  const dot = document.getElementById("phase-dot");
  const label = document.getElementById("phase-label");
  const timerEl = document.getElementById("phase-timer");
  const barFill = document.getElementById("phase-bar-fill");
  const transcript = document.getElementById("transcript");
  const composerArea = document.getElementById("composer-area");
  const input = document.getElementById("argument-input");
  const wordCount = document.getElementById("word-count");
  const sendBtn = document.getElementById("send-btn");
  const leaveBtn = document.getElementById("leave-btn");
  const endedBanner = document.getElementById("ended-banner");
  const endedTitle = document.getElementById("ended-title");
  const endedDetail = document.getElementById("ended-detail");

  let latestState = null;
  let ws = null;
  let reconnectAttempts = 0;

  function formatClock(totalSeconds) {
    const s = Math.max(0, Math.round(totalSeconds));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function wordsIn(text) {
    const trimmed = text.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  function renderTranscript(state) {
    if (!state.messages.length) {
      transcript.innerHTML = '<p class="transcript-empty">The transcript will appear here once the first argument is sent.</p>';
      return;
    }
    transcript.innerHTML = state.messages
      .map((m) => {
        const mine = m.user_id === state.you.id;
        const name = mine ? "You" : SD.escapeHtml(state.opponent.name);
        const cls = ["transcript-entry", mine ? "mine" : "theirs", m.auto_submitted ? "auto" : ""].join(" ").trim();
        return `<div class="${cls}">
                  <div class="transcript-entry-head">
                    <span class="name">${name}</span>
                    <span class="round">Round ${m.round}</span>
                  </div>
                  <div class="transcript-entry-text">${SD.escapeHtml(m.text)}</div>
                </div>`;
      })
      .join("");
  }

  function endedMessage(state) {
    if (state.end_reason === "left") {
      return state.ended_by_you
        ? "You ended this debate."
        : `${state.opponent.name} left the debate.`;
    }
    if (state.end_reason === "rounds_complete") {
      return "This debate has reached its round limit.";
    }
    return "This debate is no longer active.";
  }

  function applyState(state) {
    latestState = state;

    titleEl.textContent = state.topic.title;
    descEl.textContent = state.topic.description || "";
    descEl.hidden = !state.topic.description;

    renderTranscript(state);

    if (state.phase === "ended") {
      strip.dataset.phase = "ended";
      dot.style.background = "";
      label.textContent = "Debate ended";
      timerEl.textContent = "";
      barFill.style.transform = "scaleX(0)";
      composerArea.hidden = true;
      leaveBtn.hidden = true;
      endedBanner.hidden = false;
      endedTitle.textContent = "This debate has ended";
      endedDetail.textContent = endedMessage(state);
      return;
    }

    endedBanner.hidden = true;
    composerArea.hidden = false;
    leaveBtn.hidden = false;

    if (state.phase === "waiting") {
      strip.dataset.phase = "connecting";
      label.textContent = "Waiting for both of you to connect…";
      timerEl.textContent = "";
      barFill.style.transform = "scaleX(1)";
    } else if (state.phase === "reflecting") {
      strip.dataset.phase = "reflecting";
      label.textContent = "Time to reflect on what was just said";
    } else if (state.phase === "arguing") {
      strip.dataset.phase = state.your_turn ? "arguing-you" : "arguing-opponent";
      label.textContent = state.your_turn
        ? "Your turn to write"
        : `${state.opponent.name} is writing a response`;
    }

    const canWrite = state.phase === "arguing" && state.your_turn;
    input.disabled = !canWrite;
    sendBtn.disabled = !canWrite;
    if (canWrite && document.activeElement !== input) {
      input.focus();
    }
    if (!canWrite && state.phase !== "arguing") {
      input.value = "";
      wordCount.textContent = "";
    }
  }

  function tick() {
    if (!latestState || !latestState.deadline || !latestState.duration_seconds) return;
    if (latestState.phase !== "arguing" && latestState.phase !== "reflecting") return;
    const remaining = (new Date(latestState.deadline).getTime() - Date.now()) / 1000;
    const fraction = Math.min(1, Math.max(0, remaining / latestState.duration_seconds));
    timerEl.textContent = formatClock(remaining);
    barFill.style.transform = `scaleX(${fraction})`;
  }
  setInterval(tick, 250);

  function sendArgument() {
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "submit", text }));
    input.value = "";
    wordCount.textContent = "";
    sendBtn.disabled = true;
  }

  input.addEventListener("input", () => {
    wordCount.textContent = input.value.trim() ? `${wordsIn(input.value)} words` : "";
  });
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      sendArgument();
    }
  });
  sendBtn.addEventListener("click", sendArgument);

  leaveBtn.addEventListener("click", () => {
    if (!confirm("End this debate for both of you?")) return;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "leave" }));
    }
  });

  function connect() {
    const path = `/ws/debate/${sessionId}?user_id=${encodeURIComponent(userId)}&name=${encodeURIComponent(userName)}`;
    ws = new WebSocket(SD.wsUrl(path));

    ws.onopen = () => { reconnectAttempts = 0; };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "state") {
        applyState(message);
      } else if (message.type === "error") {
        label.textContent = message.detail || "Something went wrong.";
      }
    };

    ws.onclose = () => {
      if (latestState && latestState.phase === "ended") return;
      reconnectAttempts += 1;
      if (reconnectAttempts <= 8) {
        label.textContent = "Reconnecting…";
        setTimeout(connect, Math.min(5000, 1000 * reconnectAttempts));
      } else {
        label.textContent = "Connection lost. Refresh the page to try again.";
      }
    };
  }

  connect();
})();
