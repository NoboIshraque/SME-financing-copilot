// One typed function per backend route. Screens call these, never fetch() directly.
import type { Language } from "../i18n";
import { ApiRequestError, apiGet, apiPost } from "./client";

type MarketSample = typeof import("../mocks/fixtures/market");

/** A route the server does not have (FastAPI's bare 404/405, no ApiError body) -> sample data. */
function orSample<T>(call: Promise<T>, pick: (sample: MarketSample) => T): Promise<T> {
  return call.catch((error: unknown) => {
    const missing = error instanceof ApiRequestError && error.body === null && (error.status === 404 || error.status === 405);
    if (!missing) throw error;
    return import("../mocks/fixtures/market").then(pick);
  });
}
import type {
  ActionCard,
  Alert,
  Explanation,
  FinancingNeed,
  IngestPreview,
  LenderProfile,
  MessageDraft,
  NettingRound,
  PassportVersion,
  Ratio,
  Recommendation,
  ShareGrant,
  StabilityReport,
  AuditEvent,
  VerifyResult,
} from "./contracts";
import type {
  AbstentionLogEntry,
  ApprovalView,
  AuditAnchor,
  AuditDrill,
  ChainReport,
  CashForecast,
  CashGaps,
  DemoAccount,
  FinancingMatch,
  Health,
  IngestCommitRequest,
  IngestCommitResult,
  LoginRequest,
  LoginResponse,
  MarketAlert,
  MeshGraph,
  NegotiationPlan,
  NegotiationRequest,
  ReceivableRow,
  ReceivablesOverview,
  ReceivablesPlan,
  RoundVerification,
  ScenarioComparison,
  Session,
  ShareRequest,
  Statements,
  UserSettings,
  VarianceReport,
  VendorRank,
  WatchItem,
  WhatIfRequest,
} from "./types";

type Step = { idempotencyKey: string; stepUpCode?: string };
const id = encodeURIComponent;

