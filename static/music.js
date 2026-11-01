let page = document.body.dataset.page ?? "home";
const storageKeys = {
  liked: "dowflow-music-liked",
  recent: "dowflow-music-recent-history",
  lastTrack: "dowflow-music-last-track-index",
  activeTheme: "dowflow-music-active-theme",
  playback: "dowflow-music-playback",
  onlineCollapsed: "dowflow-music-online-collapsed",
};

// LOCKING AUDIO OPTIMIZATION FOR MOBILE
const audio = document.getElementById("audio-player");
if (audio) {
  audio.preload = "none"; // Évite de saturer la bande passante mobile
}
const preloadAudio = new Audio();
preloadAudio.preload = "none";

// SYNC LIBRARY LOADING

const playToggle = document.getElementById("play-toggle");
const prevTrackButton = document.getElementById("prev-track");
const nextTrackButton = document.getElementById("next-track");
const likeCurrentButton = document.getElementById("like-current");
const timelineRange = document.getElementById("timeline-range");
const playerStatus = document.getElementById("player-status");
const playerTrack = document.getElementById("player-track");
const playerArtist = document.getElementById("player-artist");
const playerCover = document.getElementById("player-cover");
const currentTimeLabel = document.getElementById("current-time");
const totalTimeLabel = document.getElementById("total-time");
let heroTrackTitle = document.getElementById("hero-track-title");
let heroTrackArtist = document.getElementById("hero-track-artist");
let heroProgress = document.getElementById("hero-progress");
let heroPhoto = document.getElementById("hero-photo");
let heroCover = document.getElementById("hero-cover");
let heroSpotifyCode = document.getElementById("hero-spotify-code");
let heroCodeSeed = "";

const refreshHeroRefs = () => {
  heroTrackTitle = document.getElementById("hero-track-title");
  heroTrackArtist = document.getElementById("hero-track-artist");
  heroProgress = document.getElementById("hero-progress");
  heroPhoto = document.getElementById("hero-photo");
  heroCover = document.getElementById("hero-cover");
  heroSpotifyCode = document.getElementById("hero-spotify-code");
};

// VARIABLES POUR LA LECTURE EN BOUCLE DES FAVORIS
let isLoopingFavorites = false;
let favoriteTracks = [];
let originalPlaylist = [];
let originalIndex = -1;

let tracks = [];
let filteredTracks = [];
let currentIndex = -1;
let isPlaying = false;
let isScrubbing = false;
let pendingSeekTime = null;
let pendingSeekAttempts = 0;
let libraryPage = 1;
let explorePage = 1;
let likedPage = 1;
let requestedAutoplay = false;
const pageSize = 1000; // AUGMENTÉ POUR AFFICHER PLUS DE MUSIQUES
let nextPreloadedFile = "";
let favoritesReady = false;
const viewState = {
  exploreTerm: "",
  libraryTerm: "",
  likedTerm: "",
};

// Fonctions utilitaires
const getLiked = () => {
  try {
    return JSON.parse(localStorage.getItem(storageKeys.liked) ?? "[]");
  } catch {
    return [];
  }
};

const setLiked = (liked) => {
  localStorage.setItem(storageKeys.liked, JSON.stringify(liked));
};

const persistFavorite = async (file, liked) => {
  try {
    const response = await fetch(
      liked ? "/api/music/favorites" : `/api/music/favorites/${encodeURIComponent(file)}`,
      {
        method: liked ? "POST" : "DELETE",
        headers: liked ? { "Content-Type": "application/json" } : undefined,
        body: liked ? JSON.stringify({ filename: file }) : undefined,
      },
    );
    if (!response.ok) {
      throw new Error("Favorite sync failed");
    }
  } catch {
    // localStorage remains the immediate fallback when the server is offline.
  }
};

const syncFavorites = async () => {
  const localFavorites = new Set(getLiked());
  try {
    const response = await fetch("/api/music/favorites");
    const payload = await response.json();
    const serverFavorites = new Set(payload.items || []);
    const merged = [...new Set([...serverFavorites, ...localFavorites])];
    setLiked(merged);
    for (const file of localFavorites) {
      if (!serverFavorites.has(file)) {
        void persistFavorite(file, true);
      }
    }
  } catch {
    // Keep browser favorites available if the database endpoint is unavailable.
  } finally {
    favoritesReady = true;
  }
};

const getStoredTheme = () => sessionStorage.getItem(storageKeys.activeTheme);
const setStoredTheme = (themeId) => sessionStorage.setItem(storageKeys.activeTheme, themeId);
const clearStoredTheme = () => sessionStorage.removeItem(storageKeys.activeTheme);

const getRecentHistory = () => {
  try {
    return JSON.parse(localStorage.getItem(storageKeys.recent) ?? "[]");
  } catch {
    return [];
  }
};

const pushRecentTrack = (file) => {
  const recent = getRecentHistory().filter((item) => item !== file);
  recent.unshift(file);
  localStorage.setItem(storageKeys.recent, JSON.stringify(recent.slice(0, 24)));
};

const toggleLiked = (file) => {
  const preservedScrollY = window.scrollY;
  const liked = new Set(getLiked());
  if (liked.has(file)) {
    liked.delete(file);
  } else {
    liked.add(file);
  }

  setLiked([...liked]);
  if (favoritesReady) {
    void persistFavorite(file, liked.has(file));
  }
  updateFavoriteButton();
  refreshStatCounters();
  rerenderPageBlocks();
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: preservedScrollY, behavior: "auto" });
  });
};

const parseTrackName = (rawName) => {
  const separator = rawName.includes(" - ") ? " - " : null;
  if (!separator) {
    return { artist: "Local artist", title: rawName };
  }

  const [artist, ...rest] = rawName.split(separator);
  return {
    artist: artist.trim() || "Local artist",
    title: rest.join(separator).trim() || rawName,
  };
};

