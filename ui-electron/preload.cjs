// SERAPHIM VESSEL — preload script (S03 skeleton)
// Exposes minimal bridge; no real API calls yet.

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("seraphim", {
  version: "0.1.0-skeleton",
});
