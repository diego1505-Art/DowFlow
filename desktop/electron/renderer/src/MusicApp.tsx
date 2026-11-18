import { useEffect, useRef, useState } from "react";
import { addMusicFavorite, fetchMusicFavorites, removeMusicFavorite } from "./musicApi";
import type { StoredMusicFavorite } from "./musicApi";
import { searchMusicTracks } from "./youtube/musicSearch";
import type { MusicTrack } from "./types";

type MusicView = "search" | "favorites";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function artistLine(track: MusicTrack): string {
  return track.artists.map((artist) => artist.name).filter(Boolean).join(", ") || "Artiste inconnu";
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

export default function MusicApp() {
  const [query, setQuery] = useState("");
  const [view, setView] = useState<MusicView>("search");
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [searchError, setSearchError] = useState("");
  const [favorites, setFavorites] = useState<StoredMusicFavorite[]>([]);
  const [favoritesLoading, setFavoritesLoading] = useState(true);
  const [favoritesError, setFavoritesError] = useState("");
  const [favoriteBusyIds, setFavoriteBusyIds] = useState<Set<string>>(() => new Set());
  const [favoriteActionError, setFavoriteActionError] = useState("");
  const [currentTrack, setCurrentTrack] = useState<MusicTrack | null>(null);
  const [playbackState, setPlaybackState] = useState<"idle" | "resolving" | "ready" | "playing" | "paused" | "error">("idle");
  const [playbackMessage, setPlaybackMessage] = useState("Choisis un titre pour commencer.");
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seekDraft, setSeekDraft] = useState<number | null>(null);
  const [volume, setVolume] = useState(0.8);
  const audioRef = useRef<HTMLAudioElement>(null);
  const searchController = useRef<AbortController | null>(null);
  const playbackController = useRef<AbortController | null>(null);
  const electronReady = Boolean(window.dowflow?.youtube?.mintPoToken);

  async function loadFavorites(signal?: AbortSignal): Promise<void> {
    setFavoritesLoading(true);
    setFavoritesError("");
    try {
      const items = await fetchMusicFavorites(signal);
      if (signal?.aborted) return;
      setFavorites(items.filter((item) => item.source === "youtube"));
    } catch (error) {
      if (signal?.aborted) return;
      setFavoritesError(error instanceof Error ? error.message : "Impossible de charger les favoris.");
    } finally {
      if (!signal?.aborted) setFavoritesLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadFavorites(controller.signal);
    return () => controller.abort();
  }, []);

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
      setPlaybackMessage("Le flux n’a pas pu être lu. Réessaie ou choisis un autre résultat.");
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

  useEffect(() => () => {
    searchController.current?.abort();
    playbackController.current?.abort();
  }, []);

  async function chooseTrack(track: MusicTrack): Promise<void> {
    playbackController.current?.abort();
    const controller = new AbortController();
    playbackController.current = controller;
    setCurrentTrack(track);
    setPlaybackState("resolving");
    setPlaybackMessage("Préparation du flux audio…");
    setPosition(0);
    setDuration(0);

    try {
      const { resolveMusicStream } = await import("./youtube/musicPlayback");
      const url = await resolveMusicStream(track, controller.signal);
      if (controller.signal.aborted) return;
      const audio = audioRef.current;
      if (!audio) throw new Error("Le lecteur audio n’est pas disponible.");
      audio.pause();
      audio.src = url;
      audio.load();
      setPlaybackState("ready");
      setPlaybackMessage("Flux prêt — appuie sur Lecture.");
      try {
        await audio.play();
      } catch {
        // L’utilisateur peut devoir confirmer la lecture avec le bouton du lecteur.
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setPlaybackState("error");
      setPlaybackMessage(error instanceof Error ? error.message : "Impossible de résoudre le flux audio.");
    }
  }

  async function togglePlayback(): Promise<void> {
    const audio = audioRef.current;
    if (!audio || !currentTrack || playbackState === "resolving") return;
    if (audio.paused) {
      if (!audio.src) {
        await chooseTrack(currentTrack);
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

  function markFavoriteBusy(trackId: string, busy: boolean): void {
    setFavoriteBusyIds((current) => {
      const next = new Set(current);
      if (busy) next.add(trackId);
      else next.delete(trackId);
      return next;
    });
  }

  async function toggleFavorite(track: MusicTrack): Promise<void> {
    if (favoritesLoading || favoriteBusyIds.has(track.id)) return;
    const existing = favorites.find((favorite) => favorite.track_id === track.id);
    markFavoriteBusy(track.id, true);
    setFavoriteActionError("");
    try {
      if (existing) {
        await removeMusicFavorite(track.id);
        setFavorites((items) => items.filter((favorite) => favorite.track_id !== track.id));
      } else {
        await addMusicFavorite({
          source: "youtube",
          track_id: track.id,
          title: track.title,
          artist: artistLine(track),
          cover_url: track.cover.url,
          duration_ms: track.durationMs,
        });
        setFavorites((items) => [
          {
            source: "youtube",
            track_id: track.id,
            title: track.title,
            artist: artistLine(track),
            cover_url: track.cover.url,
            duration_ms: track.durationMs,
            created_at: Date.now() / 1000,
          },
          ...items.filter((favorite) => favorite.track_id !== track.id),
        ]);
      }
      setFavoritesError("");
    } catch (error) {
      setFavoriteActionError(error instanceof Error ? error.message : "La modification du favori a échoué.");
    } finally {
      markFavoriteBusy(track.id, false);
    }
  }

  function renderTrackRows(items: MusicTrack[], listKind: "search" | "favorites") {
    return (
      <div className="track-list">
        {items.map((track, index) => {
          const isFavorite = favorites.some((favorite) => favorite.track_id === track.id);
          const busy = favoriteBusyIds.has(track.id);
          const disabled = busy || favoritesLoading;
          return (
            <article className={`track-row ${currentTrack?.id === track.id ? "is-current" : ""}`} key={`${listKind}-${track.id}`}>
              <span className="track-index">{String(index + 1).padStart(2, "0")}</span>
              <div className="cover-wrap">
                {track.cover.url && <img src={track.cover.url} alt="" loading="lazy" />}
                <button type="button" className="cover-play" onClick={() => void chooseTrack(track)} aria-label={`Lire ${track.title}`}>
                  {currentTrack?.id === track.id && playbackState === "playing" ? "Ⅱ" : "▶"}
                </button>
              </div>
              <div className="track-copy">
                <strong title={track.title}>{track.title}</strong>
                <span title={artistLine(track)}>{artistLine(track)}{track.explicit ? <b className="explicit-tag">E</b> : null}</span>
              </div>
              <span className="track-duration">{track.durationMs ? formatTime(track.durationMs / 1000) : "—"}</span>
              <div className="track-actions">
                <button
                  type="button"
                  className={`favorite-toggle ${isFavorite ? "is-favorite" : ""}`}
                  onClick={() => void toggleFavorite(track)}
                  disabled={disabled}
                  aria-label={`${isFavorite ? "Retirer des" : "Ajouter aux"} favoris : ${track.title}`}
                  aria-pressed={isFavorite}
                  title={isFavorite ? "Retirer des favoris" : "Ajouter aux favoris"}
                >
                  {disabled ? <i className="spinner" aria-hidden="true" /> : isFavorite ? "★" : "☆"}
                </button>
                <button type="button" className="row-play" onClick={() => void chooseTrack(track)} aria-label={`Écouter ${track.title}`}>Lire</button>
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
  const favoriteTracks = favorites.map(favoriteToTrack);

  return (
    <div className="music-app">
      <header className="topbar">
        <a className="brand" href="/music" aria-label="Retour à DowFlow Music">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>DowFlow</strong><small>Music</small></span>
        </a>
        <div className="topbar-right">
          <span className={`connection-pill ${electronReady ? "is-ready" : "is-warning"}`}>
            <i />{electronReady ? "Electron connecté" : "Shell Electron requis"}
          </span>
          <a className="back-link" href="/music">Retour à Music</a>
        </div>
      </header>

      <main className="content">
        <section className="intro">
          <p className="eyebrow">DÉCOUVRIR · ÉCOUTER</p>
          <h1>La musique, <em>sans détour.</em></h1>
          <p className="intro-copy">Cherche un titre et lance l’écoute directement. Pas besoin de télécharger avant de lire.</p>
          <div className="music-tabs" role="group" aria-label="Vues de la bibliothèque musicale">
            <button type="button" id="music-tab-search" aria-pressed={view === "search"} aria-controls="music-panel" className={view === "search" ? "is-active" : ""} onClick={() => setView("search")}>Recherche</button>
            <button type="button" id="music-tab-favorites" aria-pressed={view === "favorites"} aria-controls="music-panel" className={view === "favorites" ? "is-active" : ""} onClick={() => setView("favorites")}>Favoris <span>{favorites.length}</span></button>
          </div>
          {view === "search" && <>
          <form className="search-box" onSubmit={(event) => event.preventDefault()} role="search">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></svg>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Titre, artiste…"
              aria-label="Rechercher un titre ou un artiste"
              autoComplete="off"
            />
            {query && <button className="clear-search" type="button" onClick={() => setQuery("")} aria-label="Effacer la recherche">×</button>}
            <span className="search-hint">Recherche directe</span>
          </form>
          {!electronReady && <div className="notice">La recherche peut dépendre de la configuration réseau. La lecture nécessite l’application DowFlow sous Electron.</div>}
          </>}
        </section>

        <section className="results-section" id="music-panel" aria-label={view === "search" ? "Résultats de recherche" : "Favoris"} aria-live="polite">
          {view === "search" ? <>
          <div className="results-heading">
            <div>
              <p className="eyebrow">CATALOGUE</p>
              <h2>{query.trim().length >= 2 ? "Résultats" : "À vous de choisir"}</h2>
            </div>
            {searchState === "loading" && <span className="loading-label"><i className="spinner" />Recherche…</span>}
            {searchState === "done" && tracks.length > 0 && <span className="result-count">{tracks.length} titres</span>}
          </div>

          {searchState === "idle" && <div className="empty-state"><span className="empty-orbit"><i /><i /><i /></span><strong>Une recherche, et c’est parti.</strong><p>Saisis au moins deux caractères pour trouver des titres.</p></div>}
          {searchState === "error" && <div className="message-state is-error"><strong>La recherche n’a pas abouti.</strong><p>{searchError}</p></div>}
          {searchState === "done" && tracks.length === 0 && <div className="empty-state compact"><strong>Aucun titre trouvé</strong><p>Essaie avec un autre titre ou le nom de l’artiste.</p></div>}

          {tracks.length > 0 && renderTrackRows(tracks, "search")}
          </> : <>
            <div className="results-heading">
              <div>
                <p className="eyebrow">VOTRE BIBLIOTHÈQUE</p>
                <h2>Favoris</h2>
              </div>
              <div className="favorites-heading-actions">
                {favoritesLoading && <span className="loading-label"><i className="spinner" />Chargement…</span>}
                {!favoritesLoading && <button type="button" className="refresh-favorites" onClick={() => void loadFavorites()} disabled={favoritesLoading}>Actualiser</button>}
              </div>
            </div>
            {favoritesError && <div className="message-state is-error" role="alert"><strong>Les favoris n’ont pas pu être chargés.</strong><p>{favoritesError}</p><button type="button" className="retry-favorites" onClick={() => void loadFavorites()} disabled={favoritesLoading}>Réessayer</button></div>}
            {!favoritesError && !favoritesLoading && favorites.length === 0 && <div className="empty-state compact"><strong>Aucun favori pour le moment</strong><p>Ajoute des titres YouTube depuis les résultats de recherche.</p></div>}
            {!favoritesError && favoriteTracks.length > 0 && renderTrackRows(favoriteTracks, "favorites")}
          </>}
          {favoriteActionError && <p className="api-action-error" role="alert">Action sur le favori impossible : {favoriteActionError}</p>}
        </section>
      </main>

      <footer className="player-bar">
        <div className="now-playing">
          {currentTrack?.cover.url ? <img className="player-cover" src={currentTrack.cover.url} alt="" /> : <div className="player-cover placeholder-cover"><span>DF</span></div>}
          <div className="now-copy">
            <strong title={currentTrack?.title}>{currentTrack?.title ?? "Aucun titre sélectionné"}</strong>
            <span title={currentTrack ? artistLine(currentTrack) : undefined}>{currentTrack ? artistLine(currentTrack) : "Choisis un résultat pour commencer"}</span>
          </div>
        </div>
        <div className="player-center">
          <div className="player-controls">
            <button type="button" className="control-button play-toggle" onClick={() => void togglePlayback()} disabled={!currentTrack || playbackState === "resolving"} aria-label={isPlaying ? "Mettre en pause" : "Lire"}>
              {playbackState === "resolving" ? <i className="spinner dark" /> : isPlaying ? "Ⅱ" : "▶"}
            </button>
          </div>
          <div className="timeline">
            <span>{formatTime(displayedPosition)}</span>
            <input
              type="range"
              min="0"
              max={duration || 0}
              step="0.25"
              value={Math.min(displayedPosition, duration || 0)}
              disabled={!canSeek}
              aria-label="Position de lecture"
              onChange={(event) => setSeekDraft(Number(event.target.value))}
              onPointerUp={commitSeek}
              onKeyUp={commitSeek}
            />
            <span>{formatTime(duration)}</span>
          </div>
        </div>
        <div className="player-status">
          <span className={`status-dot ${playbackState}`} />
          <p title={playbackMessage}>{playbackMessage}</p>
          <label className="volume-control" aria-label="Volume">
            <span>Vol.</span>
            <input type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => setVolume(Number(event.target.value))} />
          </label>
        </div>
      </footer>
      <audio ref={audioRef} preload="metadata" crossOrigin="anonymous" />
    </div>
  );
}
