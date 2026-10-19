// Which target this run drives (playwright.config.ts) and which backend routers it has.
//
// Local runs the dev stack in API mode "auto": the web app asks the real backend first and the
// offline mock (web/src/mocks) answers only routes whose router has not landed. Hosted runs a
// production build in mode "live": a journey whose router is not deployed there cannot pass, so
// it is skipped with the missing route named in the report, never faked.
import { fileURLToPath } from "node:url";

import { request, test, type APIRequestContext } from "@playwright/test";

export type Target = "local" | "hosted";

export const HOSTED_URL = process.env.E2E_BASE_URL?.replace(/\/+$/, "");
export const TARGET: Target = HOSTED_URL ? "hosted" : "local";
export const BASE_URL = HOSTED_URL ?? "http://localhost:5173";
export const IGNORE_HTTPS_ERRORS = HOSTED_URL ? new URL(HOSTED_URL).hostname === "localhost" : false;

/** The web/ directory (this file is web/e2e/support/target.ts). */
export const WEB_DIR = fileURLToPath(new URL("../../", import.meta.url));

/** An API context on this target: anonymous (a visitor, or a probe), or with a saved session. */
export function apiContext(storageState?: string): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: IGNORE_HTTPS_ERRORS, storageState });
}

const probes = new Map<string, Promise<boolean>>();

/**
 * True when the backend serves `METHOD /api/path`, false when FastAPI answers with its bare
 * "no such route" (404 `{"detail":"Not Found"}` or 405) the way web/src/mocks/mockApi.ts
 * `isMissingRoute` reads it. Probes go without a session, so a live route only refuses them.
 */
export function routeIsLive(route: string): Promise<boolean> {
  let probe = probes.get(route);
  if (!probe) {
    probe = probeRoute(route);
    probes.set(route, probe);
  }
  return probe;
}

async function probeRoute(route: string): Promise<boolean> {
  const [method = "GET", path = "/"] = route.split(" ");
  const context = await apiContext();
  try {
    const response = await context.fetch(path, {
      method,
      data: method === "GET" ? undefined : {},
      failOnStatusCode: false,
      maxRedirects: 0,
    });
    if (response.status() === 405) return false;
    if (response.status() !== 404) return true;
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    return body?.detail !== "Not Found";
  } finally {
    await context.dispose();
  }
}

/**
 * Declare the backend routes a journey depends on. Hosted: skip when any is not deployed, naming
 * them. Local: record which ones the offline mock answers, so the report says so, or skip when
 * the journey needs what the mock cannot do (`mockCannot` says what).
 */
export async function needsRoutes(
  routes: readonly string[],
  { mockCannot }: { mockCannot?: string } = {},
): Promise<Record<string, boolean>> {
  const live: Record<string, boolean> = {};
  for (const route of routes) live[route] = await routeIsLive(route);
  const missing = routes.filter((route) => !live[route]);
  if (missing.length > 0) {
    if (TARGET === "hosted") test.skip(true, `Not deployed on ${BASE_URL}: ${missing.join(", ")}`);
    if (mockCannot) test.skip(true, `Needs the real router (${missing.join(", ")}): the offline mock cannot ${mockCannot}`);
    test.info().annotations.push({ type: "offline mock", description: missing.join(", ") });
  }
  return live;
}
