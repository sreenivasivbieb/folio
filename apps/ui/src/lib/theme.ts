/** Appearance: light (default, the app's designed look), dark, or follow the OS. */
import { useSyncExternalStore } from "react";

export type ThemePref = "light" | "dark" | "system";
const KEY = "folio.theme";
const listeners = new Set<() => void>();
const media = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "system" || v === "light" ? v : "light";
  } catch {
    return "light";
  }
}

let pref: ThemePref = read();

function apply(): void {
  const dark = pref === "dark" || (pref === "system" && !!media?.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function initTheme(): void {
  apply();
  media?.addEventListener("change", () => {
    if (pref === "system") {
      apply();
      listeners.forEach((l) => l());
    }
  });
}

export function setTheme(next: ThemePref): void {
  pref = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* private storage unavailable: the choice lasts for this session */
  }
  apply();
  listeners.forEach((l) => l());
}

export function useTheme(): ThemePref {
  return useSyncExternalStore((l) => (listeners.add(l), () => listeners.delete(l)), () => pref);
}