export const api = {
  health: () => apiGet<Health>("/api/health"),
  auth: {
    me: () => apiGet<Session>("/api/auth/me"),
    login: (body: LoginRequest) => apiPost<LoginResponse>("/api/auth/login", body),
    verifyTotp: (code: string) => apiPost<Session>("/api/auth/login/totp", { code }),
    logout: () => apiPost<void>("/api/auth/logout", {}),
    demoAccounts: () => apiGet<DemoAccount[]>("/api/auth/demo-accounts"),
  },
  /** WP-01: formula, inputs and source rows behind any figure (N13). */
  explain: (figureId: string) => apiGet<Explanation>(`/api/explain/${id(figureId)}`),
  cash: {
    /** WP-04: alerts, highest tier first. */
    alerts: () => apiGet<Alert[]>("/api/cash/alerts"),
    forecast: () => apiGet<CashForecast>("/api/cash/forecast"),
    /** The gaps ahead; the indicators and sweep in the same answer are not shown yet. */
    gaps: () => apiGet<CashGaps>("/api/cash/gaps").then((answer) => answer.gaps),
    whatIf: (body: WhatIfRequest) => apiPost<CashForecast>("/api/cash/whatif", body),
  },
  receivables: {
    overview: () => apiGet<ReceivablesOverview>("/api/receivables"),
    plan: () => apiGet<ReceivablesPlan>("/api/receivables/plan"),
    dispute: (invoiceId: string, reason: string) =>
      apiPost<ReceivableRow>(`/api/receivables/${id(invoiceId)}/dispute`, { reason }),
    resolve: (invoiceId: string) => apiPost<ReceivableRow>(`/api/receivables/${id(invoiceId)}/resolve`, {}),
  },
  financing: {
    match: (need: FinancingNeed) => apiPost<FinancingMatch>("/api/financing/match", need),
    lender: (lenderId: string) => apiGet<LenderProfile>(`/api/financing/lenders/${id(lenderId)}`),
  },
  analysis: {
    statements: () => apiGet<Statements>("/api/analysis/statements"),
    ratios: () => apiGet<Ratio[]>("/api/analysis/ratios"),
    variance: () => apiGet<VarianceReport>("/api/analysis/variance"),
    scenarios: (decisions: string[]) => apiPost<ScenarioComparison>("/api/analysis/scenarios", { decisions }),
    stability: (recommendationId: string) =>
      apiPost<StabilityReport>("/api/analysis/stability", { recommendation_id: recommendationId }),
  },
  mesh: {
    obligations: () => apiGet<MeshGraph>("/api/mesh/obligations"),
    rounds: () => apiGet<NettingRound[]>("/api/mesh/rounds"),
    propose: () => apiPost<NettingRound>("/api/mesh/rounds/propose", {}),
    approve: (roundId: string, step: Step) => apiPost<NettingRound>(`/api/mesh/rounds/${id(roundId)}/approve`, {}, step),
    verify: (roundId: string) => apiGet<RoundVerification>(`/api/mesh/rounds/${id(roundId)}/verify`),
  },
  /** WP-09 was cut (19 Oct): no market router is deployed. When the server has no such route,
   *  the Market screen falls back to the bundled sample data (labelled a preview on screen). */
  market: {
    prices: () => orSample(apiGet<WatchItem[]>("/api/market/prices"), (m) => m.watchlist()),
    alerts: () => orSample(apiGet<MarketAlert[]>("/api/market/alerts"), (m) => m.marketAlerts()),
    rankVendors: (commodity: string, quantity: string) =>
      orSample(apiPost<VendorRank[]>("/api/market/vendors/rank", { commodity, quantity }),
        (m) => m.vendorRanking(commodity)),
    negotiate: (body: NegotiationRequest) =>
      orSample(apiPost<NegotiationPlan>("/api/market/negotiate", body), (m) => m.negotiationPlan(body)),
  },

  copilot: {
    /** WP-10: today's recommendation, with at most 3 pre-checked action cards (P9). */
    today: (language: Language = "en") =>
      apiGet<Recommendation>(`/api/copilot/today?language=${encodeURIComponent(language)}`),
    ask: (question: string) => apiPost<Recommendation>("/api/copilot/ask", { question }),
    abstentions: () => apiGet<AbstentionLogEntry[]>("/api/copilot/abstentions"),
  },
  approvals: {
    /** WP-11: ask for an EXECUTE card to be approved; the key makes a retried request a replay. */
    request: (card: ActionCard, idempotencyKey: string) => apiPost<ApprovalView>("/api/approvals", { card }, { idempotencyKey }),
    /** The owner approves with a fresh TOTP code. */
    approve: (approvalId: string, stepUpCode: string) =>
      apiPost<ApprovalView>(`/api/approvals/${id(approvalId)}/approve`, {}, { stepUpCode }),
    execute: (approvalId: string, idempotencyKey: string) =>
      apiPost<ApprovalView>(`/api/approvals/${id(approvalId)}/execute`, {}, { idempotencyKey }),
    pending: () => apiGet<ApprovalView[]>("/api/approvals?status=pending"),
  },
  messages: {
    drafts: () => apiGet<MessageDraft[]>("/api/messages/drafts"),
    approve: (draftId: string, step: Step) => apiPost<MessageDraft>(`/api/messages/${id(draftId)}/approve`, {}, step),
    send: (draftId: string, step: Step) => apiPost<MessageDraft>(`/api/messages/${id(draftId)}/send`, {}, step),
  },
  reports: {
    passports: () => apiGet<PassportVersion[]>("/api/reports/passport"),
    issuePassport: () => apiPost<PassportVersion>("/api/reports/passport", {}),
    shares: () => apiGet<ShareGrant[]>("/api/reports/shares"),
    share: (passportId: string, body: ShareRequest, step: Step) =>
      apiPost<ShareGrant>(`/api/reports/passport/${id(passportId)}/share`, body, step),
    revoke: (grantId: string) => apiPost<ShareGrant>(`/api/reports/shares/${id(grantId)}/revoke`, {}),
    verify: (passportId: string) => apiGet<VerifyResult>(`/api/verify/${id(passportId)}`),
  },
  trust: {
    auditVerify: () => apiGet<ChainReport>("/api/audit/verify"),
    auditAnchors: () => apiGet<AuditAnchor[]>("/api/audit/anchors"),
    auditEvents: () => apiGet<AuditEvent[]>("/api/audit/events?limit=20"),
    drill: () => apiGet<AuditDrill>("/api/trust/drill"),
  },
  settings: {
    get: () => apiGet<UserSettings>("/api/settings"),
    save: (body: UserSettings) => apiPost<UserSettings>("/api/settings", body),
  },
  ingest: {
    /** WP-02: multipart file + tenant_id (until the principal carries the tenant). */
    preview: (file: File, tenantId: string) => {
      const form = new FormData();
      form.append("file", file);
      form.append("tenant_id", tenantId);
      return apiPost<IngestPreview>("/api/ingest/preview", form);
    },
    commit: (body: IngestCommitRequest) => apiPost<IngestCommitResult>("/api/ingest/commit", body),
  },
};