const formatTime = (seconds) => {
  if (!Number.isFinite(seconds)) {
    return "0:00";
  }

  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${secs}`;
};

const normalizeSearch = (value) => {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
};

const toAudioUrl = (track) => {
  if (!track) {
    return "";
  }
  if (track.audio_url) {
    return track.audio_url;
  }
  if (!track.file) {
    return "";
  }
  return `/media/music/${String(track.file)
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")}`;
};

const setAudioSource = (track) => {
  if (!audio || !track) {
    return false;
  }

  const nextSrc = toAudioUrl(track);
  if (audio.dataset.file === track.file && audio.getAttribute("src") === nextSrc) {
    return false;
  }

  audio.src = nextSrc;
  audio.dataset.file = track.file;
  return true;
};

const clearAudioSource = () => {
  if (!audio) {
    return;
  }

  if (!audio.getAttribute("src")) {
    delete audio.dataset.file;
    return;
  }

  audio.removeAttribute("src");
  delete audio.dataset.file;
  audio.load();
};

const getCoverUrl = (track) => {
  if (!track?.cover) {
    return "";
  }
  return track.cover;
};

const mapLibraryItem = (item) => {
  const filename = item.filename || item.file || item.name || "";
  return {
    file: filename,
    name: filename,
    title: item.title || filename,
    artist: item.artist || "Local artist",
    cover: item.cover_url || item.cover || "",
    audio_url: item.audio_url || "",
    size: item.size,
    mtime: item.mtime,
  };
};

const createTrackModel = (track, index) => {
  return {
    ...track,
    index,
    searchText: normalizeSearch(`${track.artist} ${track.title} ${track.name}`),
    titleSearch: normalizeSearch(track.title),
    artistSearch: normalizeSearch(track.artist),
  };
};

const setActiveNav = () => {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === page);
  });
};

const updateFavoriteButton = () => {
  if (!likeCurrentButton) {
    return;
  }

  const currentTrack = tracks[currentIndex];
  const liked = currentTrack ? getLiked().includes(currentTrack.file) : false;
  likeCurrentButton.textContent = liked ? "Remove" : "Favorite";
  likeCurrentButton.classList.toggle("is-liked", liked);
};

const hashSeed = (value) => {
  let hash = 2166136261;
  const text = String(value || "dowflow");
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
};

const renderSpotifyCode = (seed) => {
  if (!heroSpotifyCode) {
    return;
  }
  if (heroCodeSeed === seed && heroSpotifyCode.childElementCount) {
    return;
  }
  heroCodeSeed = seed;
  heroSpotifyCode.innerHTML = "";

  const rng = (() => {
    let state = hashSeed(seed) || 1;
    return () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 4294967296;
    };
  })();

  const heights = [18, 28, 38, 48, 62, 78, 92];
  const pattern = [];
  pattern.push("dot");
  for (let i = 0; i < 23; i += 1) {
    if (rng() < 0.12) {
      pattern.push("dot");
    } else {
      pattern.push(heights[Math.floor(rng() * heights.length)]);
    }
  }
  pattern.push("dot");

  pattern.forEach((item) => {
    const el = document.createElement("span");
    if (item === "dot") {
      el.className = "code-dot";
    } else {
      el.className = "code-bar";
      el.style.setProperty("--h", `${item}%`);
    }
    heroSpotifyCode.appendChild(el);
  });
};

const syncPlayerLabels = () => {
  const currentTrack = tracks[currentIndex];

  if (!currentTrack) {
    playerTrack.textContent = "No track";
    playerArtist.textContent = "Local library";
    if (playerCover) {
      playerCover.style.backgroundImage = "";
    }
    if (heroPhoto) {
      heroPhoto.style.backgroundImage = "";
    }
    if (heroCover) {
      heroCover.style.backgroundImage = "";
    }
    if (heroTrackTitle) {
      heroTrackTitle.textContent = "No track";
      heroTrackArtist.textContent = "Choose a track to begin";
    }
    renderSpotifyCode("empty");
    updateFavoriteButton();
    return;
  }

  playerTrack.textContent = currentTrack.title;
  playerArtist.textContent = currentTrack.artist;
  const coverUrl = getCoverUrl(currentTrack);
  if (playerCover) {
    playerCover.style.backgroundImage = coverUrl ? `url("${coverUrl}")` : "";
  }
  if (heroPhoto) {
    heroPhoto.style.backgroundImage = coverUrl
      ? `linear-gradient(180deg, rgba(5, 12, 8, 0.26), rgba(5, 12, 8, 0.72)), url("${coverUrl}")`
      : "";
  }
  if (heroCover) {
    heroCover.style.backgroundImage = coverUrl ? `url("${coverUrl}")` : "";
  }
  if (heroTrackTitle) {
    heroTrackTitle.textContent = currentTrack.title;
    heroTrackArtist.textContent = currentTrack.artist;
  }
  renderSpotifyCode(currentTrack.file || currentTrack.title || "track");
  updateFavoriteButton();
};

const updatePlaybackUi = () => {
  // Message différent selon le mode
  if (isLoopingFavorites) {
    playToggle.textContent = isPlaying ? "Pause" : "Play";
    playerStatus.textContent = isPlaying ? "Playing favorites on loop" : "Paused (favorites)";
  } else {
    playToggle.textContent = isPlaying ? "Pause" : "Play";
    playerStatus.textContent = isPlaying ? "Playing" : "Paused";
  }
  
  document.body.classList.toggle("is-playing", isPlaying);
  currentTimeLabel.textContent = formatTime(audio.currentTime);
  totalTimeLabel.textContent = formatTime(audio.duration);

  timelineRange.max = Number.isFinite(audio.duration) && audio.duration > 0 ? `${audio.duration}` : "0";
  if (!isScrubbing) {
    timelineRange.value = `${audio.currentTime || 0}`;
  }

  // Mise à jour de la couleur de la barre de progression (style Spotify)
  const progressPercent = audio.duration > 0
    ? (audio.currentTime / audio.duration) * 100
    : 0;
  timelineRange.style.background = `linear-gradient(to right, #1ed760 ${progressPercent}%, rgba(255, 255, 255, 0.15) ${progressPercent}%)`;
  if (heroProgress) {
    heroProgress.style.width = `${progressPercent}%`;
  }
  // Le hero utilise un code style Spotify à la place de la barre de progression.
};

const seekTo = (value) => {
  if (!Number.isFinite(audio.duration) || audio.duration <= 0) {
    return;
  }

  pendingSeekTime = Math.max(0, Math.min(Number(value) || 0, audio.duration));
  pendingSeekAttempts = 0;
  audio.currentTime = pendingSeekTime;
};

