import { BrowserRecorder } from "./browser-recorder";
import { Downloader } from "../sw/downloader";

import { CollectionLoader } from "@webrecorder/wabac/swlib";

import { listAllMsg } from "../utils";

import {
  getLocalOption,
  removeLocalOption,
  setLocalOption,
} from "../localstorage";

// ===========================================================================
self.recorders = {};
self.newRecId = null;
self.shelfTargets = {};

// @ts-expect-error - TS7034 - Variable 'newRecUrl' implicitly has type 'any' in some locations where its type cannot be determined.
let newRecUrl = null;
// @ts-expect-error - TS7034 - Variable 'newRecCollId' implicitly has type 'any' in some locations where its type cannot be determined.
let newRecCollId = null;

// @ts-expect-error - TS7034 - Variable 'defaultCollId' implicitly has type 'any' in some locations where its type cannot be determined.
let defaultCollId = null;
let autorun = false;

const openWinMap = new Map();

const collLoader = new CollectionLoader();

const disabledCSPTabs = new Set();
// ===========================================================================

function main() {
  chrome.action.setBadgeBackgroundColor({ color: "#4d7c0f" });

  chrome.contextMenus.create({
    id: "toggle-rec",
    title: "Start Recording",
    contexts: ["browser_action"],
  });
  chrome.contextMenus.create({
    id: "view-rec",
    title: "View Web Archives",
    contexts: ["all"],
  });
}

// @ts-expect-error - TS7006 - Parameter 'port' implicitly has an 'any' type.
chrome.runtime.onConnect.addListener((port) => {
  switch (port.name) {
    case "popup-port":
      popupHandler(port);
      break;
  }
});

