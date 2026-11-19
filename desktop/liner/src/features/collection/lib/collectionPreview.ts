export interface CollectionPreview {
  coverUrl?: string;
  title?: string;
  subtitle?: string;
}

export type CollectionKind = "album" | "playlist";

export function collectionPath(type: CollectionKind, id: string): string {
  return `/collection?type=${type}&id=${encodeURIComponent(id)}`;
}

export function collectionPreviewState(preview: CollectionPreview): {
  collectionPreview: CollectionPreview;
} {
  return { collectionPreview: preview };
}

export function readCollectionPreview(
  state: unknown,
): CollectionPreview | undefined {
  if (!state || typeof state !== "object") return undefined;
  const preview = (state as { collectionPreview?: unknown }).collectionPreview;
  if (!preview || typeof preview !== "object") return undefined;
  const { coverUrl, title, subtitle } = preview as Record<string, unknown>;
  const text = (value: unknown) =>
    typeof value === "string" && value ? value : undefined;
  return {
    coverUrl: text(coverUrl),
    title: text(title),
    subtitle: text(subtitle),
  };
}