const flushPendingSeek = () => {
  if (pendingSeekTime === null || !Number.isFinite(audio.duration) || audio.duration <= 0) {
    return;
  }

  const targetTime = Math.max(0, Math.min(pendingSeekTime, audio.duration));

  if (Math.abs(audio.currentTime - targetTime) <= 1) {
    pendingSeekTime = null;
    pendingSeekAttempts = 0;
    return;
  }

  if (pendingSeekAttempts >= 4) {
    pendingSeekTime = null;
    pendingSeekAttempts = 0;
    return;
  }

  pendingSeekAttempts += 1;
  audio.currentTime = targetTime;
};

const preloadUpcomingTrack = (index) => {
  if (!tracks.length) {
    return;
  }

  const nextIndex = ((index + 1) % tracks.length + tracks.length) % tracks.length;
  const nextTrack = tracks[nextIndex];
  if (!nextTrack || nextTrack.file === nextPreloadedFile) {
    return;
  }

  nextPreloadedFile = nextTrack.file;
  return;
};

const savePlaybackState = () => {
  const track = tracks[currentIndex];
  if (!track?.file) {
    return;
  }

  const payload = {
    file: track.file,
    time: Number(audio?.currentTime) || 0,
    playing: Boolean(isPlaying && audio && !audio.paused),
  };

  try {
    sessionStorage.setItem(storageKeys.playback, JSON.stringify(payload));
  } catch {
    /* ignore quota / private mode */
  }
  localStorage.setItem(storageKeys.lastTrack, String(currentIndex));
};

const readPlaybackState = () => {
  try {
    return JSON.parse(sessionStorage.getItem(storageKeys.playback) ?? "null");
  } catch {
    return null;
  }
};

const restorePlaybackState = async () => {
  if (!tracks.length || !audio) {
    return;
  }

  const state = readPlaybackState();
  let idx = -1;
  if (state?.file) {
    idx = tracks.findIndex((track) => track.file === state.file);
  }
  if (idx < 0) {
    const last = parseInt(localStorage.getItem(storageKeys.lastTrack) ?? "", 10);
    if (!Number.isNaN(last) && last >= 0 && last < tracks.length) {
      idx = last;
    }
  }
  if (idx < 0) {
    idx = 0;
  }

  currentIndex = idx;
  localStorage.setItem(storageKeys.lastTrack, String(currentIndex));
  const track = tracks[currentIndex];
  const resumeTime = Math.max(0, Number(state?.time) || 0);
  const shouldPlay = Boolean(state?.playing);

  requestedAutoplay = shouldPlay;
  pendingSeekTime = resumeTime > 0 ? resumeTime : null;
  pendingSeekAttempts = 0;
  setAudioSource(track);
  syncPlayerLabels();
  updatePlaybackUi();

  let restored = false;
  const applyResume = () => {
    if (restored) {
      return;
    }
    restored = true;
    if (pendingSeekTime !== null && Number.isFinite(audio.duration) && audio.duration > 0) {
      audio.currentTime = Math.min(pendingSeekTime, Math.max(0, audio.duration - 0.25));
      pendingSeekTime = null;
    }
    updatePlaybackUi();
    if (shouldPlay) {
      void playCurrent();
    } else if (playerStatus) {
      playerStatus.textContent = "Ready to play";
    }
    savePlaybackState();
  };

  audio.addEventListener("loadedmetadata", applyResume, { once: true });
  audio.load();
  if (audio.readyState >= 1) {
    applyResume();
  }
};

const loadTrack = (index, shouldPlay = false) => {
  if (!tracks.length) {
    return;
  }

  currentIndex = ((index % tracks.length) + tracks.length) % tracks.length;
  localStorage.setItem(storageKeys.lastTrack, currentIndex);
  const track = tracks[currentIndex];

  audio.pause();
  requestedAutoplay = shouldPlay;
  pendingSeekTime = null;
  pendingSeekAttempts = 0;
  nextPreloadedFile = "";
  if (shouldPlay) {
    setAudioSource(track);
    audio.currentTime = 0;
  } else {
    clearAudioSource();
  }

  if (isLoopingFavorites) {
    playerStatus.textContent = "Playing favorites on loop...";
  } else {
    playerStatus.textContent = "Loading...";
  }

  syncPlayerLabels();
  updatePlaybackUi();
  savePlaybackState();

  if (shouldPlay) {
    audio.load();
  } else if (playerStatus) {
    playerStatus.textContent = "Ready to play";
  }

  if (shouldPlay) {
    void playCurrent();
  }
};

const playCurrent = async () => {
  if (!tracks.length) {
    return;
  }

  if (currentIndex === -1) {
    loadTrack(0, false);
  }

  const currentTrack = tracks[currentIndex];
  if (!currentTrack) {
    return;
  }

  const sourceChanged = setAudioSource(currentTrack);
  if (sourceChanged) {
    requestedAutoplay = true;
    audio.load();
  }

  try {
    flushPendingSeek();
    await audio.play();
    isPlaying = true;
    requestedAutoplay = false;
    updatePlaybackUi();
    savePlaybackState();
  } catch {
    isPlaying = false;
    requestedAutoplay = false;
    playerStatus.textContent = "Playback blocked - press Play";
    updatePlaybackUi();
    savePlaybackState();
  }
};

const pauseCurrent = () => {
  audio.pause();
  isPlaying = false;
  updatePlaybackUi();
  savePlaybackState();
};

const playTrackByFile = (file, autoplay = true) => {
  const index = tracks.findIndex((track) => track.file === file);
  if (index !== -1) {
    loadTrack(index, autoplay);
  } else {
    // Si pas trouvé dans tracks, peut-être dans filtered?
    const fIndex = filteredTracks.findIndex((t) => t.file === file);
    if (fIndex !== -1) {
      loadTrack(tracks.indexOf(filteredTracks[fIndex]), autoplay);
    }
  }
};

const createCoverClass = (index) => {
  const variants = ["", "alt-1", "alt-2", "alt-3"];
  return variants[index % variants.length];
};

const createLikeButton = (track) => {
  const button = document.createElement("button");
  button.className = "ghost-button compact like-button";
  const liked = getLiked().includes(track.file);
  button.textContent = liked ? "Remove" : "Add";
  button.classList.toggle("is-liked", liked);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleLiked(track.file);
  });
  return button;
};

// RERENDER PAGE BLOCKS
const renderEmpty = (container, message) => {
  container.innerHTML = `<div class="empty-state"><p>${message}</p></div>`;
};

