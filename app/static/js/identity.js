/* Anonymous, account-free identity. Each browser keeps its own id and a
   friendly generated name in localStorage - see app/identity.py for where
   the name suggestions come from. */
window.SD = (function () {
  function getId() {
    let id = localStorage.getItem("sd_user_id");
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
      localStorage.setItem("sd_user_id", id);
    }
    return id;
  }

  function getName() {
    return localStorage.getItem("sd_user_name") || "";
  }

  async function ensureIdentity() {
    const id = getId();
    let name = getName();
    if (!name) {
      try {
        const res = await fetch("/api/identity/name");
        const data = await res.json();
        name = data.suggested_name;
      } catch (e) {
        name = "Anonymous Debater";
      }
      localStorage.setItem("sd_user_name", name);
    }
    return { id, name };
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function wsUrl(path) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}${path}`;
  }

  return { getId, getName, ensureIdentity, escapeHtml, wsUrl };
})();
