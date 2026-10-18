// The signed-in session (WP-11 cookie session), cached by react-query.
import { useQuery } from "@tanstack/react-query";

import { ApiRequestError } from "../api/client";
import { api } from "../api/endpoints";
import type { Session } from "../api/types";

export const SESSION_KEY = ["session"] as const;

/** The current session, or null when signed out (401). */
export async function fetchSession(): Promise<Session | null> {
  try {
    return await api.auth.me();
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 401) return null;
    throw error;
  }
}

export function useSession() {
  return useQuery({ queryKey: SESSION_KEY, queryFn: fetchSession, staleTime: 5 * 60_000 });
}

/** The session inside screens wrapped by RequireAuth, where it is always present. */
export function useRequiredSession(): Session {
  const { data } = useSession();
  if (!data) throw new Error("useRequiredSession used outside RequireAuth");
  return data;
}

/** Only paths inside this app, so a crafted ?next= link cannot send anyone to another site. */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next === "/login" || next.startsWith("/login?") || next.startsWith("/login/")) return "/";
  return next;
}
