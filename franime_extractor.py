"""
Franime.fr extractor — supports SIBNET, FILEMOON, SENDVID, VIDMOLY, and direct HLS.
Launches Chrome in the background by default, captures player URLs, and tries each player in order.
"""
from __future__ import annotations
import re, os, shutil, tempfile, time, random
from pathlib import Path
from typing import Any

from config import BROWSER_HEADLESS, BROWSER_PROFILE_DIR, PROXIES, SUBPROCESS_CREATION_FLAGS
from logger import get_logger
from utils import _resolve_ffmpeg_dir, find_chrome_binary, has_ffmpeg, yt_dlp_runtime_options

log = get_logger("franime_ext")

# ── Anti-Bot Settings ────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

def human_delay(min_ms=500, max_ms=1500):
    """Wait for a random interval."""
    time.sleep(random.randint(min_ms, max_ms) / 1000.0)

def move_mouse_humanly(page):
    """Move the mouse along a less linear path."""
    try:
        width, height = 1280, 720
        for _ in range(random.randint(2, 5)):
            x, y = random.randint(0, width), random.randint(0, height)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            human_delay(100, 300)
    except Exception:
        pass

# ── Known players and their URL patterns ─────────────────────────────────────
# Each entry: (name, detection regex, blacklist regex)
PLAYERS = [
    ("SIBNET",   re.compile(r"sibnet\.ru/shell\.php",          re.I), re.compile(r"sibnet\.ru/export/|sbcount|/time", re.I)),
    ("FILEMOON", re.compile(r"filemoon\.\w+/",                 re.I), None),
    ("SENDVID",  re.compile(r"sendvid\.com/",                  re.I), None),
    ("VIDMOLY",  re.compile(r"vidmoly\.\w+/",                  re.I), None),
    ("HLS",      re.compile(r"\.(m3u8|mpd)(\?|$)",            re.I), None),
    ("WATCH2",   re.compile(r"franime\.fr/watch2/",            re.I), None),
]

SKIP_HOSTS = {
    "google-analytics", "googletagmanager", "doubleclick", "facebook",
    "twitter", "sentry", "fonts.google", "gstatic", "clarity.ms",
    "hotjar", "segment.io", "amplitude", "adskeeper", "bidgear",
    "a-ads.com", "betweendigital", "yandex", "mail.ru",
}

# Download priority (yt-dlp supports all these domains)
PLAYER_PRIORITY = ["HLS", "SIBNET", "SENDVID", "VIDMOLY", "FILEMOON", "WATCH2"]


def _skip(url: str) -> bool:
    return url.startswith("blob:") or any(h in url for h in SKIP_HOSTS)


def _detect_player(url: str) -> str | None:
    """Return the player name detected for a URL."""
    for name, pattern, blacklist in PLAYERS:
        if blacklist and blacklist.search(url):
            continue
        if pattern.search(url):
            return name
    return None


