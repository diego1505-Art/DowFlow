
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

Some sites require a session. A local Chrome profile or a `youtube_cookies.txt` file in Netscape format can be used. These files give access to your accounts and are excluded from the repository by `.gitignore`.

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
