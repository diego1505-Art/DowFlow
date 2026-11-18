import { useCallback, useEffect, useRef, useState } from "react";
import {
  addLocalMusicFavorite,
  addMusicFavorite,
  fetchLocalMusicFavorites,
  fetchMusicDownloadJob,
  fetchMusicFavorites,
  fetchMusicLibrary,
  removeLocalMusicFavorite,
  removeMusicFavorite,
  startMusicDownload,
} from "./musicApi";
import type { LocalMusicFile, StoredMusicFavorite } from "./musicApi";
import { searchMusicTracks } from "./youtube/musicSearch";
import type { MusicTrack } from "./types";

type MusicRoute = "home" | "stream" | "library" | "favorites";
type DownloadUiState =
  | { status: "queued"; message?: string }
  | { status: "progress"; progress: number | null; message?: string }
  | { status: "done"; message: string }
  | { status: "error"; message: string };
type PlaybackItem =
  | { kind: "youtube"; uiId: string; track: MusicTrack }
  | { kind: "local"; uiId: string; file: LocalMusicFile };

function routeFromPath(pathname: string): MusicRoute {
  if (pathname === "/music/stream") return "stream";
  if (pathname === "/music/explore") return "library";
  if (pathname === "/music/liked") return "favorites";
  return "home";
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function waitForNextPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 1200);
    signal.addEventListener("abort", finish, { once: true });
  });
}

function artistLine(track: MusicTrack): string {
  return track.artists.map((artist) => artist.name).filter(Boolean).join(", ") || "Artiste inconnu";
}

function itemTitle(item: PlaybackItem): string {
  return item.kind === "youtube" ? item.track.title : item.file.title;
}

function itemArtist(item: PlaybackItem): string {
  return item.kind === "youtube" ? artistLine(item.track) : item.file.artist || "Artiste inconnu";
}

function itemCover(item: PlaybackItem): string {
  return item.kind === "youtube" ? item.track.cover.url : item.file.cover_url ?? "";
}

function itemDuration(item: PlaybackItem): number {
  return item.kind === "youtube" ? item.track.durationMs : 0;
}

function youtubeItem(track: MusicTrack): PlaybackItem {
  return { kind: "youtube", uiId: `youtube:${track.id}`, track };
}

function localItem(file: LocalMusicFile): PlaybackItem {
  return { kind: "local", uiId: `local:${file.filename}`, file };
}

function favoriteToTrack(favorite: StoredMusicFavorite): MusicTrack {
  return {
    id: favorite.track_id,
    title: favorite.title,
    artists: [{ id: "", name: favorite.artist || "Artiste inconnu" }],
    durationMs: favorite.duration_ms ?? 0,
    cover: { url: favorite.cover_url ?? "", width: 0, height: 0 },
  };
}

function localErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Impossible de charger la bibliothèque locale.";
  if (message.includes("(409")) {
    return `La bibliothèque locale est temporairement indisponible. ${message}`;
  }
  return message;
}

