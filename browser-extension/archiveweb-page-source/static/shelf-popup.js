const START_PORT = 8765;
const PORT_COUNT = 30;
const SHELF_DRIVE = "application/x-archive-shelf-item";

const selectedFolder = document.getElementById("selected-folder");
const chooseFolderButton = document.getElementById("choose-folder");
const recordButton = document.getElementById("record");
const statusBox = document.getElementById("status");
const folderDialog = document.getElementById("folder-dialog");
const folderList = document.getElementById("folder-list");
const folderCrumbs = document.getElementById("folder-crumbs");
const importInput = document.getElementById("import-file");
const importButton = document.getElementById("import-archive");

let shelfBase = null;
let shelfState = { groups: [], items: [] };
let destination = "";
let pickerPath = [];
let recorderPort = null;
let activeTab = null;
let isStarting = false;
let isRecording = false;
let isSaving = false;
let isImporting = false;
let currentCollectionId = "";
let pendingCollection = null;
let startTimer = null;

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function normalizePath(value) {
  return String(value || "").split(/[\\/]/).map((part) => part.trim()).filter(Boolean);
}

function pathText(parts) {
  return parts.join(" / ");
}

function isShelfState(state) {
  return state && state.application === "archive-shelf" && state.protocol === 1 && Array.isArray(state.groups) && Array.isArray(state.items);
}

async function findShelf() {
  const attempts = Array.from({ length: PORT_COUNT }, async (_, index) => {
    const port = START_PORT + index;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 700);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/state`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("No Shelf server on that port");
      const state = await response.json();
      if (!isShelfState(state)) throw new Error("Not Archive Shelf");
      return { base: `http://127.0.0.1:${port}`, state };
    } finally {
      clearTimeout(timer);
    }
  });
  try {
    return await Promise.any(attempts);
  } catch {
    return null;
  }
}

function allFolderPaths() {
  const paths = new Set(shelfState.groups.map((path) => pathText(normalizePath(path))));
  for (const item of shelfState.items) {
    const folder = pathText(normalizePath(item.folder));
    if (folder) paths.add(folder);
    const parts = normalizePath(folder);
    for (let index = 1; index < parts.length; index++) paths.add(pathText(parts.slice(0, index)));
  }
  return [...paths];
}

function directFolders(parent) {
  const parentText = pathText(parent);
  const children = new Set();
  for (const fullPath of allFolderPaths()) {
    const parts = normalizePath(fullPath);
    if (parts.length > parent.length && parent.every((part, index) => parts[index] === part)) {
      const child = parts[parent.length];
      if (child) children.add(child);
    }
  }
  for (const item of shelfState.items) {
    const parts = normalizePath(item.folder);
    if (parts.length > parent.length && parent.every((part, index) => parts[index] === part)) {
      const child = parts[parent.length];
      if (child) children.add(child);
    }
  }
  return [...children].sort((left, right) => left.localeCompare(right));
}

function setDestination(path) {
  destination = pathText(path);
  selectedFolder.textContent = destination || "All folders (top level)";
  folderDialog.hidden = true;
  updateButton();
}

function renderFolderPicker() {
  folderCrumbs.replaceChildren();
  const addCrumb = (label, path) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => {
      pickerPath = path;
      renderFolderPicker();
    });
    folderCrumbs.append(button);
  };
  addCrumb("All folders", []);
  pickerPath.forEach((part, index) => {
    folderCrumbs.append(document.createTextNode("›"));
    addCrumb(part, pickerPath.slice(0, index + 1));
  });

  folderList.replaceChildren();
  const children = directFolders(pickerPath);
  if (!children.length) {
    const empty = document.createElement("div");
    empty.className = "folder-empty";
    empty.textContent = pickerPath.length ? "No subfolders here." : "No folders yet. The archive will be saved at the top level.";
    folderList.append(empty);
  }
  for (const name of children) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "folder-option";
    const icon = document.createElement("span");
    icon.className = "folder-icon";
    icon.textContent = "📁";
    const label = document.createElement("span");
    label.className = "folder-name";
    label.textContent = name || "(unnamed folder)";
    const chevron = document.createElement("span");
    chevron.className = "folder-chevron";
    chevron.textContent = "›";
    button.append(icon, label, chevron);
    button.addEventListener("click", () => {
      pickerPath = [...pickerPath, name];
      renderFolderPicker();
    });
    folderList.append(button);
  }
}