// @ts-expect-error - TS7006 - Parameter 'port' implicitly has an 'any' type.
function popupHandler(port) {
  if (
    !port.sender ||
    (port.sender.url !== chrome.runtime.getURL("popup.html") &&
      port.sender.url !== chrome.runtime.getURL("shelf-popup.html"))
  ) {
    return;
  }

  let tabId: number | null = null;

  // @ts-expect-error - TS7006 - Parameter 'message' implicitly has an 'any' type.
  port.onMessage.addListener(async (message) => {
    switch (message.type) {
      case "startUpdates":
        if (!Number.isInteger(message.tabId)) break;
        tabId = Number(message.tabId);
        if (self.recorders[tabId]) {
          const recorder = self.recorders[tabId] as BrowserRecorder & { port?: TODOFixMe };
          recorder.port = port;
          recorder.doUpdateStatus();
        }
        port.postMessage(await listAllMsg(collLoader));
        break;

      case "startRecording": {
        const { collId, autorun } = message;
        if (tabId === null) break;
        if (message.shelf) {
          self.shelfTargets[collId] = message.shelf;
          await chrome.storage.local.set({ [`archiveShelfTarget:${collId}`]: message.shelf });
        }
        const err = await startRecorder(tabId, { collId, port, autorun }, message.url);
        if (err) {
          port.postMessage({
            type: "status",
            recording: false,
            collId,
            failureMsg: err instanceof Error ? err.message : String(err),
          });
        }
        break;
      }

      case "stopShelfSession":
        saveShelfCollection(message.collId, port);
        break;

      case "stopRecording":
        if (tabId !== null) stopRecorder(tabId);
        break;

      case "toggleBehaviors":
        if (tabId !== null) toggleBehaviors(tabId);
        break;

      case "newColl": {
        const { name } = await collLoader.initNewColl({ title: message.title });
        defaultCollId = name;
        port.postMessage(await listAllMsg(collLoader, { defaultCollId }));
        await setLocalOption("defaultCollId", defaultCollId);
        break;
      }
    }
  });

  port.onDisconnect.addListener(() => {
    const disconnectedTabId = tabId;
    if (disconnectedTabId !== null && self.recorders[disconnectedTabId]) {
      const recorder = self.recorders[disconnectedTabId] as BrowserRecorder & { port?: TODOFixMe };
      recorder.port = null;
    }
  });
}

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tab' implicitly has an 'any' type. | TS7006 - Parameter 'reason' implicitly has an 'any' type.
chrome.debugger.onDetach.addListener((tab, reason) => {
  // target closed, delete recorder as this tab will not be used again
  if (reason === "target_closed") {
    delete self.recorders[tab.id];
  }
});

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tab' implicitly has an 'any' type.
chrome.tabs.onCreated.addListener((tab) => {
  if (!tab.id) {
    return;
  }

  let openUrl = null;
  let start = false;
  let waitForTabUpdate = true;
  let collId = null;

  // start recording from extension in new tab use case
  // @ts-expect-error - TS7005 - Variable 'newRecUrl' implicitly has an 'any' type.
  if (newRecUrl && tab.pendingUrl === "about:blank") {
    start = true;
    openUrl = newRecUrl;
    // @ts-expect-error - TS7005 - Variable 'newRecCollId' implicitly has an 'any' type. | TS7005 - Variable 'defaultCollId' implicitly has an 'any' type.
    collId = newRecCollId || defaultCollId;
    newRecUrl = null;
    newRecCollId = null;
  } else if (
    tab.openerTabId &&
    (!tab.pendingUrl || isValidUrl(tab.pendingUrl)) &&
    // @ts-expect-error - TS2339 - Property 'running' does not exist on type 'BrowserRecorder'.
    self.recorders[tab.openerTabId]?.running
  ) {
    // @ts-expect-error - TS2339 - Property 'collId' does not exist on type 'BrowserRecorder'.
    collId = self.recorders[tab.openerTabId].collId;

    start = true;
    if (tab.pendingUrl) {
      waitForTabUpdate = false;
      openUrl = tab.pendingUrl;
    }
  }

  if (start) {
    if (openUrl && !isValidUrl(openUrl)) {
      return;
    }
    startRecorder(
      tab.id,
      { waitForTabUpdate, collId, openUrl, autorun },
      openUrl,
    );
  }
});

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type. | TS7006 - Parameter 'changeInfo' implicitly has an 'any' type.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (tabId && self.recorders[tabId]) {
    const recorder = self.recorders[tabId];
    if (changeInfo.url) {
      // @ts-expect-error - TS2339 - Property 'failureMsg' does not exist on type 'BrowserRecorder'.
      recorder.failureMsg = null;
    }

    if (changeInfo.url && openWinMap.has(changeInfo.url)) {
      openWinMap.delete(changeInfo.url);
    }

    // @ts-expect-error - TS2339 - Property 'waitForTabUpdate' does not exist on type 'BrowserRecorder'.
    if (recorder.waitForTabUpdate) {
      if (isValidUrl(changeInfo.url)) {
        recorder.attach();
      } else {
        // @ts-expect-error - TS2339 - Property 'waitForTabUpdate' does not exist on type 'BrowserRecorder'.
        recorder.waitForTabUpdate = false;
        delete self.recorders[tabId];
        return;
      }
    }
  } else if (changeInfo.url && openWinMap.has(changeInfo.url)) {
    const collId = openWinMap.get(changeInfo.url);
    openWinMap.delete(changeInfo.url);
    if (!tabId || !isValidUrl(changeInfo.url)) {
      return;
    }
    startRecorder(tabId, { collId, autorun }, changeInfo.url);
  }
});

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type.
chrome.tabs.onRemoved.addListener((tabId) => {
  delete self.recorders[tabId];
  removeLocalOption(`${tabId}-collId`);
});

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'info' implicitly has an 'any' type. | TS7006 - Parameter 'tab' implicitly has an 'any' type.
chrome.contextMenus.onClicked.addListener((info, tab) => {
  switch (info.menuItemId) {
    case "view-rec":
      chrome.tabs.create({ url: chrome.runtime.getURL("index.html") });
      break;

    case "toggle-rec":
      if (!isRecording(tab.id)) {
        if (isValidUrl(tab.url)) {
          startRecorder(tab.id);
        }
      } else {
        stopRecorder(tab.id);
      }
      break;
  }
});

