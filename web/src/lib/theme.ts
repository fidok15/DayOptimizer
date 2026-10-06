import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "dayoptimizer-theme";

const current = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const listeners = new Set<() => void>();

export const setTheme = (t: Theme) => {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
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
