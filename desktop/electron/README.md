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

Electron builds the Music React renderer and the YouTube PoToken preload before launching. `/music` is now the shared Music shell, with **Accueil**, **Streaming**, **Bibliothèque**, and **Favoris** views; internal navigation keeps one player mounted. Local files are listed through DowFlow's existing library API and play directly from their local media URL. Favorites combine the existing filename-based local favorites with streaming favorites stored in a dedicated SQLite table. YouTube tracks have a **Télécharger en MP3** action beside the title: it starts DowFlow's existing asynchronous Music/yt-dlp job using the stable video page URL, polls `/jobs/<id>` for progress, and refreshes the local library after completion. It does not reuse or persist the temporary URL used by the streaming player. Downloads are written to DowFlow's configured download folder under `music/`; the user should only save content they are authorized to keep. The historical online-download explorer remains accessible at `/music/explore/legacy` and is intentionally outside the shared player. Search uses YouTube Music Innertube directly from the renderer and streaming playback resolves a temporary WEB_REMIX audio URL through the restricted `window.dowflow.youtube.mintPoToken` bridge. There is no Liner API/backend, Discord integration, or external Google Fonts dependency in this slice. A narrow Electron CORS allowlist applies only to YouTube media/catalogue hosts and the current local DowFlow origin. Streaming requires Electron; local playback works through the existing DowFlow backend, and the ordinary PyWebView launcher remains unchanged.

The built static renderer is written to `static/music-stream/` so Flask can serve it without Node at runtime. After changing renderer source, run `pnpm build:music` from this directory. The `pnpm check` command typechecks and builds the renderer as well as checking the Electron preload.

Electron also injects a per-launch `X-DowFlow-Desktop` header only into requests to the local Flask origin. The backend checks this token only when launched by this shell; normal source and PyWebView launches are unchanged. The renderer receives a deliberately small `window.dowflow` API (`desktop.getRuntimeInfo` and `youtube.mintPoToken`); it does not receive Node.js or `ipcRenderer` access. The hidden YouTube worker has a separate sandboxed preload and accepts only mint requests; the optional TV-session and player-`n` solver paths are not ported yet.

This prototype does not yet package the Python backend or create a Windows installer. The packaged-backend layout and Electron Builder configuration will be added after the development lifecycle and Music integration are validated. Do not distribute this prototype.
