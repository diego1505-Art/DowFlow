
# DowFlow V13

DowFlow is a Windows Flask application for downloading, organizing and playing videos and music locally.

Use DowFlow only for personal purposes and with content you have the right to download, play and keep.

## Features

- Video and audio downloads with `yt-dlp`.
- Optional acceleration with `aria2c` and parallel connections.
- Adaptive quality, VTT subtitles and resumable downloads.
- Music search, album covers, favorites and a local library.
- Browser-based extraction with Playwright for sites that are not supported directly.
- SQLite history, asynchronous jobs and per-domain organization.

## Requirements

- Windows 10 or later.
- Python 3.10 or later in the `PATH`.
- Git for automatic project updates.
- Internet connection.

`start.bat` detects or installs Playwright Chromium, `aria2c` and FFmpeg via WinGet when they are missing. Node.js LTS can provide more YouTube formats.

## Getting started

From the project root:

```powershell
.\start.bat
```

On startup, the script:

1. Checks the latest `main` commit on [GitHub](https://github.com/diego1505-Art/DowFlow).
2. Temporarily stashes tracked changes with Git if needed.
3. Applies a fast-forward update, then restores your local changes.
4. Creates `.venv` if needed.
5. Checks `requirements.txt` and updates `yt-dlp`.
6. Checks Playwright, `aria2c` and FFmpeg.

The application is then available at <http://127.0.0.1:5001>.

For a manual installation:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## Diagnostics

The diagnostic center uses the venv, ANSI colors and non-destructive checks:

```powershell
.\debug.bat
```

It can check Python, dependencies, imports, FFmpeg, FFprobe, `aria2c`, Chrome, Playwright, the network, SQLite, the Flask APIs and the latest commit available on GitHub. Results are kept in `logs/debug_*.log`.

## Tests

```powershell
python -m unittest discover -v
```

## Cookies and local data

Some sites, including YouTube, may require a signed-in session. DowFlow can use a Netscape-format cookie export instead of reading Chrome's locked cookie database.

### Export YouTube cookies

1. Sign in to YouTube in Chrome.
2. Open YouTube, then use a trusted cookie-export extension such as **Cookie Exporter** to export cookies for `youtube.com` in **Netscape** format. Do not copy cookie values manually from Chrome DevTools.
3. Save the exported file in the project root, next to `app.py`. DowFlow accepts either `youtube_cookies.txt` or the extension's common filename, `youtube.com_cookies.txt`.
4. Start a new download. After YouTube requests a session, the log should say `retrying with youtube_cookies.txt` or `retrying with youtube.com_cookies.txt`, then continue with the download.

The cookie file contains credentials for your account. Do not share it or commit it to Git; both supported filenames are excluded by `.gitignore`. If you exposed the file or its contents, revoke the affected sessions and export a fresh file.

If the log says `retrying with Chrome browser cookies` instead, DowFlow did not find an export at the project root. Set `DOWFLOW_YOUTUBE_COOKIES` to the full path of the file if you want to store it elsewhere.

On Windows, Chrome may lock its cookie database while running. This is the yt-dlp issue [#7271](https://github.com/yt-dlp/yt-dlp/issues/7271), not the `browser_profile/` folder used by DowFlow's Playwright extractors. The cookie export avoids that database lock.

Downloads, logs, SQLite databases, browser profiles, Python caches and virtual environments are local and ignored by Git.

## Project structure

| File or folder | Role |
| --- | --- |
| `app.py` | Flask server and HTTP routes |
| `playlist.py` | Video and audio downloads |
| `music.py` | Music search and library |
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
