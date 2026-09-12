const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("osmo", {
  request: (payload) => ipcRenderer.invoke("sidecar:request", payload),
  onStatus: (handler) => {
    const wrapped = (_event, data) => handler(data);
    ipcRenderer.on("sidecar:status", wrapped);
    return () => ipcRenderer.removeListener("sidecar:status", wrapped);
  },
  onPacket: (handler) => {
    const wrapped = (_event, data) => handler(data);
    ipcRenderer.on("sidecar:packet", wrapped);
    return () => ipcRenderer.removeListener("sidecar:packet", wrapped);
  },
  onLog: (handler) => {
    const wrapped = (_event, data) => handler(data);
    ipcRenderer.on("sidecar:log", wrapped);
    return () => ipcRenderer.removeListener("sidecar:log", wrapped);
  },
  onEvent: (handler) => {
    const wrapped = (_event, data) => handler(data);
    ipcRenderer.on("sidecar:event", wrapped);
    return () => ipcRenderer.removeListener("sidecar:event", wrapped);
  },
});
