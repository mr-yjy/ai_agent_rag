import type { UserLlmModel } from "./llm-models";

export interface DesktopLlmSettings {
  apiKey: string;
  model: UserLlmModel;
}

export interface ScholarPilotDesktopBridge {
  platform: string;
  loadSettings: () => Promise<DesktopLlmSettings | null>;
  saveSettings: (
    settings: DesktopLlmSettings,
  ) => Promise<{ ok: boolean }>;
  clearSettings: () => Promise<{ ok: boolean }>;
}

declare global {
  interface Window {
    scholarPilotDesktop?: ScholarPilotDesktopBridge;
  }
}

export function getDesktopBridge() {
  return typeof window === "undefined"
    ? undefined
    : window.scholarPilotDesktop;
}
