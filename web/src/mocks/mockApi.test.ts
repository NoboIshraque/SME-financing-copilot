import { beforeEach, describe, expect, it, vi } from "vitest";

import { resolveApiMode } from "../api/apiMode";
import { mockedPathCount, resetMockUsage } from "../api/mockUsage";
import { DEMO_PASSWORD, DEMO_TOTP_CODE } from "./db";
import { MOCK_HEADER, createMockFetch, installMockApi, isMissingRoute } from "./mockApi";

type Fetch = ReturnType<typeof createMockFetch>;

async function post(fetchMock: Fetch, path: string, body: unknown) {
  return fetchMock(path, { method: "POST", body: JSON.stringify(body) });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => resetMockUsage());

describe("mock API", () => {
  it("serves the synthetic health banner and an ApiError 404 for unknown routes", async () => {
    const fetchMock = createMockFetch();
    const health = await (await fetchMock("/api/health")).json();
    expect(health.data_mode_banner).toBe("synthetic");

    const missing = await fetchMock("/api/no-such-route");
    expect(missing.status).toBe(404);
    expect(await missing.json()).toEqual({ code: "not_found", message_key: "error.not_found" });
  });

  it("signs a password-only account in and out", async () => {
    const fetchMock = createMockFetch();
    const login = await (await post(fetchMock, "/api/auth/login", { email: "accountant@hishab.demo", password: DEMO_PASSWORD })).json();
    expect(login.status).toBe("ok");
    expect(login.session.principal.role).toBe("accountant");
    expect((await fetchMock("/api/auth/me")).status).toBe(200);

    expect((await fetchMock("/api/auth/logout", { method: "POST" })).status).toBe(204);
    expect((await fetchMock("/api/auth/me")).status).toBe(401);
  });

  it("asks a TOTP account for its code and accepts only the right one", async () => {
    const fetchMock = createMockFetch();
    const first = await (await post(fetchMock, "/api/auth/login", { email: "owner@hishab.demo", password: DEMO_PASSWORD })).json();
    expect(first).toEqual({ status: "totp_required" });
    expect((await fetchMock("/api/auth/me")).status).toBe(401);

    const wrong = await post(fetchMock, "/api/auth/login/totp", { code: "000000" });
    expect(wrong.status).toBe(401);
    expect((await wrong.json()).message_key).toBe("error.invalid_totp");

    const right = await post(fetchMock, "/api/auth/login/totp", { code: DEMO_TOTP_CODE });
    expect((await right.json()).principal.role).toBe("owner");
  });

  it("locks an account after five wrong passwords, even against the right one", async () => {
    const fetchMock = createMockFetch();
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const response = await post(fetchMock, "/api/auth/login", { email: "staff@hishab.demo", password: "guess" });
      expect(response.status).toBe(401);
    }
    const locked = await post(fetchMock, "/api/auth/login", { email: "staff@hishab.demo", password: DEMO_PASSWORD });
    expect(locked.status).toBe(423);
    expect((await locked.json()).detail).toEqual({ retry_after_minutes: "15" });
  });

  it("lets a test replace one route, with path parameters", async () => {
    const fetchMock = createMockFetch({
      overrides: {
        "GET /api/health": { status: 503, body: { code: "down", message_key: "error.server" } },
        "GET /api/items/:id": (request) => ({ body: { id: request.params.id } }),
      },
    });
    expect((await fetchMock("/api/health")).status).toBe(503);
    expect(await (await fetchMock("/api/items/inv%2F7")).json()).toEqual({ id: "inv/7" });
  });
});

describe("auto mode (mock only for routers that have not landed)", () => {
  it("prefers the real backend and falls back on FastAPI's bare 'Not Found' only", async () => {
    const target = {
      fetch: vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path === "/api/health") return json({ status: "ok", data_mode_banner: null });
        if (path === "/api/explain/fig-x") return json({ code: "figure_not_found", message_key: "error.figure_not_found" }, 404);
        return json({ detail: "Not Found" }, 404);
      }),
    };
    installMockApi("auto", {}, target);

    expect((await (await target.fetch("/api/health")).json()).data_mode_banner).toBeNull();
    const realNotFound = await target.fetch("/api/explain/fig-x");
    expect(realNotFound.status).toBe(404);
    expect(realNotFound.headers.get(MOCK_HEADER)).toBeNull();

    const fromMock = await target.fetch("/api/auth/demo-accounts");
    expect(fromMock.headers.get(MOCK_HEADER)).toBe("1");
    expect(mockedPathCount()).toBe(1);
  });

  it("falls back when the backend is not running", async () => {
    const target = { fetch: vi.fn().mockRejectedValue(new TypeError("Failed to fetch")) };
    installMockApi("auto", {}, target);
    const response = await target.fetch("/api/health");
    expect(response.headers.get(MOCK_HEADER)).toBe("1");
  });

  it("never intercepts other hosts, non-API paths, or live mode", async () => {
    const real = vi.fn().mockResolvedValue(json({ real: true }));
    const target = { fetch: real };
    installMockApi("mock", {}, target);
    await target.fetch("/assets/logo.svg");
    await target.fetch("https://example.com/api/health");
    expect(real).toHaveBeenCalledTimes(2);

    const liveTarget = { fetch: real };
    installMockApi("live", {}, liveTarget);
    expect(liveTarget.fetch).toBe(real);
  });
});

describe("isMissingRoute", () => {
  it.each([
    ["FastAPI has no router for the path", json({ detail: "Not Found" }, 404), true],
    ["a router's own 404 is real", json({ code: "fact_not_found", message_key: "error.fact_not_found" }, 404), false],
    ["the method is not routed yet", json({ detail: "Method Not Allowed" }, 405), true],
    ["Vite's proxy cannot reach the API", new Response("", { status: 500 }), true],
    ["the API crashed: a real error to surface", new Response("Internal Server Error", { status: 500 }), false],
    ["a normal answer", json({ status: "ok" }), false],
  ])("%s -> %s", async (_case, response, expected) => {
    expect(await isMissingRoute(response)).toBe(expected);
  });
});

describe("resolveApiMode", () => {
  it.each([
    ["production defaults to live", { PROD: true }, null, "live"],
    ["production ignores a saved choice", { PROD: true }, "mock", "live"],
    ["production honours the build setting", { PROD: true, VITE_API_MODE: "auto" }, null, "auto"],
    ["development defaults to auto", { PROD: false }, null, "auto"],
    ["development honours a saved choice over the build", { PROD: false, VITE_API_MODE: "live" }, "mock", "mock"],
    ["unknown values are ignored", { PROD: false, VITE_API_MODE: "offline" }, "bogus", "auto"],
  ] as const)("%s", (_case, env, saved, expected) => {
    expect(resolveApiMode(env, saved)).toBe(expected);
  });
});
