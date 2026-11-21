import { useCallback, useState } from "react";
import { api, getAuthSession, toClientTrack } from "@/shared/api";
import { clientCatalog } from "@/shared/api/clientCatalog";
import type { Track } from "@/shared/types";
import {
  addLocalPlaylistTrack,
  createLocalPlaylist,
  deleteLocalPlaylist,
  isLocalPlaylistId,
  moveLocalPlaylistTrack,
  removeLocalPlaylistTrack,
} from "../local/playlists";
import { notifyLibraryChanged, evictPlaylistFromCache } from "./usePlaylists";
import { setTrackLiked, toggleTrackLike } from "./useLikedTracks";

type Options = {
  onSuccess?: (...args: any[]) => void;
  onError?: (error: unknown) => void;
  onSettled?: () => void;
};

function useMutation<T, R = unknown>(action: (input: T) => Promise<R>) {
  const [isPending, setIsPending] = useState(false);
  const mutateAsync = useCallback(
    async (input: T): Promise<R> => {
      setIsPending(true);
      try {
        const result = await action(input);
        notifyLibraryChanged();
        return result;
      } finally {
        setIsPending(false);
      }
    },
    [action],
  );
  const mutate = useCallback(
    (input: T, options?: Options) => {
      void mutateAsync(input)
        .then((value) => options?.onSuccess?.(value))
        .catch((error) => options?.onError?.(error))
        .finally(() => options?.onSettled?.());
    },
    [mutateAsync],
  );
  return { mutate, mutateAsync, isPending };
}

export function useAddPlaylistTracks() {
  return useMutation(
    async ({
      playlistId,
      trackId,
      track,
    }: {
      playlistId: string;
      trackId: string;
      track?: Track;
    }) => {
      if (!isLocalPlaylistId(playlistId)) {
        return api.addPlaylistTrack(playlistId, trackId);
      }
      const snapshot = track ?? (await clientCatalog.resolveSnapshot(trackId));
      if (!snapshot) throw new Error("Track not found");
      return addLocalPlaylistTrack(playlistId, toClientTrack(snapshot));
    },
  );
}

export function useRemovePlaylistTracks() {
  return useMutation<{ playlistId: string; itemId: string }, unknown>(
    async ({ playlistId, itemId }) => {
      if (isLocalPlaylistId(playlistId)) {
        removeLocalPlaylistTrack(playlistId, itemId);
        return;
      }
      return api.removePlaylistItem(playlistId, itemId);
    },
  );
}

export function useReorderPlaylistTracks() {
  return useMutation<
    {
      playlistId: string;
      itemId: string;
      beforeItemId: string | null;
      revision: number;
    },
    unknown
  >(async ({ playlistId, itemId, beforeItemId, revision }) => {
    if (isLocalPlaylistId(playlistId)) {
      moveLocalPlaylistTrack(playlistId, itemId, beforeItemId);
      return;
    }
    return api.movePlaylistItem(playlistId, itemId, beforeItemId, revision);
  });
}

export function useCreatePlaylist() {
  return useMutation(
    async ({ title, description }: { title: string; description?: string }) => {
      if (!getAuthSession()?.accessToken) {
        return createLocalPlaylist(title, description);
      }
      return api.createPlaylist({ title, description });
    },
  );
}

export function useDeletePlaylist() {
  return useMutation(async ({ playlistId }: { playlistId: string }) => {
    evictPlaylistFromCache(playlistId);
    if (isLocalPlaylistId(playlistId)) {
      deleteLocalPlaylist(playlistId);
      return;
    }
    await api.deletePlaylist(playlistId);
  });
}

export function useSaveExternalItem() {
  return useMutation(
    ({
      type,
      id,
      snapshot,
    }: {
      type: "album" | "artist" | "playlist";
      id: string;
      snapshot?: Record<string, unknown>;
    }) =>
      api.saveCollection(
        `${type}s` as "albums" | "artists" | "playlists",
        id,
        snapshot,
      ),
  );
}

export function useRemoveExternalItem() {
  return useMutation(
    async ({
      type,
      id,
      isOwned,
    }: {
      type: "album" | "artist" | "playlist";
      id: string;
      isOwned?: boolean;
    }) => {
      if (type === "playlist") {
        evictPlaylistFromCache(id);
        if (isLocalPlaylistId(id)) {
          deleteLocalPlaylist(id);
          return;
        }
        if (isOwned === false) {
          return api.removeCollection("playlists", id);
        }
        try {
          const res = await api.deletePlaylist(id);
          // purge any saved collection reference in case it was both created and saved
          await api.removeCollection("playlists", id).catch(() => {});
          return res;
        } catch (err: unknown) {
          if (isOwned === true) {
            throw err;
          }
          // fall back to removing from saved collections if playlist was not owned
          return api.removeCollection("playlists", id);
        }
      }
      return api.removeCollection(`${type}s` as "albums" | "artists", id);
    },
  );
}

type TrackMutationInput = string | { trackId: string; [key: string]: unknown };
const trackIdFrom = (input: TrackMutationInput) =>
  typeof input === "string" ? input : input.trackId;

function useTrackLikeMutation(liked: boolean) {
  const mutateAsync = useCallback(
    (input: TrackMutationInput) => setTrackLiked(trackIdFrom(input), liked),
    [liked],
  );
  const mutate = useCallback(
    (input: TrackMutationInput, options?: Options) => {
      void mutateAsync(input)
        .then((value) => options?.onSuccess?.(value))
        .catch((error) => options?.onError?.(error))
        .finally(() => options?.onSettled?.());
    },
    [mutateAsync],
  );
  return { mutate, mutateAsync, isPending: false };
}

export function useLikeTrack() {
  return useTrackLikeMutation(true);
}

export function useUnlikeTrack() {
  return useTrackLikeMutation(false);
}

export function useToggleTrackLike() {
  return useCallback(
    (
      trackId: string,
      options?: {
        track?: Track;
        onSuccess?: (liked: boolean) => void;
        onError?: (error: unknown) => void;
      },
    ): boolean => {
      const { liked, settled } = toggleTrackLike(trackId, options?.track);
      settled.then(
        () => options?.onSuccess?.(liked),
        (error) => options?.onError?.(error),
      );
      return liked;
    },
    [],
  );
}
