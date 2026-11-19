const pendingWrites = new Map<string, string>();

function flushPendingWrites() {
  if (typeof localStorage === "undefined" || pendingWrites.size === 0) return;
  for (const [name, value] of pendingWrites.entries()) {
    try {
      localStorage.setItem(name, value);
    } catch {}
  }
  pendingWrites.clear();
}

if (typeof window !== "undefined") {
  setInterval(flushPendingWrites, 1000);

  window.addEventListener("beforeunload", flushPendingWrites);
}

export const debouncedStorage = {
  getItem: (name: string) => {
    if (typeof window === "undefined" || typeof localStorage === "undefined")
      return null;
    if (pendingWrites.has(name)) {
      return pendingWrites.get(name)!;
    }
    return localStorage.getItem(name);
  },
  setItem: (name: string, value: string) => {
    if (typeof window === "undefined") return;
    pendingWrites.set(name, value);
  },
  removeItem: (name: string) => {
    if (typeof window === "undefined") return;
    pendingWrites.delete(name);
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem(name);
    }
  },
  flush: flushPendingWrites,
};

type StringStorage = {
  getItem: (name: string) => string | null;
  setItem: (name: string, value: string) => void;
  removeItem: (name: string) => void;
};

type PersistedEnvelope<S> = { state: S; version?: number };

export function createIncrementalJSONStorage<S>(
  storage: StringStorage = debouncedStorage,
) {
  const written = new Map<
    string,
    {
      fields: Map<string, { value: unknown; json: string | undefined }>;
      version?: number;
    }
  >();

  const isUnchanged = (
    name: string,
    state: Record<string, unknown>,
    version?: number,
  ) => {
    const prev = written.get(name);
    if (!prev || prev.version !== version) return false;
    const keys = Object.keys(state);
    if (keys.length !== prev.fields.size) return false;
    for (const key of keys) {
      const cached = prev.fields.get(key);
      if (!cached || !Object.is(cached.value, state[key])) return false;
    }
    return true;
  };

  return {
    getItem: (name: string): PersistedEnvelope<S> | null => {
      const raw = storage.getItem(name);
      if (raw === null) return null;
      return JSON.parse(raw) as PersistedEnvelope<S>;
    },
    setItem: (name: string, value: PersistedEnvelope<S>) => {
      const state = value.state as Record<string, unknown>;
      if (isUnchanged(name, state, value.version)) return;
      const prevFields = written.get(name)?.fields;
      const fields = new Map<
        string,
        { value: unknown; json: string | undefined }
      >();
      const parts: string[] = [];
      for (const key of Object.keys(state)) {
        const field = state[key];
        const cached = prevFields?.get(key);
        const json =
          cached && Object.is(cached.value, field)
            ? cached.json
            : JSON.stringify(field);
        fields.set(key, { value: field, json });
        if (json !== undefined) parts.push(`${JSON.stringify(key)}:${json}`);
      }
      written.set(name, { fields, version: value.version });
      const versionPart =
        value.version === undefined
          ? ""
          : `,"version":${JSON.stringify(value.version)}`;
      storage.setItem(name, `{"state":{${parts.join(",")}}${versionPart}}`);
    },
    removeItem: (name: string) => {
      written.delete(name);
      storage.removeItem(name);
    },
  };
}
