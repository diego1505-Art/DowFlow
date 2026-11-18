import { ipcRenderer } from "electron";
import { mintWebPoToken } from "./web-minter.js";

const REQUEST_CHANNEL = "dowflow-potoken-request";
const RESULT_CHANNEL = "dowflow-potoken-result";
const READY_CHANNEL = "dowflow-potoken-ready";

ipcRenderer.on(REQUEST_CHANNEL, async (_event, request) => {
  const id = request && Number.isSafeInteger(request.id) ? request.id : null;
  try {
    if (id === null || !request.payload || typeof request.payload.identifier !== "string") {
      throw new Error("Invalid PoToken request");
    }
    const value = await mintWebPoToken(request.payload.identifier);
    ipcRenderer.send(RESULT_CHANNEL, { id, value });
  } catch (error) {
    ipcRenderer.send(RESULT_CHANNEL, {
      id,
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

window.addEventListener(
  "DOMContentLoaded",
  () => ipcRenderer.send(READY_CHANNEL),
  { once: true },
);
