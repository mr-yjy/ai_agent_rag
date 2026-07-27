/* eslint-disable @typescript-eslint/no-require-imports */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld(
  "scholarPilotDesktop",
  Object.freeze({
    platform: process.platform,
    loadSettings: () => ipcRenderer.invoke("desktop-settings:load"),
    saveSettings: (settings) =>
      ipcRenderer.invoke("desktop-settings:save", settings),
    clearSettings: () => ipcRenderer.invoke("desktop-settings:clear"),
  }),
);