// ===========================================================================
async function startRecorder(tabId: number, opts: TODOFixMe = {}, openUrl?: string) {
  if (openUrl && !opts.openUrl) opts.openUrl = openUrl;

  const previous = self.recorders[tabId] as (BrowserRecorder & {
    collId?: string;
    running?: boolean;
    isAttached?: boolean;
  }) | undefined;
  if (previous && opts.collId && previous.collId !== opts.collId) {
    // A new capture always gets a fresh recorder. Reusing one can retain the
    // previous session's URL and collection, causing the wrong page to be
    // recorded after a failed or unfinished session.
    if (previous.running || previous.isAttached) await previous.detach();
    delete self.recorders[tabId];
  }

  if (!self.recorders[tabId]) {
    opts.collLoader = collLoader;
    opts.openWinMap = openWinMap;
    self.recorders[tabId] = new BrowserRecorder({ tabId }, opts);
  } else {
    self.recorders[tabId].setAutoRunBehavior(opts.autorun);
    (self.recorders[tabId] as BrowserRecorder & { port?: TODOFixMe }).port = opts.port;
  }

  let err = null;
  const { waitForTabUpdate } = opts;

  // @ts-expect-error - TS2339 - Property 'running' does not exist on type 'BrowserRecorder'.
  if (!waitForTabUpdate && !self.recorders[tabId].running) {
    try {
      self.recorders[tabId].setCollId(opts.collId);
      await self.recorders[tabId].attach();
    } catch (e) {
      console.warn(e);
      err = e;
    }
    return err;
  }
}
// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type.
function stopRecorder(tabId) {
  if (self.recorders[tabId]) {
    self.recorders[tabId].detach();
    return true;
  }

  return false;
}

// Build a WACZ from the recorder's saved session, then stream it into the local Shelf.
async function saveShelfCollection(collId: string, port: TODOFixMe) {
  let target = self.shelfTargets[collId];
  if (!target) {
    const stored = await chrome.storage.local.get(`archiveShelfTarget:${collId}`);
    target = stored[`archiveShelfTarget:${collId}`];
  }
  if (!target) {
    return reportShelfResult(port, { ok: false, error: "This recording has no Archive Shelf destination." });
  }

  try {
    const recorders = (Object.values(self.recorders) as unknown as Array<{
      collId: string;
      running: boolean;
      detach: () => Promise<void>;
    }>).filter(
      (rec) => rec.collId === collId && rec.running,
    );
    // Recorder tabs share a debugger session; detach them one at a time so the
    // final recorder can fully detach the browser debugger.
    for (const recorder of recorders) await recorder.detach();

    const coll = await collLoader.loadColl(collId);
    if (!coll) throw new Error("The recording session could not be found.");

    const safeBaseName = String(target.title || "Archived Site")
      .normalize("NFKC")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")
      .replace(/\s+/g, " ")
      .replace(/[. ]+$/g, "")
      .slice(0, 110) || "Archived Site";
    const filename = `${safeBaseName}.wacz`;
    const download = new Downloader({
      coll,
      format: "wacz",
      filename,
      softwareString: "Archive Shelf recording, using Webrecorder ArchiveWeb.page",
    });
    reportShelfProgress(port, "Building the WACZ file…");
    let response: Awaited<ReturnType<typeof download.download>>;
    try {
      response = await download.download();
    } catch (error) {
      throw new Error("WACZ creation failed: " + (error instanceof Error ? error.message : String(error)));
    }
    if (!(response instanceof Response) || !response.body) {
      throw new Error("WACZ creation failed: ArchiveWeb.page returned an empty file.");
    }

    let uploadBody: Blob;
    reportShelfProgress(port, "Preparing the WACZ upload…");
    try {
      uploadBody = await response.blob();
    } catch (error) {
      throw new Error("WACZ upload preparation failed: " + (error instanceof Error ? error.message : String(error)));
    }
    if (!uploadBody.size) {
      throw new Error("WACZ creation failed: ArchiveWeb.page returned an empty file.");
    }

    const destination = new URL("/api/import", target.baseUrl);
    destination.searchParams.set("name", filename);
    destination.searchParams.set("folder", target.folder || "");
    const uploadOptions: RequestInit = {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: uploadBody,
    };
    reportShelfProgress(port, "Uploading the WACZ to Archive Shelf (" + target.baseUrl + ")…");
    let upload: Response;
    try {
      upload = await fetch(destination.href, uploadOptions);
    } catch (error) {
      const details = error instanceof Error ? error.message : String(error);
      throw new Error("Upload to Archive Shelf failed at " + target.baseUrl + ". Keep Archive Shelf running and check Brave's localhost access for the recorder. Browser detail: " + details);
    }
    let result: { error?: string } = {};
    try {
      result = await upload.json();
    } catch (_error) {
      // The organizer error below is enough if it did not return JSON.
    }
    if (!upload.ok) throw new Error(result.error || `Archive Shelf returned ${upload.status}.`);

    const saved = {
      ok: true,
      name: filename,
      folder: target.folder || "",
      savedAt: Date.now(),
    };
    await chrome.storage.local.set({ archiveShelfLastSave: saved });
    await chrome.storage.local.remove(`archiveShelfTarget:${collId}`);
    chrome.action.setBadgeText({ text: "✓" });
    chrome.action.setBadgeBackgroundColor({ color: "#4d7c0f" });
    delete self.shelfTargets[collId];
    reportShelfResult(port, saved);
  } catch (error) {
    const failure = {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      savedAt: Date.now(),
    };
    await chrome.storage.local.set({ archiveShelfLastSave: failure });
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#a12a36" });
    reportShelfResult(port, failure);
  }
}

