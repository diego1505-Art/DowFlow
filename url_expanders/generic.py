"""Fallback générique : tenter d'étendre une playlist via yt-dlp pour tout domaine."""
from __future__ import annotations

from typing import Any

from .base import ExpandResult, OptionDef, SiteProfile
from utils import yt_dlp_runtime_options


def supports(url: str, host: str) -> bool:
    # Toujours candidat en dernier recours
    return True


def profile_for(url: str, host: str) -> SiteProfile | None:
    # Ne s'affiche que si aucun expander spécialisé n'a matché
    # (appelé depuis detect_profile qui itère dans l'ordre — youtube/franime retournent avant)
    # Ici on retourne toujours un profil générique quand on est le module appelé en dernier.
    label = host or "Remote site"
    return SiteProfile(
        site_id="generic",
        label=label,
        available=True,
        help_text=(
            "Generic site. Search will try to expand a playlist or series "
            "if yt-dlp recognizes it. Otherwise, paste URLs manually."
        ),
        options=[
            OptionDef(
                key="expand_playlist",
                label="Expand if playlist",
                kind="toggle",
                default=True,
                help_text="Use yt-dlp flat-playlist mode when possible.",
            ),
            OptionDef(
                key="max_items",
                label="Item limit",
                kind="number",
                default=30,
                min_value=1,
                max_value=300,
                help_text="Maximum generated URLs.",
            ),
        ],
    )


def expand(url: str, options: dict[str, Any]) -> ExpandResult:
    if not options.get("expand_playlist", True):
        return ExpandResult(
            success=False,
            site_id="generic",
            error="'Expand if playlist' is disabled.",
        )

    try:
        max_items = int(options.get("max_items") or 30)
    except (TypeError, ValueError):
        max_items = 30
    max_items = max(1, min(300, max_items))

    try:
        import yt_dlp
    except ImportError:
        return ExpandResult(success=False, site_id="generic", error="yt-dlp is not installed.")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlistend": max_items,
    }
    ydl_opts.update(yt_dlp_runtime_options())

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return ExpandResult(
            success=False,
            site_id="generic",
            error=f"No automatic expansion for this site ({exc}).",
        )

    if not info:
        return ExpandResult(success=False, site_id="generic", error="No information returned.")

    entries = info.get("entries")
    if not entries:
        return ExpandResult(
            success=False,
            site_id="generic",
            error="This link is not a recognized playlist or series. Add URLs manually.",
        )

    urls: list[str] = []
    for entry in entries:
        if not entry:
            continue
        candidate = entry.get("webpage_url") or entry.get("url")
        if isinstance(candidate, str) and candidate.startswith("http"):
            urls.append(candidate)
        elif entry.get("id") and info.get("extractor"):
            # Best effort
            wid = entry.get("webpage_url")
            if wid:
                urls.append(wid)
        if len(urls) >= max_items:
            break

    if not urls:
        return ExpandResult(success=False, site_id="generic", error="No usable URL found.")

    title = info.get("title") or info.get("extractor") or "Playlist"
    return ExpandResult(
        success=True,
        urls=urls,
        count=len(urls),
        title=f"{title} ({len(urls)} items)",
        site_id="generic",
    )
