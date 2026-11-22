import { useEffect } from "react";
import { useLocalLibraryStore } from "../store/localLibraryStore";

export function useLocalTracks() {
  const tracks = useLocalLibraryStore((state) => state.tracks);
  const loadState = useLocalLibraryStore((state) => state.loadState);
  const load = useLocalLibraryStore((state) => state.load);

  useEffect(() => {
    if (loadState === "idle") void load();
  }, [loadState, load]);

  // DowFlow downloads are imported by the main process; reload when they land.
  useEffect(() => {
    const bridge = window.linerElectron;
    return bridge?.onLocalTracksChanged?.(() => {
      void load();
    });
  }, [load]);

  // A track downloaded while the window was in the background still has to be
  // there when the user comes back to "On this device".
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void load();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);

  return {
    tracks,
    isLoading: loadState === "idle" || loadState === "loading",
    isAvailable: loadState !== "unavailable",
  };
}
