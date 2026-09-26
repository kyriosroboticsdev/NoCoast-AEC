const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  backendUrl: process.env.BIM_BACKEND_URL || "http://127.0.0.1:8765",
  openIfc: () => ipcRenderer.invoke("ifc:open"),
  saveIfc: (name, data) => ipcRenderer.invoke("ifc:save", { name, data }),
});
