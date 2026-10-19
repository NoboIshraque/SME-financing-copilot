// Mock of the WP-11 auth router: password, TOTP second step, lockout, demo accounts.
import type { DemoAccount, LoginResponse } from "../../api/types";
import { DEMO_TOTP_CODE, MAX_FAILED_LOGINS, sessionFor } from "../db";
import { apiError, field, ok, type MockRoute } from "../http";

export const authRoutes: MockRoute[] = [
  {
    method: "GET",
    pattern: "/api/health",
    handler: () => ok({ status: "ok", contracts_version: "1.1.0", data_mode_banner: "synthetic" }),
  },
  {
    method: "GET",
    pattern: "/api/auth/me",
    handler: (_req, db) =>
      db.session ? ok(db.session) : apiError(401, "not_authenticated", "error.not_authenticated"),
  },
  {
    method: "POST",
    pattern: "/api/auth/login",
    handler: (req, db) => {
      const email = field(req.body, "email").trim().toLowerCase();
      const account = db.users.find((u) => u.email === email);
      if (account && account.failedLogins >= MAX_FAILED_LOGINS) {
        return apiError(423, "account_locked", "error.account_locked", { retry_after_minutes: "15" });
      }
      if (!account || account.password !== field(req.body, "password")) {
        if (account) account.failedLogins += 1;
        return apiError(401, "invalid_credentials", "error.invalid_credentials");
      }
      account.failedLogins = 0;
      if (account.totp) {
        db.pendingTotp = account.email;
        const body: LoginResponse = { status: "totp_required" };
        return ok(body);
      }
      db.session = sessionFor(account);
      const body: LoginResponse = { status: "ok", session: db.session };
      return ok(body);
    },
  },
  {
    method: "POST",
    pattern: "/api/auth/login/totp",
    handler: (req, db) => {
      const account = db.users.find((u) => u.email === db.pendingTotp);
      if (!account) return apiError(401, "not_authenticated", "error.not_authenticated");
      if (field(req.body, "code") !== DEMO_TOTP_CODE) return apiError(401, "invalid_totp", "error.invalid_totp");
      db.pendingTotp = null;
      db.session = sessionFor(account);
      return ok(db.session);
    },
  },
  {
    method: "POST",
    pattern: "/api/auth/logout",
    handler: (_req, db) => {
      db.session = null;
      db.pendingTotp = null;
      return { status: 204 };
    },
  },
  {
    method: "GET",
    pattern: "/api/auth/demo-accounts",
    handler: (_req, db) => {
      const accounts: DemoAccount[] = db.users.map((u) => ({
        email: u.email,
        password: u.password,
        role: u.role,
        business_name: u.business_name,
        totp_hint: u.totp ? DEMO_TOTP_CODE : null,
      }));
      return ok(accounts);
    },
  },
];
