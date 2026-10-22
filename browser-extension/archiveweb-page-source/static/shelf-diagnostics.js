(() => {
  const entries = [];
  const limit = 100;
  const add = (event, details = {}) => {
    entries.push({ time: new Date().toISOString(), event, ...details });
    if (entries.length > limit) entries.shift();
  };

  const status = document.getElementById("status");
  const record = document.getElementById("record");
  const folder = document.getElementById("selected-folder");
  document.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    const label = target.id === "record" ? record.textContent.trim() : target.textContent.trim();
    add("button", { label, folder: folder?.textContent || "" });
  }, true);

  if (status) {
    new MutationObserver(() => add("status", {
      message: status.textContent.trim(),
      error: status.classList.contains("error"),
    })).observe(status, { childList: true, characterData: true, subtree: true, attributes: true });
  }

  window.addEventListener("error", (event) => add("window-error", { message: event.message }));
  window.addEventListener("unhandledrejection", (event) => add("unhandled-rejection", {
    message: String(event.reason?.message || event.reason || "Unknown rejection"),
  }));

  document.getElementById("copy-diagnostics")?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    const report = {
      app: "ArchiveWebShelf Recorder",
      extensionVersion: chrome.runtime.getManifest().version,
      browser: navigator.userAgent,
      selectedFolder: folder?.textContent || "",
      currentStatus: status?.textContent.trim() || "",
      events: entries,
    };
    try {
      navigator.clipboard.writeText(JSON.stringify(report, null, 2)).then(() => {
        button.textContent = "Diagnostics copied";
        setTimeout(() => { button.textContent = "Copy diagnostics"; }, 1800);
      }).catch((error) => {
        add("copy-error", { message: String(error?.message || error) });
        button.textContent = "Copy failed; clipboard unavailable";
      });
    } catch (error) {
      button.textContent = "Copy failed; check extension permissions";
      add("copy-error", { message: String(error?.message || error) });
    }
  });

  add("popup-opened");
})();
