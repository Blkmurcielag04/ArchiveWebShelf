# Archive Shelf 1.0.0

Archive Shelf is a local Windows organizer and viewer for WACZ web archives. It includes a small Python server, a bundled ReplayWeb.page reader, and a browser extension for recording and importing archives.

## Download and requirements

1. Click **Code > Download ZIP** on this repository.
2. Extract the entire ZIP to a folder on your computer.
3. Open the extracted folder to find **Start Archive Shelf.bat**.

You need Windows, Python, and Chrome or Brave to use the Recorder extension. The Windows launchers default to Python 3.13. The organizer uses Python's standard library; no additional Python packages are required.

The reader is included for local archive playback. Recording live websites and downloading updates require internet access. Node.js is only needed if you choose to rebuild the Recorder from source.

## Start Archive Shelf

1. Check the Python path using the [Python Path Guide](Archive%20Shelf%20Python%20Path%20Guide.pdf).
2. Double-click **Start Archive Shelf.bat**.
3. Keep the server window open while using the organizer.
4. Use the Archive Shelf page that opens in your browser.

Both Windows launchers look for Python at:

`%LOCALAPPDATA%\Programs\Python\Python313\python.exe`

If Python is installed elsewhere, edit the `PYTHON_EXE` line in **Start Archive Shelf.bat** and **Check ReplayWeb.page Updates.bat**. The path guide shows how.

To stop the server, press **Ctrl+C**. If Command Prompt asks whether to terminate the batch job, answer **N**, then choose **R** to restart or **C** to close the window.

## Install the Recorder extension

1. Start Archive Shelf and leave its server window open.
2. In Chrome, open `chrome://extensions`; in Brave, open `brave://extensions`.
3. Turn on **Developer mode**.
4. Choose **Load unpacked**.
5. Select `browser-extension\Archive Shelf Recorder` inside the extracted project folder.
6. Pin the ArchiveWebShelf extension button if you want easier access.

The optional import-only extension is in `browser-extension\Legacy WACZ Importer`. The combined Recorder already includes importing.

## Record or import archives

Open the page you want to save, click the extension button, and choose a Shelf folder. Click **Start Archiving**, then browse the pages and media you want to capture. Click **Stop and Save WACZ** and wait for the saved message.

Recording reloads the initial page. The Recorder captures content as you browse, scroll, and click while recording. It does not automatically explore controls or follow links. On interactive sites, open the panels, settings, and alternate views you want during the recording.

To import an existing WACZ, expand **Import an existing WACZ file** in the extension popup.

## Organize and view archives

Create folders, add archives with **Choose archive files**, or drag archive files from File Explorer into the organizer. Click an archive to open it.

While viewing a WACZ, use **Manage saved pages** to remove unwanted captures from Archive Shelf's saved copy. The original imported WACZ remains unchanged.

Your collection is stored in `library` and `archive-shelf-data.json`. Back up both together. This public starter copy includes no personal archives. The app creates its storage as needed, and the included `.gitignore` excludes collection files from public commits.

## Known issues and future improvements

- **Back navigation:** returning to a Shelf folder or moving between views inside a replay can behave unexpectedly.
- **Interactive content:** settings, alternate instrument views, diagrams, and samples may be missing unless loaded while recording. More automatic capture is planned for a future version.

See [BUGS.txt](BUGS.txt) for details and workarounds. These limitations are still present in 1.0.0.

## If something is not working

- **Python was not found:** follow the Python Path Guide and check both launchers' Python paths.
- **The extension cannot find Archive Shelf:** start the server and keep its window open, then reopen the popup and refresh its folders.
- **The popup asks for a server restart:** finish any recording save first, rerun the launcher, and choose **Y** when it offers to restart the existing server.
- **A recording missed content:** try loading the relevant controls or media while recording. Some site features may still be incompatible with archiving.

If the problem continues, open the repository's [Issues tab](https://github.com/Blkmurcielag04/ArchiveWebShelf/issues) and choose **Bug report**. Include your version, browser, steps, and error message. Review screenshots and copied diagnostics for private information before posting.

## Local connection and privacy

The app opens at http://localhost:8765/ or a nearby port if 8765 is busy. The server listens only on this computer. Saved pages open on replay.localhost, a separate browser origin used to isolate archived pages from the organizer API.

Archive files are not encrypted and the local server has no password. Do not expose its port to Wi-Fi or the internet. **Copy diagnostics** places browser details, the selected Shelf folder, and recent status or error events on the clipboard. Review and redact those details before posting publicly.

## Guides and version history

- [Beginner Guide](Archive%20Shelf%20Beginner%20Guide.pdf) - how to use Archive Shelf.
- [Python Path Guide](Archive%20Shelf%20Python%20Path%20Guide.pdf) - configure the Windows launchers.
- [Connection and Safety Guide](ArchiveWebShelf%20Connection%20and%20Safety%20Guide.pdf) - local connections and safety limits.
- [Folder Contents](Archive%20Shelf%20Folder%20Contents.txt) - what each folder and file is for.
- [Source Code](Archive%20Shelf%20Source%20Code.txt) - snapshots of the main source files.
- [Known Issues](BUGS.txt) - bugs, limitations, and future improvements.
- [Version History](CHANGELOG.md) - changes by release.

**Check ReplayWeb.page Updates.bat** checks for and installs updates to the bundled reader only.

## Versions and source

The Archive Shelf release and ready-to-load Recorder extension are version **1.0.0**. The readable recorder source project retains upstream ArchiveWeb.page version **0.17.5**; this identifies the upstream source package.

Rebuilding the Recorder is optional. See the [Recorder build notes](browser-extension/archiveweb-page-source/ARCHIVE%20SHELF%20RECORDER%20BUILD%20NOTES.txt). Building creates development files and does not automatically replace the ready-to-load extension.

## Licenses

The recorder source includes code adapted from Webrecorder ArchiveWeb.page and its AGPL-3.0-or-later license at `browser-extension\archiveweb-page-source\LICENSE.md`. The bundled reader's license is at `replay\LICENSE.txt`. This release does not grant a separate license for Archive Shelf's own app code.
