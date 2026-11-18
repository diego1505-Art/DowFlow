const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld(
  "dowflow",
  Object.freeze({
    desktop: Object.freeze({
      shell: "electron",
      getRuntimeInfo: () => ipcRenderer.invoke("dowflow:runtime-info"),
    }),
    youtube: Object.freeze({
      mintPoToken: (identifier) =>
        ipcRenderer.invoke("dowflow:youtube:mint-po-token", identifier),
    }),
  }),
);
