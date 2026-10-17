import { describe, expect, it, vi } from "vitest";

import { ApiRequestError, apiGet, apiPost } from "./client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client", () => {
  it("returns parsed JSON on success", async () => {
    mockFetch(200, { status: "ok" });
    await expect(apiGet<{ status: string }>("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("raises ApiRequestError carrying the ApiError body", async () => {
    mockFetch(403, { code: "forbidden", message_key: "error.forbidden" });
    const error = await apiGet("/api/cash/forecast").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).status).toBe(403);
    expect((error as ApiRequestError).body?.code).toBe("forbidden");
  });

  it("sends JSON bodies for POST", async () => {
    const fetchMock = mockFetch(200, {});
    await apiPost("/api/financing/match", { amount: "200000.00" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"amount":"200000.00"}');
  });

  it("refuses paths outside /api/ so nothing calls third-party hosts", async () => {
    await expect(apiGet("https://example.com/x")).rejects.toThrow("/api/");
  });
});
