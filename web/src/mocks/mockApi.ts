// Offline mock API: answers /api/* from in-memory synthetic state (see api/apiMode.ts for modes).
// Tests use createMockFetch directly; the dev server installs it over window.fetch.
import type { ApiMode } from "../api/apiMode";
import { isApiError } from "../api/client";
import { recordMockedPath } from "../api/mockUsage";
import { createMockDb, type MockDb } from "./db";
import { apiError, compilePattern, type MockHandler, type MockRequest, type MockResult } from "./http";
import { ROUTES } from "./routes";

export const MOCK_HEADER = "X-Hishab-Mock";

/** Replace one route's answer, keyed "METHOD /api/path" (`:param` segments allowed). */
export type MockOverrides = Record<string, MockResult | MockHandler>;

export interface MockOptions {
  db?: MockDb;
  overrides?: MockOverrides;
  latencyMs?: number;
}

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

const compiledRoutes = ROUTES.map((route) => ({ ...route, match: compilePattern(route.pattern) }));

function baseOrigin(): string {
  return typeof location === "undefined" ? "http://localhost" : location.origin;
}

function urlOf(input: RequestInfo | URL): URL {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return new URL(raw, baseOrigin());
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== "string") return body ?? undefined;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}

export function createMockFetch({ db = createMockDb(), overrides = {}, latencyMs = 0 }: MockOptions = {}): Fetch {
  const overrideRoutes = Object.entries(overrides).map(([key, value]) => {
    const [method = "GET", pattern = ""] = key.split(" ");
    return { method, match: compilePattern(pattern), value };
  });

  return async (input, init = {}) => {
    const url = urlOf(input);
    const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const request: MockRequest = {
      method,
      path: url.pathname,
      params: {},
      query: url.searchParams,
      body: parseBody(init.body),
      headers: new Headers(init.headers),
    };

    let result: MockResult | undefined;
    for (const route of overrideRoutes) {
      const params = route.method === method ? route.match(url.pathname) : null;
      if (params) {
        result = typeof route.value === "function" ? route.value({ ...request, params }, db) : route.value;
        break;
      }
    }
    if (!result) {
      for (const route of compiledRoutes) {
        const params = route.method === method ? route.match(url.pathname) : null;
        if (params) {
          result = route.handler({ ...request, params }, db);
          break;
        }
      }
    }
    result ??= apiError(404, "not_found", "error.not_found");

    if (latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, latencyMs));
    const status = result.status ?? 200;
    const hasBody = result.body !== undefined && status !== 204;
    return new Response(hasBody ? JSON.stringify(result.body) : null, {
      status,
      headers: { "Content-Type": "application/json", [MOCK_HEADER]: "1" },
    });
  };
}

/** True when the real backend has no router for this path yet, or is not running at all. */
export async function isMissingRoute(response: Response): Promise<boolean> {
  if ([405, 502, 503, 504].includes(response.status)) return true;
  if (response.status !== 404 && response.status !== 500) return false;
  const text = await response.clone().text();
  // Vite's dev proxy answers an empty 500 when the API process is down.
  if (response.status === 500) return text.trim() === "";
  try {
    const body = JSON.parse(text) as unknown;
    // FastAPI's own "no such route" body; a router's real 404s are ApiError bodies.
    return !isApiError(body) && (body as { detail?: unknown } | null)?.detail === "Not Found";
  } catch {
    return false;
  }
}

/** Route /api/* calls on `target` (window in the browser) through the mock, per `mode`. */
export function installMockApi(mode: ApiMode, options: MockOptions = {}, target: { fetch: Fetch } = globalThis): void {
  if (mode === "live") return;
  const realFetch: Fetch = target.fetch.bind(target);
  const mockFetch = createMockFetch(options);
  const serveFromMock = async (path: string, input: RequestInfo | URL, init?: RequestInit) => {
    recordMockedPath(path);
    return mockFetch(input, init);
  };

  target.fetch = async (input, init) => {
    const url = urlOf(input);
    if (url.origin !== baseOrigin() || !url.pathname.startsWith("/api/")) return realFetch(input, init);
    if (mode === "mock") return serveFromMock(url.pathname, input, init);
    try {
      const response = await realFetch(input, init);
      return (await isMissingRoute(response)) ? serveFromMock(url.pathname, input, init) : response;
    } catch (error) {
      if (init?.signal?.aborted) throw error;
      return serveFromMock(url.pathname, input, init);
    }
  };
}
