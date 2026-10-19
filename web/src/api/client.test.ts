import { describe, expect, it, vi } from "vitest";

import { ApiRequestError, apiGet, apiPost, onUnauthorized } from "./client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
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

  it("drops error bodies that are not ApiError (e.g. FastAPI's bare 404)", async () => {
    mockFetch(404, { detail: "Not Found" });
    const error = (await apiGet("/api/unknown").catch((e: unknown) => e)) as ApiRequestError;
    expect(error.status).toBe(404);
    expect(error.body).toBeNull();
  });

  it("sends JSON bodies for POST", async () => {
    const fetchMock = mockFetch(200, {});
    await apiPost("/api/financing/match", { amount: "200000.00" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"amount":"200000.00"}');
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("sends the idempotency key and step-up code an EXECUTE approval needs", async () => {
    const fetchMock = mockFetch(200, {});
    await apiPost("/api/approvals/ap-1/approve", {}, { idempotencyKey: "idem-1", stepUpCode: "246810" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ "X-Idempotency-Key": "idem-1", "X-Step-Up-Code": "246810" });
  });

  it("uploads FormData as multipart, without a JSON content type", async () => {
    const fetchMock = mockFetch(200, {});
    const form = new FormData();
    form.append("file", new Blob(["date,amount"]), "bkash.csv");
    await apiPost("/api/ingest/preview", form);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe(form);
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("returns undefined for 204 No Content", async () => {
    mockFetch(204, undefined);
    await expect(apiPost("/api/auth/logout", {})).resolves.toBeUndefined();
  });

  it("tells listeners when the session has ended (401), until they unsubscribe", async () => {
    mockFetch(401, { code: "not_authenticated", message_key: "error.not_authenticated" });
    const listener = vi.fn();
    const stop = onUnauthorized(listener);
    await expect(apiGet("/api/cash/forecast")).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).toHaveBeenCalledTimes(1);

    stop();
    mockFetch(401, { code: "not_authenticated", message_key: "error.not_authenticated" });
    await expect(apiGet("/api/cash/forecast")).rejects.toBeInstanceOf(ApiRequestError);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("does not sign the user out for a wrong step-up code (WP-11 answers 401 invalid_step_up)", async () => {
    mockFetch(401, { code: "invalid_step_up", message_key: "error.invalid_step_up" });
    const listener = vi.fn();
    const stop = onUnauthorized(listener);
    const error = (await apiPost("/api/approvals/ap-1/approve", {}, { stepUpCode: "000000" }).catch((e: unknown) => e)) as ApiRequestError;
    expect(error.body?.code).toBe("invalid_step_up");
    expect(listener).not.toHaveBeenCalled();
    stop();
  });

  it("refuses paths outside /api/ so nothing calls third-party hosts", async () => {
    await expect(apiGet("https://example.com/x")).rejects.toThrow("/api/");
  });
});
