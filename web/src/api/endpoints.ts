// One typed function per backend route. Screens call these, never fetch() directly.
import { apiGet, apiPost } from "./client";
import type {
  ActionCard,
  Alert,
  CashGap,
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
    gaps: () => apiGet<CashGap[]>("/api/cash/gaps"),
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
  market: {
    prices: () => apiGet<WatchItem[]>("/api/market/prices"),
    alerts: () => apiGet<MarketAlert[]>("/api/market/alerts"),
    rankVendors: (commodity: string, quantity: string) =>
      apiPost<VendorRank[]>("/api/market/vendors/rank", { commodity, quantity }),
    negotiate: (body: NegotiationRequest) => apiPost<NegotiationPlan>("/api/market/negotiate", body),
  },
  copilot: {
    /** WP-10: today's recommendation, with at most 3 pre-checked action cards (P9). */
    today: () => apiGet<Recommendation>("/api/copilot/today"),
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
    preview: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return apiPost<IngestPreview>("/api/ingest/preview", form);
    },
    commit: (body: IngestCommitRequest) => apiPost<IngestCommitResult>("/api/ingest/commit", body),
  },
};
