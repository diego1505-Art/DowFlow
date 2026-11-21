
# DowFlow V15

DowFlow is a Windows Flask application for downloading, organizing and playing videos and music locally.

Use DowFlow only for personal purposes and with content you have the right to download, play and keep.

## Features

- Video and audio downloads with `yt-dlp`.
- Native parallel fragment downloads through `yt-dlp`.
- Adaptive quality, VTT subtitles and resumable downloads.
- Music search, album covers, favorites and a local library.
- Browser-based extraction with Playwright for sites that are not supported directly.
- SQLite history, asynchronous jobs and per-domain organization.

## Requirements

- Windows 10 or later.
- Python 3.10 or later in the `PATH`.
- Git for automatic updates when running a clone; ZIP updates use GitHub directly.
- Internet connection.

`launcher.py` (started by `start.bat`) detects or installs Playwright Chromium and FFmpeg via WinGet when they are missing in source mode. A ZIP downloaded from GitHub has no `.git` folder, so the launcher checks GitHub's latest `main` commit through the API, compares the project files, and can replace only project files while preserving `.venv`, `downloads`, `config.json`, `dowflow.db`, and `logs`. Node.js LTS can provide more YouTube formats. yt-dlp handles fragment parallelism natively; no additional download accelerator is installed. The portable EXE opens in a native `pywebview` window; on Windows, the Microsoft Edge WebView2 Runtime is required. The Edge browser application is not opened.

## Getting started

From the project root:

```powershell
.\start.bat
```

On startup, `launcher.py` runs everything in the `start.bat` console:

