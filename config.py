import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_FOLDER = BASE_DIR / "downloads"

# FFmpeg configuration
def _winget_ffmpeg_bins() -> list[Path]:
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    return sorted(root.glob("Gyan.FFmpeg*/ffmpeg-*/bin"), reverse=True)


FFMPEG_FALLBACK_DIRS = _winget_ffmpeg_bins()

# Media settings
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".m4v", ".mov", ".avi", ".flv", ".wmv", ".ts", ".m2ts", ".3gp", ".ogv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".opus", ".ogg", ".flac", ".wma", ".alac", ".aiff", ".oga"}
ALLOWED_LOCAL_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
PREVIEWABLE_EXTENSIONS = {
    ".mp4", ".webm", ".ogv",         # Native HTML5 video
    ".mp3", ".m4a", ".aac",         # Universal audio
    ".ogg", ".opus", ".wav", ".flac", # Firefox/Chrome audio
}

# ── Video output formats ─────────────────────────────────────────────────────
#   key → {"label", "ext", "container", "merge": bool,
#          "aext":  yt-dlp audio extension [ext=...] (e.g. "m4a", "opus", None=auto)
#          "vext":  yt-dlp video extension [ext=...] (e.g. "mp4", "webm", None=auto)
#          Legacy "vcodec"/"acodec" names are kept for one release for compatibility.
VIDEO_OUTPUT_FORMATS: dict = {
    "best":   {"label": "Auto (best available)",    "ext": None,  "container": None,   "merge": True,  "aext": None, "vext": None, "acodec": None, "vcodec": None},
    "mp4":    {"label": "MP4 (universal)",          "ext": ".mp4", "container": "mp4",  "merge": True,  "aext": "m4a","vext": "mp4","acodec": "m4a","vcodec": "mp4"},
    "mkv":    {"label": "MKV (matroska)",           "ext": ".mkv", "container": "mkv",  "merge": True,  "aext": None, "vext": None, "acodec": None, "vcodec": None},
    "webm":   {"label": "WebM (open format)",       "ext": ".webm","container": "webm", "merge": True,  "aext": "opus","vext":"webm","acodec": "opus","vcodec": "webm"},
    "mov":    {"label": "MOV (QuickTime)",          "ext": ".mov", "container": "mov",  "merge": True,  "aext": None, "vext": None, "acodec": None, "vcodec": None},
    "avi":    {"label": "AVI (legacy)",             "ext": ".avi", "container": "avi",  "merge": False, "aext": None, "vext": None, "acodec": None, "vcodec": None},
}

# ── Audio output formats ─────────────────────────────────────────────────────
#   key → {"label", "ext", "codec", "quality": str|int (bitrate kbps ou 0=best)}
AUDIO_OUTPUT_FORMATS: dict = {
    "best":  {"label": "Auto (best available)",    "ext": None,   "codec": None,  "quality": 0},
    "mp3":   {"label": "MP3 (192 kbps)",           "ext": ".mp3", "codec": "mp3", "quality": 192},
    "mp3_320":{"label": "MP3 (320 kbps HQ)",       "ext": ".mp3", "codec": "mp3", "quality": 320},
    "flac":  {"label": "FLAC (lossless)",          "ext": ".flac","codec": "flac","quality": 0},
    "wav":   {"label": "WAV (uncompressed)",       "ext": ".wav", "codec": "wav", "quality": 0},
    "aac":   {"label": "AAC (256 kbps)",           "ext": ".m4a", "codec": "aac", "quality": 256},
    "m4a":   {"label": "M4A (iTunes)",             "ext": ".m4a", "codec": "m4a", "quality": 192},
    "opus":  {"label": "Opus (160 kbps)",          "ext": ".opus","codec": "opus","quality": 160},
    "ogg":   {"label": "OGG Vorbis (192 kbps)",    "ext": ".ogg", "codec": "vorbis","quality": 192},
    "alac":  {"label": "ALAC (lossless Apple)",    "ext": ".m4a", "codec": "alac","quality": 0},
}

