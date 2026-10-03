(async function () {
  const { id: userId, name: userName } = await SD.ensureIdentity();

  const openBtn = document.getElementById("open-composer-btn");
  const cancelBtn = document.getElementById("cancel-composer-btn");
  const composer = document.getElementById("composer");
  const form = document.getElementById("composer-form");
  const list = document.getElementById("topics-list");

  openBtn.addEventListener("click", () => {
    composer.hidden = false;
    document.getElementById("topic-title").focus();
  });
  cancelBtn.addEventListener("click", () => {
    composer.hidden = true;
    form.reset();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = document.getElementById("topic-title").value.trim();
    const description = document.getElementById("topic-description").value.trim();
    if (!title) return;

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      const res = await fetch("/api/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, user_id: userId, user_name: userName }),
      });
      if (!res.ok) throw new Error("Could not post that topic.");
      const topic = await res.json();
      location.href = `/waiting/${topic.id}`;
    } catch (err) {
      submitBtn.disabled = false;
      alert(err.message || "Something went wrong posting that topic.");
    }
  });

  function renderTopics(topics) {
    if (!topics.length) {
      list.innerHTML =
        '<p class="empty-state">No one has opened a topic yet. Be the first — pick something you have a real, unresolved opinion about.</p>';
      return;
    }
    list.innerHTML = topics
      .map((t) => {
        const title = SD.escapeHtml(t.title);
        const byline = t.is_mine
          ? "You opened this — waiting for someone to join"
          : `Opened by ${SD.escapeHtml(t.creator_name)}`;
        const action = t.is_mine
          ? `<a class="btn btn-ghost" href="/waiting/${t.id}">Go to waiting room</a>`
          : `<button class="btn btn-primary" data-join="${t.id}">Join this topic</button>`;
        return `<div class="topic-card">
                  <div>
                    <div class="topic-card-title">${title}</div>
                    <div class="topic-card-byline">${byline}</div>
                  </div>
                  ${action}
                </div>`;
      })
      .join("");

    list.querySelectorAll("[data-join]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        const topicId = btn.getAttribute("data-join");
        try {
          const res = await fetch(`/api/topics/${topicId}/join`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId, user_name: userName }),
          });
          if (!res.ok) {
            const detail = (await res.json()).detail || "That topic is no longer available.";
            throw new Error(detail);
          }
          const data = await res.json();
          location.href = `/debate/${data.session_id}`;
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
          loadTopics();
        }
      });
    });
  }

  async function loadTopics() {
    try {
      const res = await fetch(`/api/topics?viewer_id=${encodeURIComponent(userId)}`);
      const topics = await res.json();
      renderTopics(topics);
    } catch (err) {
      list.innerHTML = '<p class="empty-state">Couldn\'t load topics right now.</p>';
    }
  }

  loadTopics();
  setInterval(loadTopics, 4000);
})();
