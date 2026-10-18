// One typed function per backend route. Screens call these, never fetch() directly.
import { apiGet, apiPost } from "./client";
import type { DemoAccount, Health, LoginRequest, LoginResponse, Session } from "./types";

export const api = {
  health: () => apiGet<Health>("/api/health"),
  auth: {
    me: () => apiGet<Session>("/api/auth/me"),
    login: (body: LoginRequest) => apiPost<LoginResponse>("/api/auth/login", body),
    verifyTotp: (code: string) => apiPost<Session>("/api/auth/login/totp", { code }),
    logout: () => apiPost<void>("/api/auth/logout", {}),
    demoAccounts: () => apiGet<DemoAccount[]>("/api/auth/demo-accounts"),
  },
};