# ── Video qualities ──────────────────────────────────────────────────────────
#   key → {"label", "max_height": int|None, "alias": str}
VIDEO_QUALITIES: dict = {
    "best":   {"label": "Auto max",        "max_height": None, "alias": "best"},
    "4320p":  {"label": "8K (4320p)",      "max_height": 4320, "alias": "8k"},
    "2160p":  {"label": "4K UHD (2160p)",  "max_height": 2160, "alias": "ultra"},
    "1440p":  {"label": "QHD (1440p)",     "max_height": 1440, "alias": "qhd"},
    "1080p":  {"label": "Full HD (1080p)", "max_height": 1080, "alias": "high"},
    "720p":   {"label": "HD (720p)",       "max_height": 720,  "alias": "medium"},
    "480p":   {"label": "SD (480p)",       "max_height": 480,  "alias": "low"},
    "360p":   {"label": "360p",            "max_height": 360,  "alias": "360"},
    "240p":   {"label": "240p",            "max_height": 240,  "alias": "240"},
}

# ── Supported languages ──────────────────────────────────────────────────────
#   {code_iso_639_1: {"label": str, "aliases": set[str]}}
LANGUAGES: dict = {
    # ── Franime / French language options ────────────────────────────────
    "vf":     {"label": "French dub",               "aliases": {"vf", "fr-dub", "french-dub"}},
    "vo":     {"label": "French subtitles",         "aliases": {"vo", "vostfr", "vost", "sub", "subs", "fr-sub", "vof"}},
    "fr":     {"label": "French",                  "aliases": {"fr", "fra", "fre", "french"}},
    # ── Other languages ──────────────────────────────────────────────────
    "en":     {"label": "English",                   "aliases": {"en", "eng", "english"}},
    "es":     {"label": "Spanish",                  "aliases": {"es", "spa", "spanish", "castellano"}},
    "de":     {"label": "German",                   "aliases": {"de", "deu", "ger", "german"}},
    "it":     {"label": "Italian",                  "aliases": {"it", "ita", "italian"}},
    "pt":     {"label": "Portuguese",               "aliases": {"pt", "por", "portuguese"}},
    "pt-br":  {"label": "Portuguese (Brazil)",      "aliases": {"pt-br", "pob", "brazilian"}},
    "ru":     {"label": "Russian",                  "aliases": {"ru", "rus", "russian"}},
    "ja":     {"label": "Japanese",                 "aliases": {"ja", "jpn", "japanese", "jp"}},
    "ko":     {"label": "Korean",                   "aliases": {"ko", "kor", "korean"}},
    "zh":     {"label": "Chinese",                  "aliases": {"zh", "chi", "chinese", "cmn", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "zh_cn", "zh_tw"}},
    "ar":     {"label": "Arabic",                   "aliases": {"ar", "ara", "arabic"}},
    "hi":     {"label": "Hindi",                    "aliases": {"hi", "hin", "hindi"}},
    "tr":     {"label": "Turkish",                  "aliases": {"tr", "tur", "turkish"}},
    "pl":     {"label": "Polish",                   "aliases": {"pl", "pol", "polish"}},
    "nl":     {"label": "Dutch",                    "aliases": {"nl", "nld", "dut", "dutch"}},
    "sv":     {"label": "Swedish",                  "aliases": {"sv", "swe", "swedish"}},
    "no":     {"label": "Norwegian",                "aliases": {"no", "nor", "norwegian"}},
    "da":     {"label": "Danish",                   "aliases": {"da", "dan", "danish"}},
    "fi":     {"label": "Finnish",                  "aliases": {"fi", "fin", "finnish"}},
    "cs":     {"label": "Czech",                    "aliases": {"cs", "ces", "cze", "czech"}},
    "hu":     {"label": "Hungarian",                "aliases": {"hu", "hun", "hungarian"}},
    "ro":     {"label": "Romanian",                 "aliases": {"ro", "ron", "rum", "romanian"}},
    "bg":     {"label": "Bulgarian",                "aliases": {"bg", "bul", "bulgarian"}},
    "el":     {"label": "Greek",                    "aliases": {"el", "ell", "gre", "greek"}},
    "he":     {"label": "Hebrew",                   "aliases": {"he", "heb", "hebrew"}},
    "th":     {"label": "Thai",                     "aliases": {"th", "tha", "thai"}},
    "vi":     {"label": "Vietnamese",               "aliases": {"vi", "vie", "vietnamese"}},
    "id":     {"label": "Indonesian",               "aliases": {"id", "ind", "indonesian"}},
    "ms":     {"label": "Malay",                    "aliases": {"ms", "msa", "may", "malay"}},
    "uk":     {"label": "Ukrainian",                "aliases": {"uk", "ukr", "ukrainian"}},
    "ca":     {"label": "Catalan",                  "aliases": {"ca", "cat", "catalan"}},
    "eu":     {"label": "Basque",                   "aliases": {"eu", "eus", "basque"}},
    "fa":     {"label": "Persian",                  "aliases": {"fa", "fas", "per", "persian"}},
    "ta":     {"label": "Tamil",                    "aliases": {"ta", "tam", "tamil"}},
    "te":     {"label": "Telugu",                   "aliases": {"te", "tel", "telugu"}},
    "bn":     {"label": "Bengali",                  "aliases": {"bn", "ben", "bengali"}},
    "ur":     {"label": "Urdu",                     "aliases": {"ur", "urd", "urdu"}},
    "multi":  {"label": "All languages",            "aliases": {"multi", "all", "multilingual"}},
}


