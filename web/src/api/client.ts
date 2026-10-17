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

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, { ...init, method: "GET" });
}

export async function apiPost<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  if (!path.startsWith("/api/")) throw new Error("API paths start with /api/");
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    let body: ApiError | null = null;
    try {
      body = (await response.json()) as ApiError;
    } catch {
      body = null;
    }
    throw new ApiRequestError(response.status, body);
  }
  return (await response.json()) as T;
}

export interface Health {
  status: string;
  contracts_version: string;
  data_mode_banner: "synthetic" | null;
}