function reportShelfProgress(port: TODOFixMe, message: string) {
  try {
    port.postMessage({ type: "shelfExportProgress", message });
  } catch (_error) {
    // The popup can close while a large archive is being saved.
  }
}

function reportShelfResult(port: TODOFixMe, result: { ok: boolean; [key: string]: unknown }) {
  try {
    port.postMessage({ type: "shelfExportResult", ...result });
  } catch (_error) {
    // The popup can close while a large archive is being saved.
  }
}
// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type.
function toggleBehaviors(tabId) {
  if (self.recorders[tabId]) {
    self.recorders[tabId].toggleBehaviors();
    return true;
  }

  return false;
}

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type.
function isRecording(tabId) {
  // @ts-expect-error - TS2339 - Property 'running' does not exist on type 'BrowserRecorder'.
  return self.recorders[tabId]?.running;
}

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'url' implicitly has an 'any' type.
function isValidUrl(url) {
  return (
    url &&
    (url === "about:blank" ||
      url.startsWith("https:") ||
      url.startsWith("http:"))
  );
}

// ===========================================================================
chrome.runtime.onMessage.addListener(
  // @ts-expect-error - TS7006 - Parameters 'message' and 'sender' implicitly have an 'any' type.
  async (message, sender) => {
    if (sender?.id !== chrome.runtime.id || !message || typeof message !== "object") {
      return;
    }

    let senderOrigin = "";
    try {
      senderOrigin = new URL(sender.url).origin;
    } catch {
      return;
    }
    if (senderOrigin !== new URL(chrome.runtime.getURL("/")).origin) {
      return;
    }

    switch (message.msg) {
      case "startNew":
        if (
          typeof message.url !== "string" ||
          !/^https?:\/\//i.test(message.url) ||
          !isValidUrl(message.url) ||
          typeof message.collId !== "string" ||
          !message.collId ||
          message.collId.length > 200
        ) {
          return;
        }
        newRecUrl = message.url;
        newRecCollId = message.collId;
        autorun = Boolean(message.autorun);
        defaultCollId = await getLocalOption("defaultCollId");
        chrome.tabs.create({ url: "about:blank" });
        break;

      case "disableCSP":
        if (!Number.isInteger(sender.tab?.id) || message.tabId !== sender.tab.id) {
          return;
        }
        void disableCSPForTab(sender.tab.id);
        break;
    }
  },
);

// ===========================================================================
// @ts-expect-error - TS7006 - Parameter 'tabId' implicitly has an 'any' type.
async function disableCSPForTab(tabId) {
  if (disabledCSPTabs.has(tabId)) {
    return;
  }

  await new Promise((resolve) => {
    chrome.debugger.attach({ tabId }, "1.3", () => {
      // @ts-expect-error - TS2794 - Expected 1 arguments, but got 0. Did you forget to include 'void' in your type argument to 'Promise'?
      resolve();
    });
  });

  await new Promise((resolve) => {
    chrome.debugger.sendCommand(
      { tabId },
      "Page.setBypassCSP",
      { enabled: true },
      // @ts-expect-error - TS7006 - Parameter 'resp' implicitly has an 'any' type.
      (resp) => resolve(resp),
    );
  });

  disabledCSPTabs.add(tabId);

  // hacky: don't detach if any recorders are running, otherwise will disconnect
  for (const rec of Object.values(self.recorders)) {
    // @ts-expect-error - TS2339 - Property 'running' does not exist on type 'BrowserRecorder'.
    if (rec.running) {
      return;
    }
  }

  await new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      // @ts-expect-error - TS2794 - Expected 1 arguments, but got 0. Did you forget to include 'void' in your type argument to 'Promise'?
      resolve();
    });
  });
}

// ===========================================================================
chrome.runtime.onInstalled.addListener(main);

if (self.importScripts) {
  self.importScripts("sw.js");
}
