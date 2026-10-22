const START_PORT = 8765;
const PORT_COUNT = 30;
const folderSelect = document.getElementById("folder");
const archiveInput = document.getElementById("archive");
const saveButton = document.getElementById("save");
const statusBox = document.getElementById("status");
let archiveShelfBase = null;

function setStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.toggle("error", isError);
}

function validState(state) {
  return state && state.application === "archive-shelf" && state.protocol === 1 && Array.isArray(state.groups) && Array.isArray(state.items);
}

async function findArchiveShelf() {
  const controllers = [];
  const probes = Array.from({ length: PORT_COUNT }, (_, index) => {
    const port = START_PORT + index;
    const controller = new AbortController();
    controllers.push(controller);
    const timer = setTimeout(() => controller.abort(), 800);
    return fetch(`http://127.0.0.1:${port}/api/state`, {
      cache: "no-store",
      signal: controller.signal
    }).then(async response => {
      if (!response.ok) throw new Error("No organizer on this port");
      const state = await response.json();
      if (!validState(state)) throw new Error("Not Archive Shelf");
      return { base: `http://127.0.0.1:${port}`, state };
    }).finally(() => clearTimeout(timer));
  });

  try {
    const result = await Promise.any(probes);
    controllers.forEach(controller => controller.abort());
    return result;
  } catch {
    controllers.forEach(controller => controller.abort());
    return null;
  }
}

function addFolderOption(label, value) {
  const option = document.createElement("option");
  option.textContent = label;
  option.value = value;
  folderSelect.append(option);
}

function showFolders(state) {
  const previous = folderSelect.value;
  folderSelect.replaceChildren();
  addFolderOption("All folders (top level)", "");
  const folders = new Set(state.groups);
  for (const item of state.items) {
    if (item.folder) folders.add(item.folder);
  }
  [...folders].sort((a, b) => a.localeCompare(b)).forEach(path => addFolderOption(path, path));
  if ([...folderSelect.options].some(option => option.value === previous)) folderSelect.value = previous;
  folderSelect.disabled = false;
}

async function refreshFolders() {
  setStatus("Looking for Archive Shelf…");
  saveButton.disabled = true;
  const result = await findArchiveShelf();
  if (!result) {
    archiveShelfBase = null;
    folderSelect.disabled = true;
    setStatus("Start Archive Shelf, then refresh the folder list.", true);
    return;
  }
  archiveShelfBase = result.base;
  showFolders(result.state);
  setStatus("Choose a folder and select your WACZ file.");
  updateSaveButton();
}

function updateSaveButton() {
  saveButton.disabled = !archiveShelfBase || !archiveInput.files.length;
}

async function saveArchive() {
  const file = archiveInput.files[0];
  if (!file || !archiveShelfBase) return;
  saveButton.disabled = true;
  setStatus(`Adding ${file.name}…`);
  const query = new URLSearchParams({ name: file.name, folder: folderSelect.value });
  try {
    const response = await fetch(`${archiveShelfBase}/api/import?${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Archive Shelf could not add that file.");
    const destination = folderSelect.value || "All folders";
    setStatus(`${file.name} added to ${destination}.`);
    archiveInput.value = "";
  } catch (error) {
    setStatus(error.message || "Could not connect to Archive Shelf. Try refreshing the folder list.", true);
  } finally {
    updateSaveButton();
  }
}

document.getElementById("refresh").addEventListener("click", refreshFolders);
archiveInput.addEventListener("change", updateSaveButton);
saveButton.addEventListener("click", saveArchive);
refreshFolders();
