export type JsonRecord = Record<string, unknown>;

export function asRecord(value: unknown): JsonRecord | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : undefined;
}

export function isRecord(value: unknown): value is JsonRecord {
  return asRecord(value) !== undefined;
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export function trimmedString(value: unknown): string | undefined {
  const trimmed = typeof value === "string" ? value.trim() : "";
  return trimmed || undefined;
}

export function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

export function recordAt(
  value: unknown,
  ...path: string[]
): JsonRecord | undefined {
  let current = asRecord(value);
  for (const key of path) {
    current = asRecord(current?.[key]);
    if (!current) return undefined;
  }
  return current;
}

export function findFirst(value: unknown, key: string): JsonRecord | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirst(item, key);
      if (found) return found;
    }
    return undefined;
  }
  const record = asRecord(value);
  if (!record) return undefined;
  const direct = asRecord(record[key]);
  if (direct) return direct;
  for (const child of Object.values(record)) {
    const found = findFirst(child, key);
    if (found) return found;
  }
  return undefined;
}

export function walkRecords(
  value: unknown,
  visit: (record: JsonRecord) => boolean,
): void {
  if (Array.isArray(value)) {
    value.forEach((item) => walkRecords(item, visit));
    return;
  }
  const record = asRecord(value);
  if (!record || visit(record)) return;
  for (const child of Object.values(record)) walkRecords(child, visit);
}

export function collectByKey(
  value: unknown,
  key: string,
  out: unknown[] = [],
): unknown[] {
  if (Array.isArray(value)) {
    for (const entry of value) collectByKey(entry, key, out);
    return out;
  }
  const record = asRecord(value);
  if (!record) return out;
  for (const [name, entry] of Object.entries(record)) {
    if (name === key) out.push(entry);
    collectByKey(entry, key, out);
  }
  return out;
}

export function parseJsonSafe(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return undefined;
  }
}
