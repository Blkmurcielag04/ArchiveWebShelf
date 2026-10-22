import "../globals";

import type { BrowserRecorder } from "./browser-recorder";

declare global {
  interface Window {
    recorders: Record<string, BrowserRecorder>;
    newRecId: string | null;
    shelfTargets: Record<string, { baseUrl: string; folder: string; title: string }>;
  }
  let chrome: TODOFixMe;
}
