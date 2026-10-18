// Response envelopes the web expects from each router, built from the shared contracts.
// They are not contracts themselves: each owner WP is named on its type. The mock API in
// src/mocks serves exactly these shapes, so a router that matches them drops in unchanged.
import type { DataMode, Figure, ForecastBand, Principal, Role } from "./contracts";

/** GET /api/health (WP-00). */
export interface Health {
  status: string;
  contracts_version: string;
  data_mode_banner: "synthetic" | null;
}

/** GET /api/auth/me, and the result of a completed sign-in (WP-11). 401 when signed out. */
export interface Session {
  principal: Principal;
  display_name: string;
  business_name: string;
  totp_enrolled: boolean;
  data_mode: DataMode;
}

/** POST /api/auth/login body (WP-11). */
export interface LoginRequest {
  email: string;
  password: string;
}

/** POST /api/auth/login: signed in, or the account must send its TOTP code next
 *  (POST /api/auth/login/totp {code} -> Session). Wrong password: 401 error.invalid_credentials;
 *  locked: 423 error.account_locked with detail.retry_after_minutes. */
export type LoginResponse = { status: "ok"; session: Session } | { status: "totp_required" };

/** GET /api/auth/demo-accounts: public demo logins, served only in demo mode (WP-11). */
export interface DemoAccount {
  email: string;
  password: string;
  role: Role;
  business_name: string;
  /** Current demo TOTP code, shown so judges can sign in without an authenticator app. */
  totp_hint?: string | null;
}

/** GET /api/cash/forecast (WP-04): the 13-week band and its headline figures, each explainable.
 *  Figure label_keys the screens look for: cash.closing_balance (cash now), cash.buffer_target,
 *  cash.runway_days (days until the likely balance falls below the buffer; equals the horizon
 *  when it never does), cash.lowest_likely_balance. */
export interface CashForecast {
  band: ForecastBand;
  figures: Figure[];
}
