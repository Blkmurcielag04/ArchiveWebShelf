(() => {
  const message = document.getElementById("message");
  const replay = document.getElementById("replay");
  const query = new URLSearchParams(location.search);
  const id = query.get("id") || "";
  const name = query.get("name") || "";
  const requestedParentOrigin = query.get("parentOrigin") || "";

  function allowedParentOrigin(value) {
    try {
      const url = new URL(value);
      const samePort = url.port === location.port;
      const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
      return url.origin === value && ["http:", "https:"].includes(url.protocol) && samePort && localHost
        ? url.origin
        : "";
    } catch { return ""; }
  }

  const parentOrigin = allowedParentOrigin(requestedParentOrigin);
  const initialReplayState = query.get("replay") || location.hash.slice(1);
  if (initialReplayState && !location.hash) history.replaceState(history.state, "", `#${initialReplayState}`);

  if (!/^[a-f0-9]{32}$/.test(id) || !name || name.includes("/") || name.includes("\\")) {
    replay.remove();
    message.hidden = false;
    message.textContent = "Archive Shelf could not find that archive. Return to the folder and open it again.";
    return;
  }

  replay.setAttribute("title", name);
  replay.setAttribute("source", `${location.origin}/library/${encodeURIComponent(id)}/${encodeURIComponent(name)}`);
  replay.setAttribute("deepLink", "");

  let lastReplayState = cleanState(location.hash.slice(1));
  function cleanState(value) {
    if (typeof value !== "string" || value.length > 12000) return "";
    const incoming = new URLSearchParams(value.startsWith("#") ? value.slice(1) : value);
    const result = new URLSearchParams();
    for (const key of ["url", "ts", "query", "view"]) if (incoming.has(key)) result.set(key, incoming.get(key) || "");
    return result.toString();
  }

  function tellShelf(state) {
    if (!parentOrigin) return;
    window.parent.postMessage({ type: "archivewebshelf-replay-state", id, state }, parentOrigin);
  }

  // The Shelf's Back/Forward controls live outside ReplayWeb.page. Forward
  // those actions to ReplayWeb's own toolbar so they use the history of the
  // archived site, rather than the organizer page's history.
  function navigateReplay(direction) {
    const replayAppFrame = replay.shadowRoot?.querySelector("iframe");
    const replayApp = replayAppFrame?.contentDocument?.querySelector("replay-app-main");
    const replayItem = replayApp?.shadowRoot?.querySelector("wr-item");
    const label = direction === "back" ? "Back" : "Forward";
    const control = replayItem?.shadowRoot?.querySelector(`a[aria-label="${label}"]`);
    if (!control) return false;
    control.click();
    return true;
  }

  window.addEventListener("message", event => {
    const data = event.data;
    if (event.source !== window.parent || event.origin !== parentOrigin ||
        !data || data.type !== "archivewebshelf-replay-navigation" || data.id !== id ||
        !["back", "forward"].includes(data.direction)) return;
    navigateReplay(data.direction);
  });

  replay.addEventListener("rwp-url-change", () => {
    const next = cleanState(location.hash.slice(1));
    if (next === lastReplayState) return;
    if (lastReplayState) {
      // ReplayWeb.page updates its own URL with replaceState. Preserve the prior
      // replay location before recording the new one so browser Back can return.
      history.replaceState(history.state, "", `#${lastReplayState}`);
      history.pushState(history.state, "", `#${next}`);
    } else {
      history.replaceState(history.state, "", next ? `#${next}` : location.pathname + location.search);
    }
    lastReplayState = next;
    tellShelf(next);
  });

  window.addEventListener("popstate", () => {
    lastReplayState = cleanState(location.hash.slice(1));
    tellShelf(lastReplayState);
  });

  if (lastReplayState) tellShelf(lastReplayState);
  replay.addEventListener("error", () => {
    message.hidden = false;
    message.textContent = "ReplayWeb.page could not open this archive. Check that the archive file is still in Archive Shelf, then try again.";
  });
})();