def normalize_language(lang_value: str | None) -> str:
    """Normalize any language input to its canonical ISO code."""
    raw = (lang_value or "").strip().lower()
    if not raw:
        return ""
    if raw in LANGUAGES:
        return raw
    for key, meta in LANGUAGES.items():
        if raw in meta["aliases"]:
            return key
    return raw


def detect_language_from_url(url: str) -> str:
    """Detect a language from a URL parameter, path, or domain."""
    from urllib.parse import parse_qs, urlparse
    _AMBIGUOUS_TOKENS = {"id", "no", "it", "is", "all", "sub", "subs", "multi"}
    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    # 1) Query parameters: ?lang= ?hl= ?language= ?sub_lang= ?audio_language=
    for param in ("lang", "hl", "language", "sub_lang", "sub_language", "audio_language", "alang", "slang"):
        values = parse_qs(parsed.query).get(param)
        if values and values[0]:
            detected = normalize_language(values[0])
            if detected:
                return detected

    # 2) Path: /fr/ /en/ /vostfr/ /vf/ …
    path_lower = parsed.path.lower()
    for key, meta in LANGUAGES.items():
        candidates = {key, *meta["aliases"]}
        for token in candidates:
            if token in _AMBIGUOUS_TOKENS:
                continue
            if len(token) < 2:
                continue
            if f"/{token}/" in path_lower or path_lower.endswith(f"/{token}"):
                return key

    # 3) Subdomain / TLD: fr.youtube.com, example.es…
    host = (parsed.netloc or "").lower()
    for key, meta in LANGUAGES.items():
        candidates = {key, *meta["aliases"]}
        for token in candidates:
            if len(token) != 2:
                continue
            if host.startswith(f"{token}."):
                return key

    return ""


# App settings
LOCAL_MEDIA_TTL_SECONDS = 3600
LOCAL_MEDIA_MAX_ENTRIES = 128

# Browser extractor settings
# Set DOWFLOW_BROWSER_VISIBLE=1 before starting the app if you need to debug the browser.
BROWSER_HEADLESS = os.environ.get("DOWFLOW_BROWSER_VISIBLE", "").strip().lower() not in {"1", "true", "yes", "on"}
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profile"
YOUTUBE_COOKIES_FILE = BASE_DIR / "youtube_cookies.txt"

# ── Performance: number of parallel connections ──────────────────────────────
# Tier selected at startup based on CPU cores and measured network speed:
# 8 / 16 / 32 / 64 / 128. More connections improve throughput for large files
# without overwhelming a modest machine.
# Force a specific value: set DOWFLOW_CONNECTIONS=64
CONNECTIONS_OVERRIDE = os.environ.get("DOWFLOW_CONNECTIONS", "").strip()

# Proxy settings (Optional)
# Format: ["http://user:pass@host:port", "http://host2:port2"]
# Leave empty [] to not use proxies.
# Note: free public proxies often time out; Direct is tried first.
PROXIES = []

# Automatically fetch and validate free public proxies (used by aria2c and
# yt-dlp). Disabled by default because proxies are unstable and may slow down or
# break downloads. Enable explicitly: set DOWFLOW_PROXY_AUTO=1
PROXY_AUTO = os.environ.get("DOWFLOW_PROXY_AUTO", "").strip().lower() in {"1", "true", "yes", "on"}
PROXY_SOURCES = (
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
)
PROXY_VALIDATE_URL = "http://www.gstatic.com/generate_204"
PROXY_VALIDATE_TIMEOUT = 4.0
PROXY_POOL_TTL_SECONDS = 1800.0
