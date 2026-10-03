(async function () {
  const { id: userId } = await SD.ensureIdentity();
  const page = document.querySelector(".waiting-page");
  const topicId = page.dataset.topicId;
  const titleEl = document.getElementById("waiting-topic-title");
  const headingEl = document.getElementById("waiting-title");
  const cancelBtn = document.getElementById("cancel-btn");

  async function loadTopic() {
    try {
      const res = await fetch(`/api/topics/${topicId}?viewer_id=${encodeURIComponent(userId)}`);
      if (!res.ok) {
        titleEl.textContent = "This topic is no longer available.";
        cancelBtn.hidden = true;
        return;
      }
      const topic = await res.json();
      titleEl.textContent = `"${topic.title}"`;
    } catch (e) {
      titleEl.textContent = "";
    }
  }

  cancelBtn.addEventListener("click", async () => {
    cancelBtn.disabled = true;
    try {
      await fetch(`/api/topics/${topicId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
    } finally {
      location.href = "/";
    }
  });

  function connect() {
    const ws = new WebSocket(SD.wsUrl(`/ws/waiting/${topicId}?user_id=${encodeURIComponent(userId)}`));
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "matched") {
        headingEl.textContent = "Found someone. Taking you in…";
        cancelBtn.hidden = true;
        location.href = `/debate/${message.session_id}`;
      } else if (message.type === "cancelled") {
        headingEl.textContent = "This topic was withdrawn.";
        cancelBtn.hidden = true;
      }
    };
    ws.onclose = () => {
      // Quiet retry - a dropped connection shouldn't strand someone waiting.
      setTimeout(connect, 2000);
    };
  }

  loadTopic();
  connect();
})();