def _candidate_filepaths_from_info(info: dict[str, Any], output_path: str) -> list[str]:
    candidates: list[str] = []

    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for item in requested_downloads:
            if isinstance(item, dict):
                filepath = item.get("filepath")
                if isinstance(filepath, str) and filepath:
                    candidates.append(filepath)

    for key in ("filepath", "_filename"):
        value = info.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    title = info.get("title")
    ext = info.get("ext")
    if isinstance(title, str) and title:
        if isinstance(ext, str) and ext:
            candidates.append(os.path.join(output_path, f"{title}.{ext}"))
        for known_ext in (".mp4", ".webm", ".mkv", ".m4v", ".mov", ".avi", ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus"):
            candidates.append(os.path.join(output_path, f"{title}{known_ext}"))

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normpath(path)
        if normalized not in seen:
            unique_candidates.append(normalized)
            seen.add(normalized)

    return unique_candidates


def _resolve_downloaded_file(info: dict[str, Any], output_path: str, before_mtime: dict[str, float]) -> str | None:
    ignored = {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".description"}

    for candidate in _candidate_filepaths_from_info(info, output_path):
        if os.path.isfile(candidate) and os.path.splitext(candidate)[1].lower() not in ignored:
            return candidate

    candidates = []
    for f in os.listdir(output_path):
        fp = os.path.join(output_path, f)
        mt = os.path.getmtime(fp)
        if f not in before_mtime or mt > before_mtime[f]:
            if os.path.splitext(f)[1].lower() not in ignored:
                candidates.append((mt, fp))

    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else None


def extract_stream_url(page_url: str, preferred_player: str | None = None, proxy_url: str | None = None) -> tuple[str | None, str | None, dict[str, list[str]], dict[str, Any]]:
    """
    Return (stream_url, player_name, all_captured, diagnostics).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

    # Map each player to its captured URLs.
    captured: dict[str, list[str]] = {name: [] for name, *_ in PLAYERS}
    url_status: dict[str, int] = {}
    diagnostics: dict[str, Any] = {
        "main_status": None,
        "blocked": False,
        "blocked_url": None,
        "url_status": url_status,
    }

    if proxy_url:
        log.info("  [franime] Using proxy: %s", proxy_url.split("@")[-1])

    def _remember(name: str, url: str) -> None:
        if url not in captured[name]:
            log.success('  [franime] ✓ [%s] %s', name, url[:110])
            captured[name].append(url)

    def on_request(req):
        url = req.url
        if _skip(url): return
        name = _detect_player(url)
        if name:
            _remember(name, url)

    def on_response(resp):
        url = resp.url
        if _skip(url): return
        # Do not block on 403 immediately; Cloudflare often returns 403/503 during its challenge.
        if url.split("#", 1)[0] == page_url.split("#", 1)[0]:
            diagnostics["main_status"] = resp.status
            if resp.status in {401, 429}: # Treat 401 and 429 as actual blocking responses.
                diagnostics["blocked"] = True
                diagnostics["blocked_url"] = url
        name = _detect_player(url)
        if name:
            url_status[url] = resp.status
            _remember(name, url)
        ct = resp.headers.get("content-type", "").lower()
        if any(t in ct for t in ["mpegurl", "dash+xml", "mp2t", "x-mpegurl"]):
            hls_name = _detect_player(url) or "HLS"
            url_status[url] = resp.status
            _remember(hls_name, url)
        if not any(e in url for e in [".js",".css",".png",".jpg",".svg",".woff",".ico",".gif",".webp",".wasm"]):
            log.info('  [franime]   %s  %s', resp.status, url[:100])

    chrome_path   = _find_chrome()
    user_data_dir = _chrome_user_data_dir()
    
    # Use the project's persistent profile instead of a temporary one.
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = str(BROWSER_PROFILE_DIR)

    log.info('  [franime] Chrome : %s', chrome_path or 'Chromium Playwright')
    log.info('  [franime] Profil : %s', profile_path)

    with sync_playwright() as pw:
        # Browser launch arguments.
        base_args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-position=0,0",
        ]

        # Random user agent.
        user_agent = random.choice(USER_AGENTS)
        # Random viewport.
        viewport_w = random.randint(1200, 1600)
        viewport_h = random.randint(700, 1000)

        # Proxy config for Playwright
        proxy_config = None
        if proxy_url:
            proxy_config = {"server": proxy_url}

        # If Chrome is installed, try to sync its initial cookies once.
        if chrome_path and user_data_dir and not (BROWSER_PROFILE_DIR / "Default").exists():
            log.info('  [franime] Synchronisation initiale du profil Chrome...')
            src_default = os.path.join(user_data_dir, "Default")
            dst_default = BROWSER_PROFILE_DIR / "Default"
            dst_default.mkdir(parents=True, exist_ok=True)
            for fname in ["Cookies", "Login Data", "Local State", "Preferences", "Web Data"]:
                src = os.path.join(src_default, fname)
                if os.path.isfile(src):
                    try: shutil.copy2(src, dst_default / fname)
                    except Exception: pass
        
        # Launch a persistent context to retain Franime sessions and cookies.
        ctx = pw.chromium.launch_persistent_context(
            profile_path, 
            headless=BROWSER_HEADLESS, 
            executable_path=chrome_path,
            args=base_args, 
            no_viewport=False, 
            viewport={"width": viewport_w, "height": viewport_h},
            user_agent=user_agent,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            proxy=proxy_config
        )
        page = ctx.new_page()

        # Inject a script to mask Playwright and simulate browser properties.
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['fr-FR', 'fr', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = { runtime: {} };
        """)

        # --- Local safeguards ---
        # Wait briefly before loading the page.
        human_delay(2000, 6000)

        page.on("request",  on_request)
        page.on("response", on_response)

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=45_000)
        except PwTimeout:
            log.warning('  [franime] Timeout – on continue')

        # Detect Cloudflare.
        content_lower = page.content().lower()
        if "challenge-platform" in content_lower or "cloudflare" in content_lower or "just a moment" in page.title().lower():
            log.info("  [franime] Cloudflare challenge detected; waiting for it to clear (up to 45s)...")
            human_delay(4000, 6000)
            try:
                # Try clicking the checkbox if it appears in the Cloudflare iframe.
                for i in range(15): # Up to 15 attempts.
                    curr_content = page.content().lower()
                    if "challenge-platform" not in curr_content and "cloudflare" not in curr_content and "just a moment" not in page.title().lower():
                        break
                    
                    # Move the mouse randomly.
                    move_mouse_humanly(page)
                    
                    # Scroll occasionally.
                    if random.random() > 0.5:
                        page.mouse.wheel(0, random.randint(100, 400))
                    
                    # Find the challenge iframe.
                    frames = page.frames
                    for f in frames:
                        if "cloudflare" in f.url or "turnstile" in f.url:
                            try:
                                checkbox = f.query_selector("input[type='checkbox'], #challenge-stage, .ctp-checkbox-container")
                                if checkbox:
                                    # Move to the element before clicking it.
                                    box = checkbox.bounding_box()
                                    if box:
                                        page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2, steps=10)
                                        human_delay(200, 500)
                                    checkbox.click()
                                    log.success("  [franime] ✓ Tentative de clic Cloudflare (%s)", i + 1)
                            except Exception: pass
                    human_delay(2000, 3500)

                # Wait for the final button; support both French and English labels.
                page.wait_for_selector("button:has-text('Regarder'), button:has-text('Watch'), .player-container", timeout=35_000)
                log.success('  [franime] ✓ Page accessible !')
            except Exception as e:
                log.error('  [franime] Challenge still present or an error occurred: %s', e)
                page.wait_for_timeout(2_000)

        # Select the preferred player when one is requested.
        if preferred_player:
            _select_player(page, preferred_player)

        # Click the watch episode button.
        page.wait_for_timeout(2_000)
        selectors = [
            "button:has-text('Regarder')", "a:has-text('Regarder')", 
            "button:has-text('Watch')", "a:has-text('Watch')",
            "button:has-text('épisode')", "button:has-text('episode')"
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=3_000)
                    log.info("  [franime] Clic 'Regarder' : %s", sel)
                    page.wait_for_timeout(2_000)
                    break
            except Exception:
                pass

        # Wait for the player.
        for sel in ["video", "iframe", "[class*='player']"]:
            try:
                page.wait_for_selector(sel, timeout=10_000)
                break
            except Exception:
                pass

        # Click play.
        for sel in ["video", ".play-button", "[class*='play']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.click(timeout=2_000)
                    break
            except Exception:
                pass

        # Wait up to 35 seconds.
        for i in range(35):
            page.wait_for_timeout(1_000)
            total = sum(len(v) for v in captured.values())
            if total >= 1 and i >= 3:
                break

        # Sendvid often returns 502; open Watch2 to capture the actual stream (mp4/m3u8).
        healthy_players = any(
            url_status.get(u, 0) and url_status.get(u, 999) < 400
            for name in ("HLS", "SIBNET", "VIDMOLY", "FILEMOON")
            for u in captured.get(name, [])
        )
        sendvid_broken = captured.get("SENDVID") and all(
            url_status.get(u, 0) >= 400 for u in captured["SENDVID"]
        )
        if captured.get("WATCH2") and (sendvid_broken or not healthy_players):
            watch2_url = captured["WATCH2"][0]
            log.error('  [franime] Sendvid unavailable or no direct stream; opening Watch2...')
            try:
                page.goto(watch2_url, wait_until="domcontentloaded", timeout=45_000)
                for sel in ["video", "iframe", "source"]:
                    try:
                        page.wait_for_selector(sel, timeout=8_000)
                        break
                    except Exception:
                        pass
                for i in range(20):
                    page.wait_for_timeout(1_000)
                    if captured.get("HLS") or any(
                        captured.get(n) for n in ("SIBNET", "VIDMOLY", "FILEMOON", "SENDVID")
                        if n != "WATCH2"
                    ):
                        # A useful new stream was captured.
                        if any(
                            url_status.get(u, 200) < 400
                            for n in ("HLS", "SIBNET", "VIDMOLY", "FILEMOON", "SENDVID")
                            for u in captured.get(n, [])
                        ):
                            break
                    # Check video sources in the page and its iframes.
                    try:
                        for frame in page.frames:
                            srcs = frame.eval_on_selector_all(
                                "video, video source, source[src], iframe[src]",
                                "els => els.map(e => e.src || e.getAttribute('src')).filter(Boolean)",
                            )
                            for src in srcs or []:
                                name = _detect_player(src) or ("HLS" if ".m3u8" in src or ".mpd" in src else None)
                                if name:
                                    url_status.setdefault(src, 200)
                                    _remember(name, src)
                    except Exception:
                        pass
            except Exception as e:
                log.warning('  [franime] Watch2 could not be used: %s', e)

        ctx.close()

    # Choose the best available player, ignoring URLs with 4xx/5xx responses.
    order = ([preferred_player] if preferred_player else []) + PLAYER_PRIORITY
    for name in order:
        urls = captured.get(name, [])
        healthy = [u for u in urls if url_status.get(u, 200) < 400]
        pick = healthy[0] if healthy else (urls[0] if urls and name == "WATCH2" else None)
        if pick:
            status = url_status.get(pick)
            status_txt = f" (HTTP {status})" if status is not None else ""
            log.success('  [franime] Selected player: %s → %s%s', name, pick[:100], status_txt)
            return pick, name, captured, diagnostics

    return None, None, captured, diagnostics


def _select_player(page, player_name: str):
    """Try to select a specific player from the Franime dropdown."""
    try:
        # Open the dropdown.
        for sel in ["select", "[class*='lecteur']", "[class*='player-select']", "button:has-text('Lecteur')"]:
            el = page.query_selector(sel)
            if el:
                el.click(timeout=2_000)
                page.wait_for_timeout(500)
                # Find the requested player option.
                opt = page.query_selector(f"option:has-text('{player_name}'), li:has-text('{player_name}')")
                if opt:
                    opt.click(timeout=2_000)
                    log.success('  [franime] Selected player: %s', player_name)
                    page.wait_for_timeout(1_500)
                    return
    except Exception as e:
        log.error('  [franime] Could not change player: %s', e)


def download_franime(url: str, output_path: str = "downloads",
                     download_type: str = "video", quality: str = "best",
                     video_format: str = "mp4", audio_format: str = "mp3",
                     language: str | None = None) -> dict[str, Any]:
    os.makedirs(output_path, exist_ok=True)

    # --- Request delay ---
    log.info('  [franime] Waiting before starting...')
    human_delay(3000, 8000)

    # Try direct access first: public proxies often time out and waste several minutes.
    shuffled_proxies = list(PROXIES)
    random.shuffle(shuffled_proxies)
    proxies_to_try = [None] + shuffled_proxies

    # 1. Try extracting with proxy rotation.
    stream_url = None
    player_name = None
    all_captured: dict[str, list[str]] = {}
    url_status: dict[str, int] = {}
    
    for proxy in proxies_to_try:
        try:
            log.info("\n  [franime] Analyse de la page (Proxy: %s) : %s", proxy or "Direct", url)
            stream_url, player_name, all_captured, diagnostics = extract_stream_url(url, proxy_url=proxy)
            url_status = diagnostics.get("url_status") or {}
            
            if stream_url:
                break # A stream was found.
                
            if diagnostics.get("blocked") and diagnostics.get("main_status") in {401, 429}:
                log.error(
                    "  [franime] Proxy blocked or fatal error (%s). Trying the next one...",
                    diagnostics.get("main_status"),
                )
                continue
                
        except Exception as e:
            log.error('  [franime] ✗ Proxy error (%s): %s', proxy, e)
            continue

    if not stream_url and not all_captured:
        return {
            "success": False,
            "error": "Could not extract streams, even after proxy rotation.",
            "reason": "page_blocked"
        }

    # Track tested URLs to avoid unnecessary retries.
    tried_urls = set()

    def try_download(s_url, s_name):
        if not s_url or s_url in tried_urls:
            return None
        # Do not retry an embed that returned 4xx/5xx during capture.
        status = url_status.get(s_url)
        if status is not None and status >= 400 and s_name != "WATCH2":
            log.warning('  [franime] Skipping [%s] HTTP %s: %s', s_name, status, s_url[:100])
            tried_urls.add(s_url)
            return None
        tried_urls.add(s_url)
        
        for proxy in proxies_to_try:
            log.info(
                "  [franime] Tentative [%s] (Proxy: %s) : %s...",
                s_name,
                proxy or "Direct",
                s_url[:100],
            )
            try:
                res = _download_stream(s_url, s_name, url, output_path, download_type, quality,
                                       video_format=video_format, audio_format=audio_format,
                                       language=language, proxy_url=proxy)
                if res.get("filename"):
                    return res
            except Exception as e:
                log.error('  [franime] ✗ Proxy failed (%s): %s', proxy, e)
                continue
        return None

    # 2. Try the best player found during the first pass.
    if stream_url:
        result = try_download(stream_url, player_name)
        if result: return result

    # 3. Try all other captured URLs in priority order.
    for name in PLAYER_PRIORITY:
        for s_url in all_captured.get(name, []):
            result = try_download(s_url, name)
            if result: return result

    # 4. Force another browser player if none of the captured URLs worked.
    for player in PLAYER_PRIORITY:
        if all_captured.get(player):
            continue
        
        log.info('\\n  [franime] Forcing player: %s', player)
        try:
            stream_url, player_name, captured_now, diagnostics_now = extract_stream_url(url, preferred_player=player)
            url_status.update(diagnostics_now.get("url_status") or {})
            if diagnostics_now.get("blocked") and not stream_url and diagnostics_now.get("main_status") != 403:
                status = diagnostics_now.get("main_status")
                log.error("  [franime] Blocked (%s).", status)
                continue
            if stream_url:
                result = try_download(stream_url, player_name)
                if result: return result
            
            for name in PLAYER_PRIORITY:
                for s_url in captured_now.get(name, []):
                    result = try_download(s_url, name)
                    if result: return result
        except Exception as e:
            log.error('  [franime] Error while forcing %s: %s', player, e)

    log.warning("  [franime] No player worked for %s", url)
    return {
        "success": False,
        "filename": None,
        "filepath": None,
        "error": "Player was not captured or is unavailable on Franime.",
        "reason": "not_found_or_blocked"
    }


def _download_stream(stream_url: str, player_name: str, page_url: str,
                     output_path: str, download_type: str, quality: str,
                     video_format: str = "mp4", audio_format: str = "mp3",
                     language: str | None = None,
                     proxy_url: str | None = None) -> dict[str, Any]:
    import yt_dlp
    import subprocess

    is_sibnet  = "sibnet.ru"   in stream_url
    is_filemoon= "filemoon"    in stream_url
    referer    = (
        "https://video.sibnet.ru/" if is_sibnet else
        "https://filemoon.sx/"     if is_filemoon else
        "https://franime.fr/"
    )

    slug   = re.search(r"/anime/([^?/]+)", page_url)
    title  = slug.group(1) if slug else "franime-video"
    params = dict(p.split("=",1) for p in page_url.split("?",1)[-1].split("&") if "=" in p)
    ep     = f"s{params.get('s','1')}-ep{params.get('ep','1')}-{params.get('lang','vo')}"

    ffmpeg_dir = _resolve_ffmpeg_dir()
    ffmpeg_available = has_ffmpeg()
    ffmpeg_exe = "ffmpeg"
    ffprobe_exe = "ffprobe"
    if ffmpeg_dir:
        ffmpeg_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe")

    ydl_opts: dict[str, Any] = {
        "quiet": False,
        "no_warnings": True,
        "noplaylist": True,
        "concurrent_fragment_downloads": 16,
        "retries": 10,
        "fragment_retries": 10,
        "proxy": proxy_url,
        "http_headers": {
            "Referer":    referer,
            "Origin":     referer.rstrip("/"),
            "User-Agent": random.choice(USER_AGENTS),
        },
    }

    # ── Formats et post-traitements via playlist helpers ────────────────────
    try:
        from playlist import (
            _build_video_format_string,
            _build_video_format_sort,
            _build_audio_format_string,
            _build_audio_postprocessor,
            _build_subtitle_lang_options,
            _resolve_quality_key,
        )
        from config import VIDEO_OUTPUT_FORMATS, AUDIO_OUTPUT_FORMATS
    except Exception:
        _build_video_format_string = None  # type: ignore

    ffmpeg_dir = _resolve_ffmpeg_dir_proxy()
    has_ffmpeg = bool(ffmpeg_dir) or (bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")))
    ydl_opts.update(yt_dlp_runtime_options())
    if ffmpeg_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir

    if download_type == "audio":
        if _build_video_format_string is not None:
            ydl_opts["format"] = _build_audio_format_string(audio_format)
            pp = _build_audio_postprocessor(audio_format, has_ffmpeg)
            if pp:
                ydl_opts["postprocessors"] = [pp]
        else:
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            if has_ffmpeg:
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
    else:
        if _build_video_format_string is not None:
            ydl_opts["format"] = _build_video_format_string(quality, video_format, has_ffmpeg)
            quality_sort = _build_video_format_sort(quality)
            if quality_sort:
                ydl_opts["format_sort"] = quality_sort
            f_meta = VIDEO_OUTPUT_FORMATS.get(video_format, VIDEO_OUTPUT_FORMATS["best"])
            container = f_meta["container"]
            if has_ffmpeg and container and f_meta["merge"]:
                ydl_opts["merge_output_format"] = container
        else:
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"

    # ── Subtitles / language ─────────────────────────────────────────────────
    if language and _build_video_format_string is not None:
        ydl_opts.update(_build_subtitle_lang_options(language))

    # Keep the established slug-s1-ep1-lang.ext filename pattern.
    lang_tag = ""
    if language:
        lang_tag = f"-{language}"
    elif params.get("lang"):
        lang_tag = f"-{params.get('lang')}"
    ep_tag = f"s{params.get('s','1')}-ep{params.get('ep','1')}{lang_tag or ''}"
    ydl_opts["outtmpl"] = os.path.join(output_path, f"{title}-{ep_tag}.%(ext)s")

    if shutil.which("aria2c"):
        ydl_opts["external_downloader"] = "aria2c"
        ydl_opts["external_downloader_args"] = [
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--continue=true",
        ]
        log.success('  [aria2c] Fast downloader enabled for Franime')

    # Try the download.
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(stream_url, download=True)
            filepath = _resolve_downloaded_file(info, output_path, {})
            
            if filepath and os.path.isfile(filepath):
                if not ffmpeg_available:
                    # Without FFmpeg, the file cannot be inspected or repaired.
                    log.warning("  [franime] FFmpeg not found; skipping integrity checks.")
                    return {
                        "success": True,
                        "filename": os.path.basename(filepath),
                        "filepath": filepath,
                        "folder": os.path.basename(output_path),
                    }
                # --- Automatic repair ---
                log.info("  [franime] Checking file integrity: %s", os.path.basename(filepath))
                
                # 1. Check whether this is a readable video.
                probe_cmd = [ffprobe_exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
                probe_res = subprocess.run(
                    probe_cmd,
                    capture_output=True,
                    text=True,
                    creationflags=SUBPROCESS_CREATION_FLAGS,
                )
                
                is_valid = False
                try:
                    duration = float(probe_res.stdout.strip())
                    if duration > 10: # Treat files longer than 10 seconds as valid.
                        is_valid = True
                except ValueError:
                    pass

                if not is_valid:
                    log.error(
                        "  [franime] Video is corrupted or unreadable (%s). Attempting repair...",
                        os.path.basename(filepath),
                    )
                    fixed_path = filepath.replace(".mp4", "_fixed.mp4")
                    # Remux the file to repair its container.
                    fix_cmd = [ffmpeg_exe, "-y", "-i", filepath, "-c", "copy", "-map", "0:v", "-map", "0:a?", fixed_path]
                    fix_res = subprocess.run(
                        fix_cmd,
                        capture_output=True,
                        creationflags=SUBPROCESS_CREATION_FLAGS,
                    )
                    
                    if fix_res.returncode == 0 and os.path.exists(fixed_path) and os.path.getsize(fixed_path) > 1000000:
                        os.remove(filepath)
                        os.rename(fixed_path, filepath)
                        log.success('  [franime] ✓ Repair successful.')
                    else:
                        if os.path.exists(fixed_path): os.remove(fixed_path)
                        log.error('  [franime] ✗ Repair failed. Removing file before retry.')
                        os.remove(filepath)
                        raise Exception("Video is corrupted and cannot be repaired.")

                return {
                    "success": True,
                    "filename": os.path.basename(filepath),
                    "filepath": filepath,
                    "folder": os.path.basename(output_path)
                }
        except Exception as e:
            log.error('  [franime] Download or repair error: %s', e)
            if 'filepath' in locals() and filepath and os.path.exists(filepath):
                os.remove(filepath)
            raise e

    return {"success": False, "error": "Download failed after all attempts."}


def _find_chrome() -> str | None:
    path = find_chrome_binary()
    return str(path) if path else None


def _chrome_user_data_dir() -> str | None:
    """Return Chrome's real user profile (for copying cookies), not DowFlow's profile."""
    import platform
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    return os.path.expanduser("~/.config/google-chrome")


def _resolve_ffmpeg_dir_proxy() -> str | None:
    return _resolve_ffmpeg_dir()
