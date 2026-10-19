// Records which API paths were answered by the offline mock (src/mocks), so the banner can say
// so. Kept apart from the mock itself: production bundles import this file, never the fixtures.
import { useSyncExternalStore } from "react";

const mockedPaths = new Set<string>();
const listeners = new Set<() => void>();
let snapshot = 0;

export function recordMockedPath(path: string): void {
  if (mockedPaths.has(path)) return;
  mockedPaths.add(path);
  snapshot = mockedPaths.size;
  listeners.forEach((listener) => listener());
}

export function mockedPathCount(): number {
  return snapshot;
}

export function resetMockUsage(): void {
  mockedPaths.clear();
  snapshot = 0;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** True once any response on this page came from the mock. */
export function useMockInUse(): boolean {
  return useSyncExternalStore(subscribe, mockedPathCount) > 0;
}
