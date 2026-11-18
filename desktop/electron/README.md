# DowFlow Electron shell (prototype)

This is an experimental desktop shell on the `feature/electron-shell` branch. The existing PyWebView launcher remains unchanged and is still the default launcher. The Electron shell starts the existing Flask application as a child process and loads it from a random loopback port.

## Development

1. Install the Python dependencies from the repository root using the project's normal setup instructions.
2. Install the Electron dependency from this directory:

   ```sh
   pnpm install
   ```

3. Start the shell:

   ```sh
   pnpm dev
   ```

   If Python is not available as `python`/`python3`, set `DOWFLOW_PYTHON` to the interpreter that has DowFlow's dependencies installed.

Electron injects a per-launch `X-DowFlow-Desktop` header only into requests to the local Flask origin. The backend checks this token only when launched by this shell; normal source and PyWebView launches are unchanged. The renderer receives a deliberately small `window.dowflow.desktop` API; it does not receive Node.js or `ipcRenderer` access.

This prototype does not yet package the Python backend or create a Windows installer. The packaged-backend layout and Electron Builder configuration will be added after the development lifecycle and Music integration are validated. Do not distribute this prototype.
