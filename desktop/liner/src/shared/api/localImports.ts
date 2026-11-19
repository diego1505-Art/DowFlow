import type { ImportJob, ImportReview, Track } from "@/shared/contracts";

export const LOCAL_IMPORT_PREFIX = "local_";

export interface LocalImportHandler {
  getJob(jobId: string): ImportJob | undefined;
  getReview(jobId: string): ImportReview[];
  finalize(
    jobId: string,
    tracks: Track[],
    title?: string,
    description?: string,
  ): Promise<{ finalized: boolean }>;
}

let activeHandler: LocalImportHandler | null = null;

export function registerLocalImportHandler(handler: LocalImportHandler): void {
  activeHandler = handler;
}

export function getLocalImportHandler(): LocalImportHandler {
  if (!activeHandler) throw new Error("Local import handler is not registered");
  return activeHandler;
}
