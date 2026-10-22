ARCHIVEWEBSHELF EXTENSION

This is the recommended combined browser extension named ArchiveWebShelf. It records pages as you browse, saves the finished WACZ directly into Archive Shelf, and includes a collapsed “Import an existing WACZ file” section. The preserved import-only legacy extension is in Legacy WACZ Importer\ if you prefer to keep using it.

INSTALL ON CHROME OR BRAVE
1. Start Archive Shelf with Start Archive Shelf.bat and leave its black server window open.
2. Open chrome://extensions in Chrome or brave://extensions in Brave.
3. Turn on Developer mode.
4. Choose Load unpacked and select the folder named Archive Shelf Recorder beside this note.
5. Pin the ArchiveWebShelf button if you want it beside the address bar.
6. Once ArchiveWebShelf works, you can disable the separate ArchiveWebShelf Importer (Legacy) extension in the browser. Its loadable project folder remains in Legacy WACZ Importer\ as an option.

MAKE AN ARCHIVE
1. Open the website you want to save.
2. Click Archive Shelf Recorder.
3. Choose the Shelf folder. Click through the folder list, then click Save in this folder.
4. Click Start Archiving. The page reloads as recording begins.
5. Browse to the pages you want to keep. Open links and wait for pictures, video, and other media to load while recording is active.
6. Open the Archive Shelf Recorder button again and click Stop and Save WACZ.
7. Wait for the saved message. The archive will appear in the folder you chose.

IMPORT A WACZ YOU ALREADY HAVE
1. Click ArchiveWebShelf and choose the destination folder.
2. Open “Import an existing WACZ file.”
3. Choose the archive file, then click Import existing archive.
4. Wait for the imported message. The file is added to the selected folder.

Recording is manual, as in Webrecorder ArchiveWeb.page: start on the page you want, then browse and click the pages or media to capture. The extension records what you visit during the session; it does not follow links or navigate the tab on its own. Click Stop and Save WACZ when done. Some sites block browser debugging or use media that cannot be archived.

WHAT YOU NEED
- Chrome or Brave on the computer doing the capture.
- Archive Shelf running on that same computer. The extension talks to its local address on ports 8765 through 8794.
- No separate ReplayWeb.page desktop app and no separate ArchiveWeb.page recorder extension are needed once this extension is installed.
- This is a browser extension, not a standalone Windows executable. To use it on another computer, copy the Archive Shelf app and archive collection, install Python and Chrome/Brave there, then load this extension folder from that computer.

YOUR FILES AND PRIVACY
The WACZ is sent to the Archive Shelf server on this computer and stored under the app's library folder. This extension does not send archives to a cloud service. Keep the Archive Shelf server window open during recording and saving. Cookie archiving is turned off by default in this build; you can opt in from the recorder's privacy settings if you have a specific reason. Cookies can include information meant to stay private.

SOURCE AND UPDATES
The complete readable source is in archiveweb-page-source. It includes Archive Shelf's integration and the upstream Webrecorder ArchiveWeb.page source. See its LICENSE.md; the upstream project is AGPL-3.0-or-later. The file Archive Shelf Source Code.txt beside the app collects the main files into one copyable document for inspection.

Check ReplayWeb.page Updates.bat only updates the embedded reader used to open archives. It does not update this recorder extension. To change or rebuild the extension, edit the files under archiveweb-page-source/src and run the instructions in that folder's ARCHIVE SHELF RECORDER BUILD NOTES.txt using Node.js and Yarn.




