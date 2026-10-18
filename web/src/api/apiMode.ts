// Where /api calls go. Production builds use the build-time VITE_API_MODE (default "live");
// development builds also honour a saved choice, so the mock can be switched on and off.
//   live  only the real backend
//   mock  only the offline mock (src/mocks), labelled in the banner
//   auto  the real backend; the mock answers only routes whose router has not landed yet
export const API_MODES = ["live", "mock", "auto"] as const;
export type ApiMode = (typeof API_MODES)[number];

const STORAGE_KEY = "hishab.apiMode";

function asMode(value: string | null | undefined): ApiMode | undefined {
  return API_MODES.find((mode) => mode === value);
}

export function resolveApiMode(env: { VITE_API_MODE?: string; PROD: boolean }, saved: string | null): ApiMode {
  const fromEnv = asMode(env.VITE_API_MODE);
  if (env.PROD) return fromEnv ?? "live";
  return asMode(saved) ?? fromEnv ?? "auto";
}

export function readSavedApiMode(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function saveApiMode(mode: ApiMode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore: development convenience only
  }
}
