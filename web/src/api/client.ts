// Typed API client. Every response is JSON; errors use the ApiError contract.
import type { ApiError } from "./contracts";

export class ApiRequestError extends Error {
  readonly status: number;
  readonly body: ApiError | null;

  constructor(status: number, body: ApiError | null) {
    super(body?.message_key ?? `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  /** Sent as X-Idempotency-Key, so a retried approval runs only once on the server. */
  idempotencyKey?: string;
  /** Fresh TOTP code for EXECUTE-tier actions, sent as X-Step-Up-Code. */
  stepUpCode?: string;
}

const unauthorizedListeners = new Set<() => void>();

/** Called whenever the server answers 401 (signed out or session expired). */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

export async function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return request<T>(path, "GET", undefined, options);
}

/** POST a JSON body, or a FormData body for file uploads. */
export async function apiPost<T>(path: string, body: unknown, options: RequestOptions = {}): Promise<T> {
  return request<T>(path, "POST", body, options);
}

export function isApiError(value: unknown): value is ApiError {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message_key === "string";
}

async function request<T>(path: string, method: "GET" | "POST", body: unknown, options: RequestOptions): Promise<T> {
  if (!path.startsWith("/api/")) throw new Error("API paths start with /api/");
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  if (options.idempotencyKey) headers["X-Idempotency-Key"] = options.idempotencyKey;
  if (options.stepUpCode) headers["X-Step-Up-Code"] = options.stepUpCode;

  const response = await fetch(path, {
    method,
    body: payload,
    headers,
    credentials: "same-origin",
    signal: options.signal,
  });
  if (!response.ok) {
    let errorBody: unknown = null;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = null;
    }
    const apiError = isApiError(errorBody) ? errorBody : null;
    // Only a lost session signs the user out. A 401 for a wrong password, TOTP or step-up code
    // (error.invalid_step_up, ...) is an answer to that one request, shown where it was asked.
    if (response.status === 401 && (apiError === null || apiError.code === "not_authenticated")) {
      unauthorizedListeners.forEach((listener) => listener());
    }
    throw new ApiRequestError(response.status, apiError);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}