export default function MusicApp() {
  const [route, setRoute] = useState<MusicRoute>(() => routeFromPath(window.location.pathname));
  const [query, setQuery] = useState("");
  const [libraryFilter, setLibraryFilter] = useState("");
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [searchError, setSearchError] = useState("");
  const [library, setLibrary] = useState<LocalMusicFile[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [libraryError, setLibraryError] = useState("");
  const [youtubeFavorites, setYoutubeFavorites] = useState<StoredMusicFavorite[]>([]);
  const [localFavoriteFiles, setLocalFavoriteFiles] = useState<string[]>([]);
  const [favoritesLoading, setFavoritesLoading] = useState(true);
  const [favoritesError, setFavoritesError] = useState("");
  const [favoriteBusyIds, setFavoriteBusyIds] = useState<Set<string>>(() => new Set());
  const [favoriteActionError, setFavoriteActionError] = useState("");
  const [downloadStates, setDownloadStates] = useState<Record<string, DownloadUiState>>({});
  const [currentItem, setCurrentItem] = useState<PlaybackItem | null>(null);
  const [playbackState, setPlaybackState] = useState<"idle" | "resolving" | "ready" | "playing" | "paused" | "error">("idle");
  const [playbackMessage, setPlaybackMessage] = useState("Choisis un titre pour commencer.");
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seekDraft, setSeekDraft] = useState<number | null>(null);
  const [volume, setVolume] = useState(0.8);
  const audioRef = useRef<HTMLAudioElement>(null);
  const searchController = useRef<AbortController | null>(null);
  const libraryController = useRef<AbortController | null>(null);
  const playbackController = useRef<AbortController | null>(null);
  const downloadControllers = useRef(new Map<string, AbortController>());
  const activeDownloadIds = useRef(new Set<string>());
  const mountedRef = useRef(true);
  const electronReady = Boolean(window.dowflow?.youtube?.mintPoToken);

  const loadLibrary = useCallback(async () => {
    libraryController.current?.abort();
    const controller = new AbortController();
    libraryController.current = controller;
    setLibraryLoading(true);
    setLibraryError("");
    try {
      const items = await fetchMusicLibrary(controller.signal);
      if (!controller.signal.aborted) setLibrary(items);
    } catch (error) {
      if (!controller.signal.aborted) setLibraryError(localErrorMessage(error));
    } finally {
      if (!controller.signal.aborted) setLibraryLoading(false);
    }
  }, []);

  const loadFavorites = useCallback(async () => {
    setFavoritesLoading(true);
    setFavoritesError("");
    try {
      const [streamItems, localItems] = await Promise.all([
        fetchMusicFavorites(),
        fetchLocalMusicFavorites(),
      ]);
      setYoutubeFavorites(streamItems.filter((item) => item.source === "youtube"));
      setLocalFavoriteFiles(localItems);
    } catch (error) {
      setFavoritesError(error instanceof Error ? error.message : "Impossible de charger les favoris.");
    } finally {
      setFavoritesLoading(false);
    }
  }, []);

  useEffect(() => {
    const onPopState = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (route !== "stream") void loadLibrary();
  }, [route, loadLibrary]);

  useEffect(() => {
    void loadFavorites();
  }, [loadFavorites]);

  useEffect(() => {
    const refreshOnReturn = () => {
      if (document.visibilityState !== "hidden" && route !== "stream") void loadLibrary();
      if (document.visibilityState !== "hidden" && route === "favorites") void loadFavorites();
    };
    window.addEventListener("focus", refreshOnReturn);
    window.addEventListener("pageshow", refreshOnReturn);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      window.removeEventListener("pageshow", refreshOnReturn);
    };
  }, [route, loadLibrary, loadFavorites]);

  useEffect(() => {
    const normalized = query.trim();
    searchController.current?.abort();
    if (normalized.length < 2) {
      setTracks([]);
      setSearchError("");
      setSearchState("idle");
      return;
    }

    const controller = new AbortController();
    searchController.current = controller;
    const timer = window.setTimeout(() => {
      setSearchState("loading");
      setSearchError("");
      void searchMusicTracks(normalized, controller.signal)
        .then((results) => {
          if (controller.signal.aborted) return;
          setTracks(results);
          setSearchState("done");
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setSearchError(error instanceof Error ? error.message : "La recherche a échoué.");
          setSearchState("error");
        });
    }, 420);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = volume;
    const updateTime = () => setPosition(audio.currentTime || 0);
    const updateDuration = () => setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    const onPlay = () => {
      setPlaybackState("playing");
      setPlaybackMessage("Lecture en cours");
    };
    const onPause = () => {
      if (audio.currentTime > 0 && !audio.ended) {
        setPlaybackState("paused");
        setPlaybackMessage("En pause");
      }
    };
    const onEnded = () => {
      setPlaybackState("paused");
      setPlaybackMessage("Titre terminé");
    };
    const onError = () => {
      if (!audio.error) return;
      setPlaybackState("error");
      setPlaybackMessage("Le fichier ou flux audio n’a pas pu être lu. Réessaie ou choisis un autre titre.");
    };
    audio.addEventListener("timeupdate", updateTime);
    audio.addEventListener("durationchange", updateDuration);
    audio.addEventListener("loadedmetadata", updateDuration);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    return () => {
      audio.removeEventListener("timeupdate", updateTime);
      audio.removeEventListener("durationchange", updateDuration);
      audio.removeEventListener("loadedmetadata", updateDuration);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
    };
  }, [volume]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      searchController.current?.abort();
      libraryController.current?.abort();
      playbackController.current?.abort();
      for (const controller of downloadControllers.current.values()) controller.abort();
      downloadControllers.current.clear();
    };
  }, []);

  function navigate(path: string): void {
    if (window.location.pathname === path) return;
    window.history.pushState({}, "", path);
    setRoute(routeFromPath(path));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function onInternalLink(event: React.MouseEvent<HTMLAnchorElement>): void {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = event.currentTarget;
    if (target.target && target.target !== "_self") return;
    const url = new URL(target.href, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/music")) return;
    event.preventDefault();
    navigate(url.pathname);
  }

  async function chooseTrack(item: PlaybackItem): Promise<void> {
    playbackController.current?.abort();
    const controller = new AbortController();
    playbackController.current = controller;
    const audio = audioRef.current;
    audio?.pause();
    setCurrentItem(item);
    setPlaybackState(item.kind === "youtube" ? "resolving" : "ready");
    setPlaybackMessage(item.kind === "youtube" ? "Préparation du flux audio…" : "Ouverture du fichier local…");
    setPosition(0);
    setDuration(0);

    try {
      let url: string;
      if (item.kind === "youtube") {
        const { resolveMusicStream } = await import("./youtube/musicPlayback");
        url = await resolveMusicStream(item.track, controller.signal);
      } else {
        url = new URL(item.file.audio_url, window.location.href).toString();
      }
      if (controller.signal.aborted) return;
      if (!audio) throw new Error("Le lecteur audio n’est pas disponible.");
      audio.src = url;
      audio.load();
      setPlaybackState("ready");
      setPlaybackMessage(item.kind === "local" ? "Fichier local prêt à la lecture." : "Flux prêt — appuie sur Lecture.");
      try {
        await audio.play();
      } catch {
        // L’utilisateur peut devoir confirmer la lecture avec le bouton du lecteur.
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setPlaybackState("error");
      setPlaybackMessage(error instanceof Error ? error.message : "Impossible de préparer la lecture.");
    }
  }

  async function togglePlayback(): Promise<void> {
    const audio = audioRef.current;
    if (!audio || !currentItem || playbackState === "resolving") return;
    if (audio.paused) {
      if (!audio.src) {
        await chooseTrack(currentItem);
        return;
      }
      try {
        await audio.play();
      } catch {
        setPlaybackMessage("La lecture a été bloquée. Réessaie avec le bouton Lecture.");
      }
    } else {
      audio.pause();
    }
  }

  function commitSeek(): void {
    const audio = audioRef.current;
    if (!audio || seekDraft === null || !Number.isFinite(audio.duration) || audio.seekable.length === 0) {
      setSeekDraft(null);
      return;
    }
    const target = Math.max(0, Math.min(seekDraft, audio.duration));
    let seekable = false;
    for (let index = 0; index < audio.seekable.length; index += 1) {
      if (target >= audio.seekable.start(index) - 0.25 && target <= audio.seekable.end(index) + 0.25) {
        seekable = true;
        break;
      }
    }
    if (seekable) {
      try {
        audio.currentTime = target;
      } catch {
        setPlaybackMessage("Cette position n’est pas encore disponible dans le flux.");
      }
    } else {
      setPlaybackMessage("Cette position n’est pas encore disponible dans le flux.");
    }
    setSeekDraft(null);
  }

  function markFavoriteBusy(uiId: string, busy: boolean): void {
    setFavoriteBusyIds((current) => {
      const next = new Set(current);
      if (busy) next.add(uiId);
      else next.delete(uiId);
      return next;
    });
  }

  async function toggleFavorite(item: PlaybackItem): Promise<void> {
    if (favoritesLoading || favoriteBusyIds.has(item.uiId)) return;
    const isFavorite = item.kind === "youtube"
      ? youtubeFavorites.some((favorite) => favorite.track_id === item.track.id)
      : localFavoriteFiles.includes(item.file.filename);
    markFavoriteBusy(item.uiId, true);
    setFavoriteActionError("");
    try {
      if (item.kind === "youtube") {
        if (isFavorite) {
          await removeMusicFavorite(item.track.id);
          setYoutubeFavorites((items) => items.filter((favorite) => favorite.track_id !== item.track.id));
        } else {
          const record: StoredMusicFavorite = {
            source: "youtube",
            track_id: item.track.id,
            title: item.track.title,
            artist: artistLine(item.track),
            cover_url: item.track.cover.url || null,
            duration_ms: item.track.durationMs,
            created_at: Date.now() / 1000,
          };
          await addMusicFavorite({
            source: "youtube",
            track_id: record.track_id,
            title: record.title,
            artist: record.artist,
            cover_url: record.cover_url ?? "",
            duration_ms: record.duration_ms ?? 0,
          });
          setYoutubeFavorites((items) => [record, ...items.filter((favorite) => favorite.track_id !== item.track.id)]);
        }
      } else if (isFavorite) {
        await removeLocalMusicFavorite(item.file.filename);
        setLocalFavoriteFiles((items) => items.filter((filename) => filename !== item.file.filename));
      } else {
        await addLocalMusicFavorite(item.file.filename);
        setLocalFavoriteFiles((items) => [item.file.filename, ...items.filter((filename) => filename !== item.file.filename)]);
      }
      setFavoritesError("");
    } catch (error) {
      setFavoriteActionError(error instanceof Error ? error.message : "La modification du favori a échoué.");
    } finally {
      markFavoriteBusy(item.uiId, false);
    }
  }

  async function downloadTrack(track: MusicTrack): Promise<void> {
    const trackId = track.id;
    if (activeDownloadIds.current.has(trackId)) return;
    activeDownloadIds.current.add(trackId);
    setDownloadStates((current) => ({ ...current, [trackId]: { status: "queued", message: "Mise en file…" } }));
    let controller: AbortController | null = null;
    try {
      const started = await startMusicDownload({ id: track.id, title: track.title, artist: artistLine(track) });
      if (!mountedRef.current) return;
      controller = new AbortController();
      downloadControllers.current.set(trackId, controller);
      const pollDeadline = Date.now() + 60 * 60 * 1000;
      while (!controller.signal.aborted) {
        if (Date.now() >= pollDeadline) throw new Error("Le suivi du téléchargement a dépassé une heure.");
        const job = await fetchMusicDownloadJob(started.job_id, controller.signal);
        if (controller.signal.aborted || !mountedRef.current) return;
        const progress = typeof job.progress === "number" && Number.isFinite(job.progress)
          ? Math.max(0, Math.min(100, job.progress))
          : null;
        if (job.status === "success") {
          setDownloadStates((current) => ({
            ...current,
            [trackId]: { status: "done", message: job.message || "Disponible dans la bibliothèque locale." },
          }));
          void loadLibrary();
          return;
        }
        if (job.status === "failed" || job.status === "skipped") {
          setDownloadStates((current) => ({
            ...current,
            [trackId]: { status: "error", message: job.error || job.message || "Le téléchargement n’a pas abouti." },
          }));
          return;
        }
        setDownloadStates((current) => ({
          ...current,
          [trackId]: { status: "progress", progress, message: job.message || undefined },
        }));
        await waitForNextPoll(controller.signal);
      }
    } catch (error) {
      if (controller?.signal.aborted || !mountedRef.current) return;
      const message = error instanceof Error ? error.message : "Le téléchargement a échoué.";
      setDownloadStates((current) => ({
        ...current,
        [trackId]: {
          status: "error",
          message: message.includes("Choose a download folder first.")
            ? "Choisis d’abord un dossier de téléchargement dans DowFlow."
            : message,
        },
      }));
    } finally {
      if (controller && downloadControllers.current.get(trackId) === controller) {
        downloadControllers.current.delete(trackId);
      }
      activeDownloadIds.current.delete(trackId);
    }
  }

  function renderTrackRows(items: PlaybackItem[], listKind: string) {
    return (
      <div className="track-list">
        {items.map((item, index) => {
          const isFavorite = item.kind === "youtube"
            ? youtubeFavorites.some((favorite) => favorite.track_id === item.track.id)
            : localFavoriteFiles.includes(item.file.filename);
          const busy = favoriteBusyIds.has(item.uiId);
          const disabled = busy || favoritesLoading;
          const download = item.kind === "youtube" ? downloadStates[item.track.id] : undefined;
          const downloadBusy = download?.status === "queued" || download?.status === "progress";
          const downloadLabel = download?.status === "done" ? "Retélécharger" : download?.status === "error" ? "Réessayer le téléchargement" : "Télécharger en MP3";
          const cover = itemCover(item);
          const artist = itemArtist(item);
          return (
            <article className={`track-row ${currentItem?.uiId === item.uiId ? "is-current" : ""}`} key={`${listKind}-${item.uiId}`}>
              <span className="track-index">{String(index + 1).padStart(2, "0")}</span>
              <div className="cover-wrap">
                {cover && <img src={cover} alt="" loading="lazy" />}
                <button type="button" className="cover-play" onClick={() => void chooseTrack(item)} aria-label={`Lire ${itemTitle(item)}`}>
                  {currentItem?.uiId === item.uiId && playbackState === "playing" ? "Ⅱ" : "▶"}
                </button>
              </div>
              <div className="track-copy">
                <strong title={itemTitle(item)}>{itemTitle(item)}</strong>
                <span title={artist}>{artist}{item.kind === "local" ? <b className="source-tag">LOCAL</b> : item.track.explicit ? <b className="explicit-tag">E</b> : null}</span>
                {download && <span className={`track-download-status is-${download.status}`} role={download.status === "error" ? "alert" : "status"}>
                  {download.status === "queued" ? download.message || "En attente…"
                    : download.status === "progress" ? `${download.progress === null ? "Téléchargement…" : `${Math.floor(download.progress)}%`}${download.message ? ` — ${download.message}` : ""}`
                      : download.status === "done" ? download.message
                        : `Échec : ${download.message}`}
                </span>}
              </div>
              <span className="track-duration">{itemDuration(item) ? formatTime(itemDuration(item) / 1000) : "—"}</span>
              <div className="track-actions">
                {item.kind === "youtube" && <button
                  type="button"
                  className={`download-toggle ${download?.status === "done" ? "is-done" : ""} ${download?.status === "error" ? "is-error" : ""}`}
                  onClick={() => void downloadTrack(item.track)}
                  disabled={downloadBusy}
                  aria-label={`${downloadBusy ? "Téléchargement en cours" : downloadLabel} : ${itemTitle(item)}`}
                  title={downloadBusy ? "Téléchargement en cours" : downloadLabel}
                >
                  {downloadBusy ? <i className="spinner" aria-hidden="true" /> : download?.status === "done" ? "↻" : download?.status === "error" ? "↻" : "↓"}
                </button>}
                <button
                  type="button"
                  className={`favorite-toggle ${isFavorite ? "is-favorite" : ""}`}
                  onClick={() => void toggleFavorite(item)}
                  disabled={disabled}
                  aria-label={`${isFavorite ? "Retirer des" : "Ajouter aux"} favoris : ${itemTitle(item)}`}
                  aria-pressed={isFavorite}
                  title={isFavorite ? "Retirer des favoris" : "Ajouter aux favoris"}
                >
                  {disabled ? <i className="spinner" aria-hidden="true" /> : isFavorite ? "★" : "☆"}
                </button>
                <button type="button" className="row-play" onClick={() => void chooseTrack(item)} aria-label={`Écouter ${itemTitle(item)}`}>Lire</button>
              </div>
            </article>
          );
        })}
      </div>
    );
  }

  const isPlaying = playbackState === "playing";
  const displayedPosition = seekDraft ?? position;
  const canSeek = duration > 0 && Boolean(audioRef.current?.seekable.length);
  const favoriteItems: PlaybackItem[] = [
    ...youtubeFavorites.map((favorite) => youtubeItem(favoriteToTrack(favorite))),
    ...library.filter((file) => localFavoriteFiles.includes(file.filename)).map(localItem),
  ];
  const recentLocalItems = [...library].sort((a, b) => b.mtime - a.mtime).slice(0, 5).map(localItem);
  const filteredLibrary = library.filter((file) => {
    const needle = libraryFilter.trim().toLocaleLowerCase();
    return !needle || `${file.title} ${file.artist} ${file.filename}`.toLocaleLowerCase().includes(needle);
  }).map(localItem);
  const headings: Record<MusicRoute, { eyebrow: string; lead: string; emphasis: string; copy: string }> = {
    home: { eyebrow: "VOTRE MUSIQUE", lead: "La musique,", emphasis: "sans détour.", copy: "Retrouve ta collection locale ou pars à la découverte de nouveaux titres." },
    stream: { eyebrow: "DÉCOUVRIR · ÉCOUTER", lead: "À écouter,", emphasis: "en streaming.", copy: "Recherche des titres YouTube Music et lance l’écoute directement." },
    library: { eyebrow: "COLLECTION LOCALE", lead: "Ta bibliothèque,", emphasis: "à portée.", copy: "Parcours et écoute les fichiers audio déjà présents dans DowFlow." },
    favorites: { eyebrow: "VOTRE SÉLECTION", lead: "Tes favoris,", emphasis: "réunis.", copy: "Tes titres YouTube Music et tes fichiers locaux préférés, au même endroit." },
  };
  const heading = headings[route];

  return (
    <div className="music-app">
      <header className="topbar">
        <a className="brand" href="/music" onClick={onInternalLink} aria-label="Retour à DowFlow Music">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>DowFlow</strong><small>Music</small></span>
        </a>
        <div className="topbar-right">
          <span className={`connection-pill ${electronReady ? "is-ready" : "is-warning"}`}>
            <i />{electronReady ? "Electron connecté" : "Shell Electron requis pour YouTube"}
          </span>
        </div>
      </header>

      <main className="content">
        <section className={`intro ${route === "home" ? "intro-home" : ""}`}>
          <p className="eyebrow">{heading.eyebrow}</p>
          <h1>{heading.lead} <em>{heading.emphasis}</em></h1>
          <p className="intro-copy">{heading.copy}</p>
          <nav className="music-tabs" aria-label="Sections Music">
            <a href="/music" onClick={onInternalLink} aria-current={route === "home" ? "page" : undefined} className={route === "home" ? "is-active" : ""}>Accueil</a>
            <a href="/music/stream" onClick={onInternalLink} aria-current={route === "stream" ? "page" : undefined} className={route === "stream" ? "is-active" : ""}>Streaming</a>
            <a href="/music/explore" onClick={onInternalLink} aria-current={route === "library" ? "page" : undefined} className={route === "library" ? "is-active" : ""}>Bibliothèque</a>
            <a href="/music/liked" onClick={onInternalLink} aria-current={route === "favorites" ? "page" : undefined} className={route === "favorites" ? "is-active" : ""}>Favoris <span>{youtubeFavorites.length + localFavoriteFiles.length}</span></a>
          </nav>
          {route === "stream" && <>
            <form className="search-box" onSubmit={(event) => event.preventDefault()} role="search">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></svg>
              <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Titre, artiste…" aria-label="Rechercher un titre ou un artiste" autoComplete="off" />
              {query && <button className="clear-search" type="button" onClick={() => setQuery("")} aria-label="Effacer la recherche">×</button>}
              <span className="search-hint">Recherche YouTube Music</span>
            </form>
            {!electronReady && <div className="notice">La lecture en streaming nécessite le shell Electron DowFlow. Les titres de la bibliothèque locale se lisent directement dans le navigateur.</div>}
            <p className="download-note">Télécharge uniquement les pistes que tu as le droit de conserver.</p>
          </>}
        </section>

        {route === "home" && <section className="results-section" aria-label="Accueil Music">
          <div className="home-shortcuts">
            <a href="/music/stream" onClick={onInternalLink}><span>01</span><strong>Découvrir en streaming</strong><small>Recherche YouTube Music</small><b aria-hidden="true">↗</b></a>
            <a href="/music/explore" onClick={onInternalLink}><span>02</span><strong>Ouvrir la bibliothèque</strong><small>{library.length} fichier{library.length === 1 ? "" : "s"} local{library.length === 1 ? "" : "aux"}</small><b aria-hidden="true">↗</b></a>
          </div>
          <div className="results-heading home-heading"><div><p className="eyebrow">AJOUTS RÉCENTS</p><h2>Dans votre collection</h2></div><a className="section-link" href="/music/explore" onClick={onInternalLink}>Toute la bibliothèque <span>→</span></a></div>
          {libraryLoading && <p className="loading-label"><i className="spinner" />Chargement de la bibliothèque…</p>}
          {libraryError && <div className="message-state is-error" role="alert"><strong>La bibliothèque locale n’est pas disponible.</strong><p>{libraryError}</p><button type="button" className="retry-favorites" onClick={() => void loadLibrary()}>Réessayer</button></div>}
          {!libraryLoading && !libraryError && recentLocalItems.length === 0 && <div className="empty-state compact"><strong>Aucun fichier musical local</strong><p>Les fichiers disponibles dans DowFlow apparaîtront ici.</p></div>}
          {recentLocalItems.length > 0 && renderTrackRows(recentLocalItems, "home-recent")}
        </section>}

        {route === "stream" && <section className="results-section" id="music-panel" aria-label="Résultats de recherche" aria-live="polite">
          <div className="results-heading"><div><p className="eyebrow">YOUTUBE MUSIC</p><h2>{query.trim().length >= 2 ? "Résultats" : "À vous de choisir"}</h2></div>
            {searchState === "loading" && <span className="loading-label"><i className="spinner" />Recherche…</span>}
            {searchState === "done" && tracks.length > 0 && <span className="result-count">{tracks.length} titres</span>}
          </div>
          {searchState === "idle" && <div className="empty-state"><span className="empty-orbit"><i /><i /><i /></span><strong>Une recherche, et c’est parti.</strong><p>Saisis au moins deux caractères pour trouver des titres.</p></div>}
          {searchState === "error" && <div className="message-state is-error"><strong>La recherche n’a pas abouti.</strong><p>{searchError}</p></div>}
          {searchState === "done" && tracks.length === 0 && <div className="empty-state compact"><strong>Aucun titre trouvé</strong><p>Essaie avec un autre titre ou le nom de l’artiste.</p></div>}
          {tracks.length > 0 && renderTrackRows(tracks.map(youtubeItem), "stream")}
          {favoriteActionError && <p className="api-action-error" role="alert">Action sur le favori impossible : {favoriteActionError}</p>}
        </section>}

        {route === "library" && <section className="results-section" aria-label="Bibliothèque locale">
          <div className="results-heading"><div><p className="eyebrow">FICHIERS DOWFLOW</p><h2>Bibliothèque</h2></div><div className="favorites-heading-actions"><span className="result-count">{library.length} fichier{library.length === 1 ? "" : "s"}</span><button type="button" className="refresh-favorites" onClick={() => void loadLibrary()} disabled={libraryLoading}>{libraryLoading ? <i className="spinner" /> : "Actualiser"}</button></div></div>
          <div className="library-tools"><label className="library-filter"><span className="visually-hidden">Filtrer la bibliothèque</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></svg><input type="search" value={libraryFilter} onChange={(event) => setLibraryFilter(event.target.value)} placeholder="Filtrer par titre ou artiste…" /></label><a className="legacy-link" href="/music/explore/legacy">Ouvrir l’ancien explorateur et ses téléchargements <span>↗</span></a></div>
          <p className="legacy-note">L’ancien explorateur s’ouvre en dehors de ce lecteur. La lecture en cours ne survit pas à cette navigation.</p>
          {libraryLoading && <p className="loading-label"><i className="spinner" />Chargement de la bibliothèque…</p>}
          {libraryError && <div className="message-state is-error" role="alert"><strong>La bibliothèque n’a pas pu être chargée.</strong><p>{libraryError}</p><button type="button" className="retry-favorites" onClick={() => void loadLibrary()} disabled={libraryLoading}>Réessayer</button></div>}
          {!libraryLoading && !libraryError && filteredLibrary.length === 0 && <div className="empty-state compact"><strong>{library.length ? "Aucun résultat" : "La bibliothèque est vide"}</strong><p>{library.length ? "Essaie un autre titre ou artiste." : "Les fichiers audio locaux apparaîtront ici lorsqu’ils seront disponibles."}</p></div>}
          {!libraryError && filteredLibrary.length > 0 && renderTrackRows(filteredLibrary, "library")}
          {favoriteActionError && <p className="api-action-error" role="alert">Action sur le favori impossible : {favoriteActionError}</p>}
        </section>}

        {route === "favorites" && <section className="results-section" aria-label="Favoris Music">
          <div className="results-heading"><div><p className="eyebrow">YOUTUBE + LOCAL</p><h2>Favoris</h2></div><div className="favorites-heading-actions">{favoritesLoading && <span className="loading-label"><i className="spinner" />Chargement…</span>}{!favoritesLoading && <button type="button" className="refresh-favorites" onClick={() => { void loadFavorites(); void loadLibrary(); }}>Actualiser</button>}</div></div>
          {favoritesError && <div className="message-state is-error" role="alert"><strong>Une source de favoris n’a pas pu être chargée.</strong><p>{favoritesError}</p><button type="button" className="retry-favorites" onClick={() => { void loadFavorites(); void loadLibrary(); }} disabled={favoritesLoading}>Réessayer</button></div>}
          {libraryError && <p className="inline-warning" role="status">La bibliothèque locale n’a pas pu être résolue : {libraryError}</p>}
          {!favoritesError && !favoritesLoading && favoriteItems.length === 0 && <div className="empty-state compact"><strong>Aucun favori pour le moment</strong><p>Ajoute des titres depuis le streaming ou la bibliothèque locale.</p></div>}
          {favoriteItems.length > 0 && renderTrackRows(favoriteItems, "favorites")}
          {favoriteActionError && <p className="api-action-error" role="alert">Action sur le favori impossible : {favoriteActionError}</p>}
        </section>}
      </main>

      <footer className="player-bar">
        <div className="now-playing">
          {currentItem && itemCover(currentItem) ? <img className="player-cover" src={itemCover(currentItem)} alt="" /> : <div className="player-cover placeholder-cover"><span>DF</span></div>}
          <div className="now-copy"><strong title={currentItem ? itemTitle(currentItem) : undefined}>{currentItem ? itemTitle(currentItem) : "Aucun titre sélectionné"}</strong><span title={currentItem ? itemArtist(currentItem) : undefined}>{currentItem ? itemArtist(currentItem) : "Choisis un résultat pour commencer"}</span></div>
        </div>
        <div className="player-center">
          <div className="player-controls"><button type="button" className="control-button play-toggle" onClick={() => void togglePlayback()} disabled={!currentItem || playbackState === "resolving"} aria-label={isPlaying ? "Mettre en pause" : "Lire"}>{playbackState === "resolving" ? <i className="spinner dark" /> : isPlaying ? "Ⅱ" : "▶"}</button></div>
          <div className="timeline"><span>{formatTime(displayedPosition)}</span><input type="range" min="0" max={duration || 0} step="0.25" value={Math.min(displayedPosition, duration || 0)} disabled={!canSeek} aria-label="Position de lecture" onChange={(event) => setSeekDraft(Number(event.target.value))} onPointerUp={commitSeek} onKeyUp={commitSeek} /><span>{formatTime(duration)}</span></div>
        </div>
        <div className="player-status"><span className={`status-dot ${playbackState}`} /><p title={playbackMessage}>{playbackMessage}</p><label className="volume-control" aria-label="Volume"><span>Vol.</span><input type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => setVolume(Number(event.target.value))} /></label></div>
      </footer>
      <audio ref={audioRef} preload="metadata" crossOrigin="anonymous" />
    </div>
  );
}
