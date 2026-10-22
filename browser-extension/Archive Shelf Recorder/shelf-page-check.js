(() => {
  const box = document.getElementById("page-check");
  const START_PORT = 8765;
  const PORT_COUNT = 30;

  function showMessage(message, error = false) {
    box.textContent = message;
    box.style.color = error ? "#a12a36" : "";
  }

  async function findShelfServer() {
    const requests = Array.from({ length: PORT_COUNT }, async (_, offset) => {
      const base = "http://127.0.0.1:" + (START_PORT + offset);
      const response = await fetch(base + "/api/state", { cache: "no-store" });
      if (!response.ok) throw new Error("Not Archive Shelf");
      const state = await response.json();
      if (state.application !== "archive-shelf" || !Array.isArray(state.items)) {
        throw new Error("Not Archive Shelf");
      }
      return base;
    });
    try { return await Promise.any(requests); }
    catch { return null; }
  }

  function addMatch(base, match) {
    const row = document.createElement("div");
    row.className = "page-check-match";
    const label = document.createElement("div");
    label.textContent = "Already archived: " + match.title + " — " + match.name +
      (match.folder ? " (" + match.folder + ")" : "");
    const link = document.createElement("a");
    const target = new URL(base + "/");
    if (match.folder) target.searchParams.set("folder", match.folder);
    target.searchParams.set("archive", match.id);
    const replay = new URLSearchParams({ url: match.url });
    if (match.ts) replay.set("ts", match.ts);
    target.searchParams.set("replay", replay.toString());
    link.href = target.href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "Open archived page";
    row.append(label, link);
    box.append(row);
  }

  async function checkCurrentPage() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const pageUrl = tabs[0] && tabs[0].url;
    if (!pageUrl || !/^https?:\/\//i.test(pageUrl)) {
      showMessage("Open a regular webpage to check whether it is already archived.");
      return;
    }

    showMessage("Checking whether this page is already in your Shelf…");
    const base = await findShelfServer();
    if (!base) {
      showMessage("Start Archive Shelf to check your saved pages.");
      return;
    }

    const endpoint = base + "/api/find-page?url=" + encodeURIComponent(pageUrl);
    let response;
    try {
      response = await fetch(endpoint, { cache: "no-store" });
    } catch {
      showMessage("Could not check saved pages. Refresh the Shelf connection and try again.", true);
      return;
    }
    if (response.status === 404) {
      showMessage("Restart Archive Shelf to enable the saved-page check.", true);
      return;
    }
    let result;
    try { result = await response.json(); }
    catch {
      showMessage("Could not read the saved-page check response. Restart Archive Shelf.", true);
      return;
    }
    if (!response.ok) {
      showMessage(result.error || "Could not check saved pages.", true);
      return;
    }
    box.replaceChildren();
    if (!result.matches.length) {
      showMessage("This page is not in your saved WACZ archives.");
      return;
    }
    const heading = document.createElement("div");
    heading.textContent = "This page is already archived:";
    box.append(heading);
    for (const match of result.matches) addMatch(base, match);
  }

  checkCurrentPage().catch(() => showMessage("Could not check saved pages.", true));

  // MV3 service workers can disconnect an idle popup port. Keep it active and
  // reconnect while the popup is open so the recorder status stays available.
  setInterval(() => {
    try {
      if (recorderPort) {
        recorderPort.postMessage({ type: "keepAlive" });
      } else if (!isSaving && !isImporting && !isStarting && typeof connectRecorder === "function") {
        setStatus("Reconnecting to the recorder…");
        connectRecorder().then(() => {
          if (recorderPort) setStatus("Recorder connection restored.");
        }).catch(() => {});
      }
    } catch {
      recorderPort = null;
    }
  }, 15000);
})();