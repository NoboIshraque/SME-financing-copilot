// The public demo accounts (WP-11, demo mode only): GET /api/auth/demo-accounts lists each one's
// email, password, role, business and, for owners, the current TOTP code. Journeys pick accounts
// from this list instead of hard-coding credentials, so they follow whatever the server seeds.
import { expect, type APIRequestContext, type APIResponse } from "@playwright/test";

export type Role = "owner" | "accountant" | "staff" | "lender_viewer" | "compliance";

export interface DemoAccount {
  email: string;
  password: string;
  role: Role;
  business_name: string;
  totp_hint?: string | null;
}

/** The business most journeys run on: the first one the server lists (the grocery). */
export const HOME_TENANT_INDEX = 0;

export async function demoAccounts(api: APIRequestContext): Promise<DemoAccount[]> {
  const response = await withRateLimit(() => api.get("/api/auth/demo-accounts"));
  expect(response.status(), "demo accounts are published (DEMO_MODE=true on the target)").toBe(200);
  return (await response.json()) as DemoAccount[];
}

/** The home business's account for `role` (the first business listed). */
export async function homeAccount(api: APIRequestContext, role: Role): Promise<DemoAccount> {
  const accounts = await demoAccounts(api);
  const business = accounts[HOME_TENANT_INDEX]?.business_name;
  const account = accounts.find((candidate) => candidate.role === role && candidate.business_name === business);
  if (!account) throw new Error(`no demo ${role} for ${business}`);
  return account;
}

/** Retry a request the API rate-limited (429 with Retry-After, WP-11 web hardening). */
export async function withRateLimit(send: () => Promise<APIResponse>, attempts = 4): Promise<APIResponse> {
  for (let attempt = 1; ; attempt += 1) {
    const response = await send();
    if (response.status() !== 429 || attempt === attempts) return response;
    const seconds = Number(response.headers()["retry-after"] ?? "5");
    await new Promise((resolve) => setTimeout(resolve, (Number.isFinite(seconds) ? seconds : 5) * 1000 + 250));
  }
}
