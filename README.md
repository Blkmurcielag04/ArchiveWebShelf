# Archive Shelf 1.0.0

Archive Shelf is a local Windows organizer and viewer for WACZ web archives. It includes a small Python server, a built-in ReplayWeb.page reader, and a browser extension for recording and importing archives.

## Start Archive Shelf

1. Use the included Archive Shelf Python Path Guide.pdf if Python 3.13 is not installed at the launcher's default location.
2. Double-click **Start Archive Shelf.bat**.
3. Keep the server window open while using the organizer. When stopping, use Ctrl+C. If Command Prompt asks whether to terminate the batch job, answer N; then choose R to restart or C to close the window.
4. Use the Archive Shelf page that opens in Chrome, Brave, or another browser.

Both Windows launchers look for Python at %LOCALAPPDATA%\Programs\Python\Python313\python.exe. If Python is installed elsewhere or another version is used, edit the PYTHON_EXE line in both .bat files. The path guide shows where to make that change.

## Record or import archives

The recommended extension is in browser-extension\Archive Shelf Recorder. In Chrome or Brave, open the Extensions page, turn on Developer mode, choose **Load unpacked**, and select that folder. The extension records the current page and the pages or media you visit while recording. It does not follow links or crawl a site on its own. Click **Stop and Save WACZ** when finished.

To import an existing WACZ, open the extension popup and expand **Import an existing WACZ file**. The older importer is kept in browser-extension\Legacy WACZ Importer as an optional alternative.

## Organize and view archives

Create folders, add archives with **Choose archive files**, or drag files from Windows Explorer into the organizer. Click an archive to open it. While viewing a WACZ, use **Manage saved pages** to remove an unwanted capture from Archive Shelf's saved copy; the original WACZ remains unchanged.

The library folder and archive-shelf-data.json catalog are user data. This public starter copy contains no saved archives. The app creates the library as needed and writes the catalog as you add folders or archives. Keep both out of public commits if you use this folder for a personal collection. The included .gitignore excludes them.

## Local connection and privacy

The app opens at http://localhost:8765/ or a nearby port if 8765 is busy. The server listens only on this computer. Saved pages open on replay.localhost, a separate browser origin used to isolate archived pages from the organizer API.

Archive files are not encrypted and the local server has no password. Do not expose its port to Wi-Fi or the internet. **Copy diagnostics** copies browser details, the selected Shelf folder, and recent status or error events to the clipboard; review and redact it before posting.

## Versions and source

The Archive Shelf release and the included ready-to-load Recorder extension are version 1.0.0. The readable recorder source project retains upstream ArchiveWeb.page version 0.17.5; that is the source package version, not the Archive Shelf release number. The source build notes explain the distinction.

- Archive Shelf Beginner Guide.pdf explains how to use the app.
- ArchiveWebShelf Connection and Safety Guide.pdf describes the local server and safety limits.
- Archive Shelf Folder Contents.txt maps the files and folders.
- Archive Shelf Source Code.txt collects the main source files for inspection.
- BUGS.txt lists known issues and next-version improvements.
- Check ReplayWeb.page Updates.bat checks for and installs updates to the embedded reader only.

## Licenses

The recorder source includes code adapted from Webrecorder ArchiveWeb.page and its AGPL-3.0-or-later license at browser-extension\archiveweb-page-source\LICENSE.md. The bundled reader's license is at replay\LICENSE.txt. This release does not grant a separate license for Archive Shelf's own app code; add a project license if you want to give others reuse rights.