const renderPagination = (container, currentPage, totalPages, onSelect) => {
  if (!container) {
    return;
  }

  container.innerHTML = "";

  if (totalPages <= 1) {
    container.style.display = "none";
    return;
  }

  container.style.display = "flex";

  const addButton = (label, page, options = {}) => {
    const button = document.createElement("button");
    button.className = `page-button${options.active ? " active" : ""}`;
    button.textContent = label;
    button.disabled = Boolean(options.disabled);
    button.addEventListener("click", () => onSelect(page));
    container.append(button);
  };

  const addDots = () => {
    const dots = document.createElement("span");
    dots.className = "page-dots";
    dots.textContent = "...";
    container.append(dots);
  };

  addButton("<", Math.max(1, currentPage - 1), { disabled: currentPage === 1 });

  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, currentPage + 2);

  if (start > 1) {
    addButton("1", 1);
    if (start > 2) {
      addDots();
    }
  }

  for (let page = start; page <= end; page += 1) {
    addButton(`${page}`, page, { active: page === currentPage });
  }

  if (end < totalPages) {
    if (end < totalPages - 1) {
      addDots();
    }
    addButton(`${totalPages}`, totalPages);
  }

  addButton(">", Math.min(totalPages, currentPage + 1), {
    disabled: currentPage === totalPages,
  });
};

const renderTrackRows = (container, items, mode = "list") => {
  if (!container) {
    return;
  }

  if (!items.length) {
    renderEmpty(container, "No tracks to show here.");
    return;
  }

  container.innerHTML = "";
  const fragment = document.createDocumentFragment();

  items.forEach((track, index) => {
    const row = document.createElement("article");
    row.className = mode === "table" ? "table-row" : "list-row";
    row.addEventListener("click", () => playTrackByFile(track.file, true));

    const count = document.createElement("span");
    count.className = "track-index";
    count.textContent = `${index + 1}`;

    const meta = document.createElement("div");
    meta.className = "track-meta";
    meta.innerHTML = `<strong class="track-title">${track.title}</strong><p>${track.artist}</p>`;

    const thumb = document.createElement("div");
    thumb.className = "track-thumb";
    const thumbCover = getCoverUrl(track);
    if (thumbCover) {
      thumb.style.backgroundImage = `url("${thumbCover}")`;
    }

    const main = document.createElement("div");
    main.className = "track-main";
    main.append(thumb, meta);

    const playButton = document.createElement("button");
    playButton.className = "ghost-button compact";
    playButton.textContent = "▶";
    playButton.addEventListener("click", (event) => {
      event.stopPropagation();
      playTrackByFile(track.file, true);
    });

    row.append(count, main);
    row.append(createLikeButton(track), playButton);
    fragment.append(row);
  });
  
  container.append(fragment);
};

const themes = [
  { id: "classique", name: "Classique", color: "#f39c12", icon: "🎻", keywords: ["mozart", "beethoven", "bach", "chopin", "classic", "piano", "orchestra", "vienna", "symphony", "concerto", "sonata"] },
  { id: "rap", name: "Rap", color: "#e74c3c", icon: "🎤", keywords: ["rap", "trap", "flow", "beat", "street", "booba", "iam", "ntm", "eminem", "dr dre", "snoop", "tupac", "biggie", "jay-z", "kendrick", "drake", "113", "magic system", "rohff", "kery james", "jul", "ninho", "damso", "nekfeu"] },
  { id: "hiphop", name: "Hip-Hop", color: "#c0392b", icon: "🎧", keywords: ["hiphop", "r&b", "soul", "groove", "urban", "funk", "motown", "usher", "beyonce", "rihanna", "chris brown", "ne-yo"] },
  { id: "jazz", name: "Jazz", color: "#8e44ad", icon: "🎷", keywords: ["jazz", "blues", "swing", "miles", "davis", "coltrane", "armstrong", "fitzgerald", "holiday", "sinatra"] },
  { id: "electro", name: "Électronique", color: "#3498db", icon: "🎹", keywords: ["electro", "techno", "house", "dj", "remix", "mix", "dance", "synth", "daft", "guetta", "tiesto", "avicii", "eddm", "dubstep", "martin garrix"] },
  { id: "pop", name: "Pop", color: "#e84393", icon: "🌟", keywords: ["pop", "hits", "radio", "star", "singer", "love", "jackson", "madonna", "taylor", "bieber", "perry", "gaga", "adele", "ed sheeran", "dua lipa"] },
];

const renderHome = () => {
  const recentList = document.getElementById("recent-list");
  const likedPreview = document.getElementById("liked-preview");
  const dailyPlaylistTitle = document.getElementById("daily-playlist-title");
  const dailyPlaylistText = document.getElementById("daily-playlist-text");
  const playDailyMix = document.getElementById("play-daily-mix");
  const launchSession = document.getElementById("launch-session");
  const clearHistory = document.getElementById("clear-history");
  const heroStatTrackCount = document.getElementById("hero-stat-track-count");
  const heroStatFavoriteCount = document.getElementById("hero-stat-favorite-count");
  const heroStatThemeFocus = document.getElementById("hero-stat-theme-focus");

  // Historique de lecture
  const recentHistory = getRecentHistory();
  const recentHistoryTracks = recentHistory
    .map((file) => tracks.find((track) => track.file === file))
    .filter(Boolean);

  if (recentList) {
    if (recentHistoryTracks.length > 0) {
      renderTrackRows(recentList, recentHistoryTracks.slice(0, 8), "list");
    } else {
      renderEmpty(recentList, "No recent plays yet.");
    }
  }

  // Favoris rapides
  const likedItems = tracks.filter((track) => getLiked().includes(track.file)).slice(0, 8);
  if (likedPreview) {
    renderTrackRows(likedPreview, likedItems, "list");
  }

  const focusTrack = tracks[currentIndex] ?? recentHistoryTracks[0] ?? likedItems[0] ?? tracks[0];
  const focusTheme =
    themes.find((theme) => focusTrack && theme.keywords.some((keyword) => focusTrack.searchText.includes(keyword))) ??
    themes[(likedItems.length + recentHistoryTracks.length + Math.max(tracks.length, 1)) % themes.length];

  if (heroStatTrackCount) {
    heroStatTrackCount.textContent = `${tracks.length}`;
  }
  if (heroStatFavoriteCount) {
    heroStatFavoriteCount.textContent = `${getLiked().length}`;
  }
  if (heroStatThemeFocus) {
    heroStatThemeFocus.textContent = focusTheme?.name ?? "Local";
  }

  if (dailyPlaylistTitle) {
    dailyPlaylistTitle.textContent = recentHistoryTracks[0]?.title ?? tracks[0]?.title ?? "No track";
    dailyPlaylistText.textContent = recentHistoryTracks.length
      ? `${recentHistoryTracks.length} recent plays available.`
      : `${Math.min(20, tracks.length)} tracks ready to play.`;
  }

  if (playDailyMix) {
    playDailyMix.onclick = () => {
      if (tracks.length) {
        loadTrack(0, true);
      }
    };
  }

  if (launchSession) {
    launchSession.onclick = () => {
      if (tracks.length) {
        loadTrack(Math.floor(Math.random() * Math.min(tracks.length, 40)), true);
      }
    };
  }

  if (clearHistory) {
    clearHistory.onclick = () => {
      localStorage.removeItem(storageKeys.recent);
      renderHome();
    };
  }
};

