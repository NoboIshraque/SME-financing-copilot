// Light/dark theme. An explicit choice is remembered; "system" follows the OS setting.
import { useSyncExternalStore } from "react";

export const THEMES = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof THEMES)[number];
export type Theme = "light" | "dark";

const STORAGE_KEY = "hishab.theme";

function readSaved(): ThemePreference {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && (THEMES as readonly string[]).includes(saved)) return saved as ThemePreference;
  } catch {
    // storage can be unavailable (private mode): follow the OS
  }
  return "system";
}

let preference: ThemePreference = readSaved();
const listeners = new Set<() => void>();

export function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(choice: ThemePreference): Theme {
  if (choice === "system") return systemPrefersDark() ? "dark" : "light";
  return choice;
}

/** Put the resolved theme on <html>; returns it. */
export function applyTheme(choice: ThemePreference = preference): Theme {
  const theme = resolveTheme(choice);
  document.documentElement.classList.toggle("dark", theme === "dark");
  return theme;
}

export function getThemePreference(): ThemePreference {
  return preference;
}

export function setThemePreference(choice: ThemePreference): void {
  preference = choice;
  try {
    if (choice === "system") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // remembering the theme is a convenience only
  }
  applyTheme(choice);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribe, getThemePreference);
}

/** Re-apply when the OS switches between light and dark while the choice is "system". */
export function watchSystemTheme(): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (preference === "system") {
      applyTheme("system");
      listeners.forEach((listener) => listener());
    }
  };
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
