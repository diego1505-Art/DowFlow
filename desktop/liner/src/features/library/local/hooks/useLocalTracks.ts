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

  return {
    tracks,
    isLoading: loadState === "idle" || loadState === "loading",
    isAvailable: loadState !== "unavailable",
  };
}