1. Checks the latest `main` commit on [GitHub](https://github.com/diego1505-Art/DowFlow); clones use Git, while ZIPs use the GitHub API and archive.
2. If a ZIP update is available, asks whether to install it and preserves runtime data and the virtual environment.
3. If a clone update is available, temporarily stashes tracked local changes, applies a fast-forward update, and restores the changes.
4. If declined, skips only the project-code update and continues startup.
5. Creates `.venv` if needed and checks dependencies automatically; dependency updates do not require confirmation.
6. Checks Playwright and FFmpeg.
7. Starts the server and streams its logs in that same console window.

The application opens in its native window and serves its local interface at <http://127.0.0.1:5001>. The console stays open while the server runs: closing it or pressing Ctrl+C stops DowFlow cleanly, and a server crash leaves the window open with a message.

For a manual installation:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python launcher.py
```

On the first launch of the portable EXE, or when its saved media drive is unavailable, choose a media root when prompted. DowFlow saves this path in `config.json` beside the EXE and reuses it on later launches. The `+` folder control changes it. In a source checkout, downloads default to `%USERPROFILE%\Downloads` and every file is written directly there, without a per-site, per-artist or per-album subfolder. Portable media tools are installed under `<media root>/bin/`; the EXE opens its window while the tools are checked in the background and shows their progress in the loading screen.

## Portable Windows build

Build the one-file, no-console executable from Windows with the project's virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
python -m pip install setuptools==42.0.1
python -m PyInstaller --clean --noconfirm build.spec
```

Install the pinned `setuptools` version after the build requirements and before starting PyInstaller. This works around the `ModuleNotFoundError: No module named 'jaraco'` compatibility issue seen in some build environments. The build is windowed (`console=False`) and uses `pywebview` with WebView2 instead of launching a browser window. Tkinter is included for the native folder picker.

Executables are built only from the command line, through `build.bat` (or, manually, the PyInstaller commands above). The interface has no export button, so a build always goes through `build.bat`. It asks for a scope — the whole menu, Video, Music, Movies / Series or Anime — and for the EXE name, then writes `dist/<name>.exe`. Scoped editions open directly on their selected page and do not include the general menu. `build_export.py` installs `requirements-build.txt` automatically when PyInstaller is missing from the build environment.

Close DowFlow before building so the included database and its SQLite write-ahead log form a consistent snapshot. The EXE embeds the current `dowflow.db`, a blank `config.json` template, the scoped `app_scope.json`, and `youtube.com_cookies.txt` when present. On first launch, choose an existing portable root; DowFlow creates `config.json`, `dowflow.db`, `logs/dowflow.log` and `bin/` there, and writes downloads directly into that root. The large Playwright Node runtime is no longer embedded in the EXE; a verified portable `node.exe` is installed in `<portable root>/bin/` on first launch and used by Playwright. This substantially reduces the EXE size while keeping the application independent of a system Node installation. The EXE may be moved anywhere and does not require the `dist/` folder on the target PC. FFmpeg, its DLLs, Node.js, and Playwright Chromium are installed or updated in `<portable root>/bin/` after the window opens. A small Windows registry pointer remembers the selected root without placing configuration beside the EXE. Cookie exports grant access to personal accounts: an EXE built with `youtube.com_cookies.txt` contains that signed-in session. Do not distribute that EXE; remove the cookie file before building a shareable copy.

## Tests

```powershell
python -m unittest discover -v
```

## Cookies and local data

Some sites may require a signed-in session. DowFlow can use Netscape-format cookie exports instead of reading Chrome's locked cookie database. Each download uses the cookie file matching its site, so sessions are not mixed.

### Export site cookies

1. Sign in to the site in Chrome.
2. Open the site and use a trusted cookie-export extension such as **Cookie Exporter** to export its cookies in **Netscape** format. Do not copy cookie values manually from Chrome DevTools.
3. Save the export, then import it from **DowFlow Music → Paramètres → Cookies** (or drop it in the project root, next to `app.py`). Imported files are validated and copied to `%APPDATA%\DowFlow\cookies\` with the matching name:
	- YouTube: `youtube_cookies.txt` or `youtube.com_cookies.txt`.
	- Instagram: `instagram_cookies.txt` or `instagram.com_cookies.txt`.
	- TikTok: `tiktok_cookies.txt` or `tiktok.com_cookies.txt`.
	- Other sites: `{domain}_cookies.txt`, for example `vimeo.com_cookies.txt`.
4. Start a new download. The log should say `retrying with <cookie filename>` when DowFlow uses the export.

For a single export containing cookies for several sites, name it `cookies.txt`. A site-specific file takes priority over the generic export.

Exports imported from the Music settings are stored in `%APPDATA%\DowFlow\cookies\` and take priority. DowFlow also reads the same file names from `%APPDATA%\DowFlow Music\cookies\` (for example `youtube.com_cookies.txt` or `cookies.txt`), so an export used by the desktop music app works for video downloads too. Files in the project root are still read; set `DOWFLOW_COOKIES_DIR` to point at another folder. You can also set `DOWFLOW_YOUTUBE_COOKIES`, `DOWFLOW_INSTAGRAM_COOKIES`, `DOWFLOW_TIKTOK_COOKIES`, or `DOWFLOW_COOKIES` to a custom file path.

Cookie files contain account credentials. Do not share them or commit them to Git; `*_cookies.txt` and `cookies.txt` are excluded by `.gitignore`. If you expose a cookie file or its contents, revoke the affected sessions and export a fresh file.

If the log says `retrying with Chrome browser cookies` instead, DowFlow did not find a matching export. Check the filename and project-root location, or set the corresponding environment variable to the full path.

On Windows, Chrome may lock its cookie database while running. This is the yt-dlp issue [#7271](https://github.com/yt-dlp/yt-dlp/issues/7271), not the `browser_profile/` folder used by DowFlow's Playwright extractors. The cookie export avoids that database lock.

Downloads, logs, SQLite databases, browser profiles, Python caches and virtual environments are local and ignored by Git.

## Project structure

| File or folder | Role |
| --- | --- |
| `app.py` | Flask server and HTTP routes |
| `playlist.py` | Video and audio downloads |
| `music.py` | Music search, downloads and library |
| `music_dataset.py` | Local catalog interface |
| `browser_extractor.py` | Browser-based extraction |
| `url_expanders/` | URL and episode expansion |
| `tools/fix_videos.py` | MP4 file remuxing |
| `tools/extract_urls_from_txt.py` | URL extraction from a text file |
| `templates/` and `static/` | Web interface |
| `downloads/` | Locally downloaded media |
| `logs/` | Local logs |

## Configuration

The main options are in `config.py`:

- `DOWFLOW_BROWSER_VISIBLE` shows the Playwright browser.
- `DOWFLOW_CONNECTIONS` forces the number of parallel connections.
- `DOWFLOW_PROXY_AUTO` enables fetching public proxies (disabled by default).
- `DOWFLOW_YOUTUBE_COOKIES` sets an alternative cookies file.

Public proxies are intentionally disabled by default : they are unstable and can slow down or compromise downloads.
## License

DowFlow is distributed under the Apache-2.0 license. See [LICENSE](LICENSE).
