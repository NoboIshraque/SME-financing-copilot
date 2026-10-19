// Signing demo roles in through the real auth API (WP-11), and the saved sessions journeys reuse.
import { join } from "node:path";

import { expect, type APIRequestContext } from "@playwright/test";

import { homeAccount, withRateLimit, type DemoAccount, type Role } from "./accounts";
import { TARGET, WEB_DIR } from "./target";
import { withFreshCode } from "./totp";

/** Roles signed in once per run by e2e/auth.setup.ts. */
export const SAVED_ROLES = ["owner", "staff", "lender_viewer"] as const satisfies readonly Role[];
export type SavedRole = (typeof SAVED_ROLES)[number];

/** Playwright storage state (session cookie) for a role on this run's target. */
export function sessionFile(role: SavedRole | "critical_owner"): string {
  return join(WEB_DIR, "e2e", ".auth", `${TARGET}-${role}.json`);
}

interface ApiErrorBody {
  code?: string;
}

/** Password, then (for owners) a fresh TOTP code; the session cookie lands in `api`. */
export async function signInThroughApi(api: APIRequestContext, account: DemoAccount): Promise<void> {
  const login = await withRateLimit(() =>
    api.post("/api/auth/login", { data: { email: account.email, password: account.password } }),
  );
  expect(login.status(), `sign-in for ${account.email}`).toBe(200);
  const body = (await login.json()) as { status: "ok" | "totp_required" };
  if (body.status === "totp_required") {
    await withFreshCode(api, account, async (code) => {
      const verified = await withRateLimit(() => api.post("/api/auth/login/totp", { data: { code } }));
      if (verified.ok()) return true;
      const error = (await verified.json().catch(() => ({}))) as ApiErrorBody;
      if (verified.status() === 401 && error.code === "invalid_totp") return false;
      throw new Error(`TOTP step for ${account.email}: HTTP ${verified.status()} ${error.code ?? ""}`);
    });
  }
}

export async function saveSession(api: APIRequestContext, role: SavedRole): Promise<DemoAccount> {
  const account = await homeAccount(api, role);
  await signInThroughApi(api, account);
  const me = await api.get("/api/auth/me");
  expect(me.status()).toBe(200);
  expect(((await me.json()) as { principal: { role: string } }).principal.role).toBe(role);
  await api.storageState({ path: sessionFile(role) });
  return account;
}
