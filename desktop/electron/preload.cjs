const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld(
  "dowflow",
  Object.freeze({
    desktop: Object.freeze({
      shell: "electron",
      getRuntimeInfo: () => ipcRenderer.invoke("dowflow:runtime-info"),
    }),
  }),
);
