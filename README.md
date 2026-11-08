
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
- Git for automatic project updates.
- Internet connection.

`start.bat` detects or installs Playwright Chromium and FFmpeg via WinGet when they are missing in source mode. Node.js LTS can provide more YouTube formats. yt-dlp handles fragment parallelism natively; no additional download accelerator is installed. The portable EXE opens in a native `pywebview` window; on Windows, the Microsoft Edge WebView2 Runtime is required. The Edge browser application is not opened.

## Getting started

From the project root:

```powershell
.\start.bat
```

On startup, the script:

1. Checks the latest `main` commit on [GitHub](https://github.com/diego1505-Art/DowFlow).
2. Shows a colored terminal animation while downloading the GitHub update; its color changes every 10 seconds and it stops when the download finishes.
3. If a newer commit is available, shows its author and summary, then asks whether to install the project update.
4. If accepted, temporarily stashes tracked local changes, applies a fast-forward update, and restores the changes.
5. If declined, skips only the project-code update and continues startup.
6. Creates `.venv` if needed and checks dependencies automatically; dependency updates do not require confirmation.
7. Checks Playwright and FFmpeg.

The application opens in its native window and serves its local interface at <http://127.0.0.1:5001>.

For a manual installation:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python startup.py
```

On the first launch of the portable EXE, or when its saved media drive is unavailable, choose a media root when prompted. DowFlow saves this path in `config.json` beside the EXE and reuses it on later launches. The `+` folder control changes it. In a source checkout, the default remains the project's `downloads/` folder. Portable media tools are installed under `<media root>/bin/`; the EXE opens its window while the tools are checked in the background and shows their progress in the loading screen.

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

The source app offers **Export EXE** in the menu and each workspace. If PyInstaller is missing from the Python environment running DowFlow, the first export installs `requirements-build.txt` into that same environment, then builds the EXE. You can also install it manually with `python -m pip install -r requirements-build.txt`. The menu exports all available pages; Video and Music export scoped editions, while a coming-soon category exports that category shell. The native save dialog chooses the EXE name, and output is kept in `dist/`. Export buttons are available only in the source app, not in an already-built executable.

Close DowFlow before building so the included database and its SQLite write-ahead log form a consistent snapshot. The EXE includes the current `dowflow.db`, a blank `config.json` template, and `youtube.com_cookies.txt` when present. On first launch, mutable seed files are extracted beside the EXE only when no local copy exists; later launches never overwrite user files. Choose an existing media root; downloaded files are stored there. The build excludes `downloads/`, the `music/` media folder, the browser profile, FFmpeg and Chromium. Those tools are installed or updated in `<media root>/bin/` after the window opens. Cookie exports grant access to personal accounts: an EXE built with `youtube.com_cookies.txt` contains that signed-in session. Do not distribute that EXE; remove the cookie file before building a shareable copy.

## Diagnostics

The diagnostic center uses the venv, ANSI colors and non-destructive checks:

```powershell
.\debug.bat
```

It can check Python, dependencies, imports, FFmpeg, FFprobe, Chrome, Playwright, the network, SQLite, the Flask APIs and the latest commit available on GitHub. Results are kept in `logs/debug_*.log`.

## Tests

```powershell
python -m unittest discover -v
```

## Cookies and local data

Some sites may require a signed-in session. DowFlow can use Netscape-format cookie exports instead of reading Chrome's locked cookie database. Each download uses the cookie file matching its site, so sessions are not mixed.

### Export site cookies

1. Sign in to the site in Chrome.
2. Open the site and use a trusted cookie-export extension such as **Cookie Exporter** to export its cookies in **Netscape** format. Do not copy cookie values manually from Chrome DevTools.
3. Save the export in the project root, next to `app.py`, using the matching name:
	- YouTube: `youtube_cookies.txt` or `youtube.com_cookies.txt`.
	- Instagram: `instagram_cookies.txt` or `instagram.com_cookies.txt`.
	- TikTok: `tiktok_cookies.txt` or `tiktok.com_cookies.txt`.
	- Other sites: `{domain}_cookies.txt`, for example `vimeo.com_cookies.txt`.
4. Start a new download. The log should say `retrying with <cookie filename>` when DowFlow uses the export.

For a single export containing cookies for several sites, name it `cookies.txt`. A site-specific file takes priority over the generic export. You can also set `DOWFLOW_YOUTUBE_COOKIES`, `DOWFLOW_INSTAGRAM_COOKIES`, `DOWFLOW_TIKTOK_COOKIES`, or `DOWFLOW_COOKIES` to a custom file path.

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
| `tools/debug_center.py` | Interactive diagnostics |
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

Public proxies are intentionally disabled by default: they are unstable and can slow down or compromise downloads.
# images :
<img width="958" height="434" alt="image" src="https://github.com/user-attachments/assets/bd83ecb2-018c-42e1-96ee-7d4a367f6657" />
<img width="736" height="326" alt="image" src="https://github.com/user-attachments/assets/fdf47423-2cf2-467f-92ae-314e6e2dd885" />
<img width="958" height="436" alt="image" src="https://github.com/user-attachments/assets/f8b0da89-8919-48f9-9e87-56093805f24a" />

## License

DowFlow is distributed under the Apache-2.0 license. See [LICENSE](LICENSE).
