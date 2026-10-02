import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "dayoptimizer-theme";

const current = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const listeners = new Set<() => void>();

/** index.html applies the saved choice (else the system preference) before first paint. */
export const setTheme = (t: Theme) => {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    // storage blocked: applied for this visit only
  }
  listeners.forEach((l) => l());
};

export const useTheme = (): Theme =>
  useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    current,
  );
