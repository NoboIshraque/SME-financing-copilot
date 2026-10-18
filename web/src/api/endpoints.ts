// One typed function per backend route. Screens call these, never fetch() directly.
import { apiGet, apiPost } from "./client";
import type { Alert, Approval, Recommendation } from "./contracts";
import type { CashForecast, DemoAccount, Health, LoginRequest, LoginResponse, Session } from "./types";

export const api = {
  health: () => apiGet<Health>("/api/health"),
  auth: {
    me: () => apiGet<Session>("/api/auth/me"),
    login: (body: LoginRequest) => apiPost<LoginResponse>("/api/auth/login", body),
    verifyTotp: (code: string) => apiPost<Session>("/api/auth/login/totp", { code }),
    logout: () => apiPost<void>("/api/auth/logout", {}),
    demoAccounts: () => apiGet<DemoAccount[]>("/api/auth/demo-accounts"),
  },
  cash: {
    /** WP-04: alerts, highest tier first. */
    alerts: () => apiGet<Alert[]>("/api/cash/alerts"),
    forecast: () => apiGet<CashForecast>("/api/cash/forecast"),
  },
  copilot: {
    /** WP-10: today's recommendation, with at most 3 pre-checked action cards (P9). */
    today: () => apiGet<Recommendation>("/api/copilot/today"),
  },
  actions: {
    /** WP-11: approve an action card. EXECUTE needs the step-up code; the key makes retries safe. */
    approve: (cardId: string, options: { idempotencyKey: string; stepUpCode?: string }) =>
      apiPost<Approval>(`/api/actions/${encodeURIComponent(cardId)}/approve`, {}, options),
  },
};