const renderExplore = () => {
  const exploreResults = document.getElementById("explore-results");
  const search = document.getElementById("explore-search");
  const helper = document.getElementById("explore-helper");
  const title = document.getElementById("explore-results-title");
  const pagination = document.getElementById("explore-pagination");
  const pageEyebrow = document.getElementById("explore-page-eyebrow");
  const pageTitle = document.querySelector(".page-header h2");
  const sidebarEyebrow = document.getElementById("explore-sidebar-eyebrow");
  const sidebarTitle = document.getElementById("explore-sidebar-title");
  const sidebarText = document.getElementById("explore-sidebar-text");
  const exploreMenuItem = document.querySelector('[data-nav="explore"]');

  // Récupérer le thème depuis l'URL
  const urlParams = new URLSearchParams(window.location.search);
  const themeFromUrl = urlParams.get("theme");
  const themeId = themeFromUrl ?? getStoredTheme();
  const activeTheme = themes.find(t => t.id === themeId);

  if (themeFromUrl) {
    setStoredTheme(themeFromUrl);
  }

  if (activeTheme) {
    document.body.classList.add("theme-active");
    document.body.style.setProperty("--theme-color", activeTheme.color);
    if (pageEyebrow) pageEyebrow.textContent = activeTheme.name;
    if (pageTitle) pageTitle.textContent = `${activeTheme.name}: explore tracks from this theme`;
    if (sidebarEyebrow) sidebarEyebrow.textContent = activeTheme.name;
    if (sidebarTitle) sidebarTitle.textContent = `Explore ${activeTheme.name}`;
    if (sidebarText) sidebarText.textContent = `Showing tracks for the ${activeTheme.name} theme.`;
    if (exploreMenuItem) exploreMenuItem.textContent = activeTheme.name;
    document.title = `Spoty Wave - ${activeTheme.name}`;
    if (title) title.textContent = `Theme: ${activeTheme.name}`;
    if (helper) helper.textContent = `Here is a selection of tracks for the ${activeTheme.name} theme.`;
  }

  const alphabeticalTracks = [...tracks].sort((a, b) => a.title.localeCompare(b.title, "fr", { sensitivity: "base" }));
  const explorePageSize = 50; // Plus petit pour fluidité

  const updateExploreResults = (term = viewState.exploreTerm, options = {}) => {
    const normalized = normalizeSearch(term);
    let results = [];
    viewState.exploreTerm = term;

    if (activeTheme && !normalized) {
      // Filtrage par thème si pas de recherche
      // On cherche les mots-clés dans le nom du fichier, le titre et l'artiste
      results = alphabeticalTracks.filter(track => {
        const matchesTheme = activeTheme.keywords.some(kw => track.searchText.includes(kw));
        
        // Si c'est le thème "Pop", on y met aussi tout ce qui n'a pas été catégorisé
        if (activeTheme.id === "pop" && !matchesTheme) {
          const isCategorized = themes.some(t => t.id !== "pop" && t.keywords.some(kw => track.searchText.includes(kw)));
          return !isCategorized;
        }
        
        return matchesTheme;
      });
    } else if (!normalized) {
      if (title) title.textContent = "Suggestions";
      if (helper) {
        helper.textContent = "Type a title or artist from your local library.";
      }
      results = alphabeticalTracks;
    } else {
      // Recherche locale uniquement (biblio DowFlow déjà chargée)
      results = alphabeticalTracks.filter((track) =>
        track.titleSearch.includes(normalized) ||
        track.artistSearch.includes(normalized) ||
        track.searchText.includes(normalized)
      );
      if (title) title.textContent = `Suggestions for "${term}"`;
      if (helper) {
        helper.textContent = `${results.length} local track(s) for "${term}".`;
      }
    }

    // Mise à jour de filteredTracks pour que playTrackByFile fonctionne
    filteredTracks = results;

    const totalPages = Math.max(1, Math.ceil(results.length / explorePageSize));
    explorePage = Math.min(Math.max(explorePage, 1), totalPages);
    const startIndex = (explorePage - 1) * explorePageSize;
    const paginatedResults = results.slice(startIndex, startIndex + explorePageSize);

    renderTrackRows(exploreResults, paginatedResults, "table");

    if (!options.keepInputValue && search && search.value !== term) {
      search.value = term;
    }
    
    if (pagination) {
      renderPagination(pagination, explorePage, totalPages, (newPage) => {
        explorePage = newPage;
        updateExploreResults(term);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }
  };

  if (search) {
    search.autocomplete = "off";
    search.spellcheck = false;
    search.autocapitalize = "off";
    search.oninput = (event) => {
      explorePage = 1;
      updateExploreResults(event.target.value, { keepInputValue: true });
      const localBlock = document.getElementById("explore-results");
      if (localBlock && event.target.value.trim()) {
        localBlock.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    };
  }

  updateExploreResults();
};

const renderLibrary = () => {
  const list = document.getElementById("library-list");
  const search = document.getElementById("library-search");
  const summary = document.getElementById("library-summary");
  const pagination = document.getElementById("library-pagination");

  const libraryPageSize = 50;

  const updateLibraryView = () => {
    const rawTerm = search?.value ?? viewState.libraryTerm;
    const term = normalizeSearch(rawTerm);
    viewState.libraryTerm = rawTerm;
    let results;
    
    if (!term) {
      results = [...tracks].sort((a, b) =>
        a.title.localeCompare(b.title, "fr", { sensitivity: "base" })
      );
    } else {
      results = tracks
        .filter((track) => track.titleSearch.startsWith(term))
        .sort((a, b) => a.title.localeCompare(b.title, "fr", { sensitivity: "base" }));
    }

    const totalPages = Math.max(1, Math.ceil(results.length / libraryPageSize));
    libraryPage = Math.min(Math.max(libraryPage, 1), totalPages);
    const startIndex = (libraryPage - 1) * libraryPageSize;
    const paginatedResults = results.slice(startIndex, startIndex + libraryPageSize);

    renderTrackRows(list, paginatedResults, "table");

    if (search && search.value !== rawTerm) {
      search.value = rawTerm;
    }

    if (pagination) {
      renderPagination(pagination, libraryPage, totalPages, (newPage) => {
        libraryPage = newPage;
        updateLibraryView();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    if (summary) {
      summary.textContent = `${tracks.length} track${tracks.length > 1 ? "s" : ""} in the library`;
    }
  };

  if (search) {
    search.oninput = () => {
      libraryPage = 1;
      viewState.libraryTerm = search.value;
      updateLibraryView();
    };
  }

  updateLibraryView();
};

const renderLiked = () => {
  const list = document.getElementById("liked-list");
  const search = document.getElementById("liked-search");
  const playLikedLoop = document.getElementById("play-liked-loop");
  const pagination = document.getElementById("liked-pagination");

  const likedPageSize = 50;

  const updateLikedView = () => {
    const likedFiles = new Set(getLiked());
    const likedTracks = tracks.filter((track) => likedFiles.has(track.file));
    const rawTerm = search?.value ?? viewState.likedTerm;
    const term = normalizeSearch(rawTerm);
    viewState.likedTerm = rawTerm;
    const visible = term
      ? likedTracks.filter((track) => track.titleSearch.startsWith(term))
      : likedTracks.sort((a, b) => a.title.localeCompare(b.title, "fr", { sensitivity: "base" }));
    
    const totalPages = Math.max(1, Math.ceil(visible.length / likedPageSize));
    likedPage = Math.min(Math.max(likedPage, 1), totalPages);
    const startIndex = (likedPage - 1) * likedPageSize;
    const paginatedResults = visible.slice(startIndex, startIndex + likedPageSize);

    renderTrackRows(list, paginatedResults, "table");

    if (search && search.value !== rawTerm) {
      search.value = rawTerm;
    }

    if (pagination) {
      renderPagination(pagination, likedPage, totalPages, (newPage) => {
        likedPage = newPage;
        updateLikedView();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }
    
    // Stocker les favoris pour la lecture en boucle
    favoriteTracks = visible;
  };

  if (search) {
    search.oninput = () => {
      likedPage = 1;
      viewState.likedTerm = search.value;
      updateLikedView();
    };
  }

  playLikedLoop?.addEventListener("click", () => {
    const likedFiles = new Set(getLiked());
    const likedTracks = tracks.filter((track) => likedFiles.has(track.file));
    
    if (likedTracks.length > 0) {
      originalPlaylist = [...tracks];
      originalIndex = currentIndex;
      favoriteTracks = likedTracks;
      isLoopingFavorites = true;
      
      tracks = favoriteTracks;
      currentIndex = -1;
      
      playTrackByFile(likedTracks[0].file, true);
    } else {
      playerStatus.textContent = "No favorites found";
    }
  });

  updateLikedView();
};

const rerenderPageBlocks = () => {
  if (page === "home") {
    renderHome();
  }
  if (page === "explore") {
    renderExplore();
  }
  if (page === "library") {
    renderLibrary();
  }
  if (page === "liked") {
    renderLiked();
  }
};

const refreshStatCounters = () => {
  const trackCount = document.getElementById("stat-track-count");
  const favoriteCount = document.getElementById("stat-favorite-count");

  if (trackCount) {
    trackCount.textContent = `${tracks.length}`;
  }
  if (favoriteCount) {
    favoriteCount.textContent = `${getLiked().length}`;
  }
};

const attachMenuNavigation = () => {
  document.querySelectorAll("a[href]").forEach((link) => {
    const href = link.getAttribute("href") || "";
    if (!href.startsWith("/music") || href.includes("#")) {
      return;
    }
    link.addEventListener("click", (event) => {
      event.preventDefault();
      if (link.dataset.nav === "explore") {
        clearStoredTheme();
      }
      savePlaybackState();
      void navigateMusicPage(href, true).catch(() => window.location.assign(href));
    });
  });
};

const navigateMusicPage = async (href, pushHistory = false) => {
  const response = await fetch(href, { headers: { "X-DowFlow-Navigation": "1" } });
  if (!response.ok) {
    window.location.assign(href);
    return;
  }
  const html = await response.text();
  const nextDocument = new DOMParser().parseFromString(html, "text/html");
  const nextShell = nextDocument.querySelector(".app-shell");
  const currentShell = document.querySelector(".app-shell");
  if (!nextShell || !currentShell) {
    window.location.assign(href);
    return;
  }

  const previousMain = currentShell.querySelector(".main-content");
  const nextMain = nextShell.querySelector(".main-content");
  const previousSidebar = currentShell.querySelector(".sidebar");
  const nextSidebar = nextShell.querySelector(".sidebar");
  if (previousMain && nextMain) previousMain.replaceWith(nextMain);
  if (previousSidebar && nextSidebar) previousSidebar.replaceWith(nextSidebar);

  const nextPage = nextDocument.body.dataset.page || "home";
  document.body.classList.add("is-page-transitioning");
  page = nextPage;
  document.body.dataset.page = nextPage;
  document.title = nextDocument.title;
  if (pushHistory) history.pushState({ musicPage: nextPage }, "", href);
  window.scrollTo({ top: 0, behavior: "smooth" });

  refreshHeroRefs();
  setActiveNav();
  attachMenuNavigation();
  rerenderPageBlocks();
  initOnlineDownload();
  initOnlineCollapse();
  refreshStatCounters();
  requestAnimationFrame(() => document.body.classList.remove("is-page-transitioning"));
};

const attachGlobalEvents = () => {
  if (!document.body.dataset.contextMenuBlocked) {
    document.addEventListener("contextmenu", (event) => {
      event.preventDefault();
    });
    document.body.dataset.contextMenuBlocked = "true";
  }

  attachMenuNavigation();

  playToggle?.addEventListener("click", () => {
    if (isPlaying) {
      pauseCurrent();
    } else {
      playCurrent();
    }
  });

  prevTrackButton?.addEventListener("click", () => {
    if (tracks.length) {
      if (isLoopingFavorites && favoriteTracks.length > 0) {
        const currentFavoriteIndex = favoriteTracks.findIndex(track => track.file === tracks[currentIndex].file);
        const newIndex = currentFavoriteIndex <= 0 ? favoriteTracks.length - 1 : currentFavoriteIndex - 1;
        playTrackByFile(favoriteTracks[newIndex].file, true);
      } else {
        loadTrack(currentIndex <= 0 ? tracks.length - 1 : currentIndex - 1, true);
      }
    }
  });

  nextTrackButton?.addEventListener("click", () => {
    if (tracks.length) {
      if (isLoopingFavorites && favoriteTracks.length > 0) {
        const currentFavoriteIndex = favoriteTracks.findIndex(track => track.file === tracks[currentIndex].file);
        const newIndex = (currentFavoriteIndex + 1) % favoriteTracks.length;
        playTrackByFile(favoriteTracks[newIndex].file, true);
      } else {
        loadTrack(currentIndex >= tracks.length - 1 ? 0 : currentIndex + 1, true);
      }
    }
  });

  likeCurrentButton?.addEventListener("click", () => {
    const currentTrack = tracks[currentIndex];
    if (currentTrack) {
      toggleLiked(currentTrack.file);
    }
  });

  timelineRange?.addEventListener("input", (event) => {
    isScrubbing = true;
    seekTo(event.target.value);
    updatePlaybackUi();
  });
  timelineRange?.addEventListener("change", (event) => {
    seekTo(event.target.value);
    isScrubbing = false;
    updatePlaybackUi();
  });
  timelineRange?.addEventListener("pointerdown", () => {
    isScrubbing = true;
  });
  timelineRange?.addEventListener("pointerup", () => {
    isScrubbing = false;
    updatePlaybackUi();
  });
  timelineRange?.addEventListener("pointercancel", () => {
    isScrubbing = false;
    updatePlaybackUi();
  });

  let lastPlaybackSaveAt = 0;
  audio?.addEventListener("timeupdate", () => {
    flushPendingSeek();
    updatePlaybackUi();
    const now = Date.now();
    if (now - lastPlaybackSaveAt > 1200) {
      lastPlaybackSaveAt = now;
      savePlaybackState();
    }
  });
  audio?.addEventListener("loadedmetadata", () => {
    flushPendingSeek();
    updatePlaybackUi();
  });
  audio?.addEventListener("loadeddata", flushPendingSeek);
  audio?.addEventListener("durationchange", flushPendingSeek);
  audio?.addEventListener("progress", flushPendingSeek);
  audio?.addEventListener("canplay", () => {
    flushPendingSeek();
    if (requestedAutoplay && !isPlaying) {
      playCurrent();
      return;
    }

    if (currentIndex !== -1 && !isPlaying) {
      playerStatus.textContent = "Ready to play";
    }
  });
  audio?.addEventListener("play", () => {
    isPlaying = true;
    const currentTrack = tracks[currentIndex];
    if (currentTrack) {
      pushRecentTrack(currentTrack.file);
      if (page === "home") {
        renderHome();
      }
    }
    updatePlaybackUi();
    savePlaybackState();
  });
  audio?.addEventListener("pause", () => {
    isPlaying = false;
    updatePlaybackUi();
    savePlaybackState();
  });
  audio?.addEventListener("seeked", () => {
    flushPendingSeek();
    updatePlaybackUi();
    savePlaybackState();
  });
  audio?.addEventListener("stalled", () => {
    playerStatus.textContent = "Loading...";
  });
  audio?.addEventListener("waiting", () => {
    playerStatus.textContent = "Buffering...";
  });
  audio?.addEventListener("error", () => {
    const mediaError = audio.error;
    if (!mediaError) {
      playerStatus.textContent = "Audio error";
      return;
    }

    const messages = {
      1: "Playback interrupted",
      2: "Network error",
      3: "Corrupted audio file",
      4: "Unsupported audio format",
    };

    playerStatus.textContent = messages[mediaError.code] ?? "Audio error";
    isPlaying = false;
    requestedAutoplay = false;
    updatePlaybackUi();
  });
  audio?.addEventListener("ended", () => {
    if (tracks.length) {
      if (isLoopingFavorites && favoriteTracks.length > 0) {
        const currentFavoriteIndex = favoriteTracks.findIndex(track => track.file === tracks[currentIndex].file);
        const nextIndex = (currentFavoriteIndex + 1) % favoriteTracks.length;
        playTrackByFile(favoriteTracks[nextIndex].file, true);
      } else {
        loadTrack(currentIndex + 1, true);
      }
    }
  });

};

const escapeHtml = (value) =>
  String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const formatDuration = (seconds) => {
  if (!seconds && seconds !== 0) return "";
  const total = Math.max(0, Math.round(Number(seconds)));
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const setOnlineStatus = (message, state) => {
  const wrap = document.getElementById("onlineProgressWrap");
  const status = document.getElementById("onlineStatusMessage");
  if (!wrap || !status) return;
  wrap.classList.add("visible");
  status.textContent = message;
  status.className = "online-status" + (state ? ` ${state}` : "");
};

const setOnlineProgress = (pct) => {
  const fill = document.getElementById("onlineProgressFill");
  if (!fill) return;
  fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
};

const pollJob = async (jobId) => {
  const started = Date.now();
  while (Date.now() - started < 60 * 60 * 1000) {
    const res = await fetch(`/jobs/${jobId}`);
    const payload = await res.json();
    if (!res.ok || !payload.success || !payload.job) {
      throw new Error((payload && payload.error) || "Unable to track the download");
    }
    const job = payload.job;
    const pct = Math.max(0, Math.min(99, Number(job.progress) || 0));
    setOnlineProgress(pct);
    setOnlineStatus(`Downloading ${pct.toFixed(0)}%`, "");
    if (["success", "failed", "skipped"].includes(job.status)) return job;
    await sleep(2000);
  }
  throw new Error("Download timed out");
};

const renderOnlineTracks = (container, trackList, emptyText) => {
  if (!container) return;
  container.innerHTML = "";
  if (!trackList || !trackList.length) {
    container.innerHTML = `<div class="search-helper">${escapeHtml(emptyText)}</div>`;
    return;
  }

  trackList.forEach((track) => {
    const row = document.createElement("div");
    row.className = "online-track";
    const thumb = track.thumbnail
      ? `<img class="cover" src="${escapeHtml(track.thumbnail)}" alt="" loading="lazy">`
      : `<div class="cover-placeholder" aria-hidden="true"></div>`;
    const duration = formatDuration(track.duration);
    const sub = [track.artist, duration].filter(Boolean).map(escapeHtml).join(" · ");
    row.innerHTML = `
      ${thumb}
      <div class="meta">
        <div class="name">${escapeHtml(track.title || "Untitled")}</div>
        <div class="sub">${sub || "—"}</div>
      </div>
      <button class="dl" type="button">↓ Download</button>
    `;
    const btn = row.querySelector(".dl");
    btn.addEventListener("click", () => downloadOnlineTrack(track, btn));
    container.appendChild(row);
  });
};

const downloadOnlineTrack = async (track, button) => {
  const formatSelect = document.getElementById("audioFormatSelect");
  const coverToggle = document.getElementById("coverToggle");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Downloading...";
  setOnlineProgress(0);
  setOnlineStatus(`Preparing "${track.title}"...`, "");
  try {
    const res = await fetch("/api/music/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: track.url,
        title: track.title,
        artist: track.artist,
        audio_format: formatSelect ? formatSelect.value : "mp3",
        with_cover: coverToggle ? coverToggle.checked : true,
      }),
    });
    const start = await res.json();
    if (!res.ok || !start.success) throw new Error(start.error || "Download failed");
    const job = await pollJob(start.job_id);
    if (job.status === "success") {
      setOnlineProgress(100);
      const name = (job.result && job.result.filename) || track.title;
      setOnlineStatus(`Complete: ${name}`, "success");
      await reloadLibrary({ keepCurrent: true });
    } else {
      throw new Error(job.error || job.message || "Download failed");
    }
  } catch (err) {
    setOnlineStatus(err.message || "Erreur", "error");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
};

const loadOnlinePopular = async () => {
  const list = document.getElementById("onlinePopularList");
  const count = document.getElementById("onlinePopularCount");
  if (!list) return;
  try {
    const res = await fetch("/api/music/popular?limit=24");
    const data = await res.json();
    const popularTracks = (data && data.tracks) || [];
    if (count) count.textContent = popularTracks.length ? `${popularTracks.length} tracks` : "";
    renderOnlineTracks(list, popularTracks, "No popular tracks available.");
  } catch {
    renderOnlineTracks(list, [], "Unable to load popular tracks.");
  }
};

const initOnlineDownload = () => {
  const form = document.getElementById("onlineSearchForm");
  const input = document.getElementById("onlineSearchInput");
  const btn = document.getElementById("onlineSearchBtn");
  const results = document.getElementById("onlineResultsList");
  const resultsCount = document.getElementById("onlineResultsCount");
  if (!form || !input || !results) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    if (btn) btn.disabled = true;
    results.innerHTML = `<div class="search-helper">Searching...</div>`;
    if (resultsCount) resultsCount.textContent = "";
    try {
      const res = await fetch("/api/music/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, limit: 24 }),
      });
      const data = await res.json();
      const found = (data && data.tracks) || [];
      if (resultsCount) resultsCount.textContent = found.length ? `${found.length} results` : "";
      renderOnlineTracks(results, found, "No results for this search.");
    } catch {
      renderOnlineTracks(results, [], "Search failed.");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  loadOnlinePopular();
};

const initOnlineCollapse = () => {
  const section = document.getElementById("online-download");
  const btn = document.getElementById("onlineCollapseBtn");
  if (!section || !btn) {
    return;
  }

  const applyCollapsed = (collapsed) => {
    section.classList.toggle("is-collapsed", collapsed);
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.title = collapsed ? "Expand" : "Collapse";
    btn.textContent = "×";
    localStorage.setItem(storageKeys.onlineCollapsed, collapsed ? "1" : "0");
  };

  applyCollapsed(localStorage.getItem(storageKeys.onlineCollapsed) === "1");
  btn.addEventListener("click", () => {
    applyCollapsed(!section.classList.contains("is-collapsed"));
  });
};

const reloadLibrary = async ({ keepCurrent = false } = {}) => {
  const previousFile = keepCurrent && currentIndex >= 0 ? tracks[currentIndex]?.file : null;
  const previousTime = keepCurrent ? Number(audio?.currentTime) || 0 : 0;
  const wasPlaying = keepCurrent && isPlaying && audio && !audio.paused;

  try {
    const response = await fetch("/api/music/library?limit=500");
    const payload = await response.json();
    const items = (payload && payload.items) || [];
    tracks = items.map(mapLibraryItem).map(createTrackModel);
  } catch {
    tracks = [];
  }

  refreshStatCounters();
  rerenderPageBlocks();

  if (!tracks.length) {
    if (playerStatus) playerStatus.textContent = "Library is empty";
    return;
  }

  if (keepCurrent && previousFile) {
    const idx = tracks.findIndex((track) => track.file === previousFile);
    if (idx >= 0) {
      currentIndex = idx;
      syncPlayerLabels();
      updatePlaybackUi();
      savePlaybackState();
      return;
    }
  }

  if (keepCurrent && wasPlaying) {
    try {
      sessionStorage.setItem(
        storageKeys.playback,
        JSON.stringify({ file: previousFile, time: previousTime, playing: true })
      );
    } catch {
      /* ignore */
    }
  }

  await restorePlaybackState();
};

const init = async () => {
  setActiveNav();
  attachGlobalEvents();
  window.addEventListener("pagehide", savePlaybackState);
  window.addEventListener("beforeunload", savePlaybackState);
  window.addEventListener("popstate", () => {
    void navigateMusicPage(window.location.pathname + window.location.search);
  });
  await syncFavorites();
  await reloadLibrary();
  initOnlineDownload();
  initOnlineCollapse();
};

init();
