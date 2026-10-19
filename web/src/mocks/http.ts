// Request/response primitives for the offline mock API.
import type { ApiError } from "../api/contracts";
import type { MockDb } from "./db";

export interface MockRequest {
  method: string;
  path: string;
  params: Record<string, string>;
  query: URLSearchParams;
  body: unknown;
  headers: Headers;
}

export interface MockResult {
  status?: number;
  body?: unknown;
}

export type MockHandler = (request: MockRequest, db: MockDb) => MockResult;

export interface MockRoute {
  method: "GET" | "POST";
  /** Path with `:name` segments, e.g. "/api/mesh/rounds/:id/approve". */
  pattern: string;
  handler: MockHandler;
}

export function ok(body: unknown): MockResult {
  return { status: 200, body };
}

export function apiError(status: number, code: string, messageKey: string, detail?: Record<string, string>): MockResult {
  const body: ApiError = { code, message_key: messageKey, ...(detail ? { detail } : {}) };
  return { status, body };
}

/** Compile "/api/x/:id" into a matcher returning the params, or null. */
export function compilePattern(pattern: string): (path: string) => Record<string, string> | null {
  const keys: string[] = [];
  const source = pattern
    .split("/")
    .map((segment) => {
      if (segment.startsWith(":")) {
        keys.push(segment.slice(1));
        return "([^/]+)";
      }
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  const regex = new RegExp(`^${source}/?$`);
  return (path) => {
    const match = regex.exec(path);
    if (!match) return null;
    return Object.fromEntries(keys.map((key, i) => [key, decodeURIComponent(match[i + 1] ?? "")]));
  };
}

/** A body field as a string, or "" when missing. */
export function field(body: unknown, name: string): string {
  if (typeof body !== "object" || body === null) return "";
  const value = (body as Record<string, unknown>)[name];
  return typeof value === "string" ? value : "";
}