function updateButton() {
  recordButton.disabled = !shelfBase || !activeTab || isStarting || isSaving || isImporting;
  recordButton.textContent = isSaving ? "Saving WACZ…" : isRecording ? "Stop and Save WACZ" : isStarting ? "Starting…" : "Start Archiving";
  chooseFolderButton.disabled = !shelfBase || isRecording || isSaving || isImporting;
  importButton.disabled = !shelfBase || !importInput.files.length || isRecording || isSaving || isImporting;
}

async function importExistingArchive() {
  const file = importInput.files[0];
  if (!file || !shelfBase) return;
  isImporting = true;
  updateButton();
  setStatus(`Importing ${file.name} into ${destination || "All folders"}…`);
  const query = new URLSearchParams({ name: file.name, folder: destination });
  try {
    const response = await fetch(`${shelfBase}/api/import?${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    let result = {};
    try { result = await response.json(); } catch (_error) { /* use a clear generic error below */ }
    if (!response.ok) throw new Error(result.error || `Archive Shelf returned ${response.status}.`);
    importInput.value = "";
    setStatus(`Imported ${file.name} into ${destination || "All folders (top level)"}.`);
    const refreshed = await findShelf();
    if (refreshed) shelfState = refreshed.state;
  } catch (error) {
    setStatus(error.message || "Could not import the archive into Archive Shelf.", true);
  } finally {
    isImporting = false;
    updateButton();
  }
}

async function refreshShelf() {
  setStatus("Looking for Archive Shelf…");
  recordButton.disabled = true;
  const result = await findShelf();
  if (!result) {
    shelfBase = null;
    chooseFolderButton.disabled = true;
    selectedFolder.textContent = "Archive Shelf is not running";
    setStatus("Start Archive Shelf, then refresh folders.", true);
    updateButton();
    return;
  }
  shelfBase = result.base;
  shelfState = result.state;
  setStatus("Choose where to save, then start archiving.");
  updateButton();
}

function listenForNextCollection() {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingCollection = null;
      reject(new Error("ArchiveWeb.page did not create the new recording session."));
    }, 10000);
    pendingCollection = (message) => {
      clearTimeout(timer);
      pendingCollection = null;
      if (!message.collId) reject(new Error("Could not identify the new recording session."));
      else resolve(message.collId);
    };
  });
}

function onRecorderMessage(message) {
  if (message.type === "shelfExportProgress") {
    setStatus(message.message || "Saving WACZ to Archive Shelf…");
    return;
  }
  if (message.type === "collections" && pendingCollection) {
    pendingCollection(message);
    return;
  }
  if (message.type === "status") {
    if (isSaving && !isStarting && !message.failureMsg) return;
    const wasStarting = isStarting;
    if (message.failureMsg || message.recording) {
      isStarting = false;
      clearTimeout(startTimer);
      startTimer = null;
    }
    if (message.collId) currentCollectionId = message.collId;
    isRecording = Boolean(message.recording);
    if (message.failureMsg) setStatus(`Recorder error: ${message.failureMsg}`, true);
    else if (isRecording) {
      const pages = message.numPages || 0;
      const pending = message.numPending || 0;
      setStatus(`Recording ${pages} page${pages === 1 ? "" : "s"}${pending ? ` · ${pending} items still loading` : ""}.`);
    } else if (wasStarting) setStatus("Waiting for the recorder to start…");
    updateButton();
  }
  if (message.type === "shelfExportResult") {
    isSaving = false;
    isRecording = false;
    if (message.ok) {
      setStatus(`Saved ${message.name} to ${message.folder || "All folders (top level)"}.`);
    } else {
      setStatus(message.error || "The recording could not be saved to Archive Shelf.", true);
    }
    updateButton();
  }
}

async function connectRecorder(forceReconnect = false) {
  if (forceReconnect && recorderPort) {
    const oldPort = recorderPort;
    recorderPort = null;
    oldPort.disconnect();
  }
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tabs[0] || null;
  if (!activeTab || !activeTab.id || !/^https?:/.test(activeTab.url || "")) {
    setStatus("Open a regular website tab before starting an archive.", true);
    updateButton();
    return;
  }
  const port = chrome.runtime.connect({ name: "popup-port" });
  recorderPort = port;
  port.onMessage.addListener(onRecorderMessage);
  port.onDisconnect.addListener(() => {
    if (recorderPort === port) {
      recorderPort = null;
      if (!isSaving) setStatus("Recorder connection closed. Try starting again to reconnect.", true);
      updateButton();
    }
  });
  try {
    port.postMessage({ type: "startUpdates", tabId: activeTab.id });
  } catch (error) {
    if (recorderPort === port) recorderPort = null;
    setStatus(error.message || "Could not connect to the recorder.", true);
  }
  updateButton();
}

async function startRecording() {
  if (!shelfBase) return;
  isSaving = true;
  isStarting = false;
  updateButton();
  setStatus("Preparing a new recording…");
  try {
    await connectRecorder(true);
    if (!recorderPort || !activeTab) throw new Error("Could not connect to the recorder. Try reopening the extension popup.");
    const tabTitle = activeTab.title || new URL(activeTab.url).hostname;
    const collIdPromise = listenForNextCollection();
    recorderPort.postMessage({ type: "newColl", title: tabTitle });
    currentCollectionId = await collIdPromise;
    recorderPort.postMessage({
      type: "startRecording",
      collId: currentCollectionId,
      url: activeTab.url,
      autorun: false,
      shelf: { baseUrl: shelfBase, folder: destination, title: tabTitle },
    });
    isSaving = false;
    isStarting = true;
    setStatus("Waiting for the recorder to start…");
    startTimer = setTimeout(() => {
      if (!isStarting) return;
      isStarting = false;
      setStatus("The recorder did not confirm that it started. Try again.", true);
      updateButton();
    }, 15000);
  } catch (error) {
    isSaving = false;
    isStarting = false;
    clearTimeout(startTimer);
    startTimer = null;
    setStatus(error.message || "Could not start the recorder.", true);
  }
  updateButton();
}

function stopAndSave() {
  if (!currentCollectionId) return;
  isRecording = false;
  isSaving = true;
  updateButton();
  setStatus("Finishing the recording, then saving its WACZ to Archive Shelf…");
  if (!recorderPort) {
    connectRecorder(true).then(() => {
      if (!recorderPort) throw new Error("Recorder connection could not be restored.");
      recorderPort.postMessage({ type: "stopShelfSession", collId: currentCollectionId });
    }).catch((error) => {
      isSaving = false;
      setStatus(error.message || "Could not reconnect to save the WACZ.", true);
      updateButton();
    });
    return;
  }
  try {
    recorderPort.postMessage({ type: "stopShelfSession", collId: currentCollectionId });
  } catch (error) {
    recorderPort = null;
    isSaving = false;
    setStatus(error.message || "Recorder connection closed before saving.", true);
    updateButton();
  }
}

chooseFolderButton.addEventListener("click", async () => {
  const result = await findShelf();
  if (!result) {
    setStatus("Start Archive Shelf, then refresh folders.", true);
    return;
  }
  shelfBase = result.base;
  shelfState = result.state;
  pickerPath = normalizePath(destination);
  folderDialog.hidden = false;
  renderFolderPicker();
});
document.getElementById("close-folders").addEventListener("click", () => { folderDialog.hidden = true; });
document.getElementById("use-folder").addEventListener("click", () => setDestination(pickerPath));
document.getElementById("refresh").addEventListener("click", refreshShelf);
recordButton.addEventListener("click", () => isRecording ? stopAndSave() : startRecording());
importInput.addEventListener("change", updateButton);
importButton.addEventListener("click", importExistingArchive);

refreshShelf().then(connectRecorder);
