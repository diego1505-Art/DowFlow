// Adapted for private DowFlow use from Liner commit 5bec3c7.
export type JsonRecord = Record<string, unknown>;

export function asRecord(value: unknown): JsonRecord | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : undefined;
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function collectByKey(value: unknown, key: string, out: unknown[] = []): unknown[] {
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
