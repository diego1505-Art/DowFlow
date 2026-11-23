# DowFlow Electron shell (prototype)

This is the experimental Electron desktop shell on `main`. The existing PyWebView launcher remains unchanged and is still the default launcher. The Electron shell starts the existing Flask application as a child process and loads it from a random loopback port.

## Development

1. Install the Python dependencies from the repository root using the project's normal setup instructions.
2. Install the Electron and Music renderer dependencies from this directory:

   ```sh
   pnpm install
   ```

3. Start the shell:

   ```sh
   pnpm dev
   ```

   If Python is not available as `python`/`python3`, set `DOWFLOW_PYTHON` to the interpreter that has DowFlow's dependencies installed.

Electron builds the YouTube PoToken preload before launching. Music is the DowFlow Music (Liner) application in `desktop/liner`: the menu opens it through the `dowflow:music:open` IPC handler, or through `/api/music/open` when no Electron bridge exists, and the Music edition installer ships Liner itself. Flask no longer serves a Music web page: the renderer folder and the `static/music-stream/` bundle were removed, and `pnpm check` now only checks the shell and bundles the preload.

The desktop identity is DowFlow throughout: the Electron product name and default window title are `DowFlow`, individual Flask pages may add their own DowFlow title suffix, the Windows AppUserModelID matches the existing PyWebView launcher (`DowFlow.DowFlow`), and the existing `static/dowflow.ico` remains the app icon. The menu and Video footer no longer link users to GitHub documentation; the `Powered by yt-dlp` attribution remains. This build has no Discord/Rich Presence, Liner API, or Electron updater. Source attribution comments for adapted code are retained. YouTube Music/YouTube media hosts and the existing optional Deezer cover lookup remain external services used by Music.

Electron also injects a per-launch `X-DowFlow-Desktop` header only into requests to the local Flask origin. The backend checks this token only when launched by this shell; normal source and PyWebView launches are unchanged. The renderer receives a deliberately small `window.dowflow` API (`desktop.getRuntimeInfo` and `youtube.mintPoToken`); it does not receive Node.js or `ipcRenderer` access. The hidden YouTube worker has a separate sandboxed preload and accepts only mint requests; the optional TV-session and player-`n` solver paths are not ported yet.

This remains an experimental desktop build. The Windows packaging path below is configured but still requires a native Windows build and clean-machine smoke test before distribution.

## Windows package

Build from a Windows checkout with Python and Node.js installed. Use the project's Python virtual environment, install pnpm, and run:

```powershell
cd desktop/electron
pnpm package:win
```

The script builds the Music renderer, creates the PyInstaller one-directory backend under `build/out/DowFlow/`, then invokes Electron Builder for an x64 NSIS installer. The expected installer is written under `desktop/electron/release/` as `DowFlow-<version>-x64.exe`. This is an unsigned per-user installer; it does not configure an update feed. The installer can offer an install location and creates Start Menu/Desktop shortcuts. Uninstalling preserves DowFlow's user data.

The packaged backend starts with a clean profile and does not embed the checkout's SQLite database, config, or YouTube cookies. Electron stores its database, configuration, and logs in its per-user `userData` directory; the selected media/download folder remains separate. The normal PyInstaller portable export keeps its existing seed-data behavior. `static/dowflow.ico` is used for the application, installer, and uninstaller icons.

PyInstaller does not cross-build a Windows executable from this Linux sandbox. Run `pnpm package:win` on Windows, then verify first launch, `/api/status` authentication, `/music` assets, log/database/config writes, media-folder selection, backend shutdown, install/uninstall data retention, and absence of DB/WAL/cookie seeds in the installer before treating it as usable. The packaged startup wait is extended to 120 seconds to allow a cold first launch of the one-directory backend.
