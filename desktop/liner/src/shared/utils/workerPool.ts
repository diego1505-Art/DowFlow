export async function runWorkerPool<T>(
  items: readonly T[],
  concurrency: number,
  task: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let cursor = 0;
  let failed = false;
  const worker = async () => {
    while (cursor < items.length && !failed) {
      const index = cursor++;
      await task(items[index], index);
    }
  };
  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    () =>
      worker().catch((error: unknown) => {
        failed = true;
        throw error;
      }),
  );
  await Promise.all(workers);
}
