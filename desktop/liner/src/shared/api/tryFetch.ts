import { rethrowIfAborted } from "@/shared/utils/abort";

async function tryFetch<T>(
  url: string,
  init: RequestInit,
  read: (response: Response) => Promise<T>,
): Promise<T | undefined> {
  try {
    const response = await fetch(url, init);
    if (!response.ok) return undefined;
    return await read(response);
  } catch {
    rethrowIfAborted(init.signal);
    return undefined;
  }
}

export function tryFetchJson(
  url: string,
  init: RequestInit = {},
): Promise<unknown> {
  return tryFetch(url, init, (response) => response.json() as Promise<unknown>);
}

export function tryFetchText(
  url: string,
  init: RequestInit = {},
): Promise<string | undefined> {
  return tryFetch(url, init, (response) => response.text());
}
