// Response envelopes the web expects from each router, built from the shared contracts.
// They are not contracts themselves: each owner WP is named on its type. The mock API in
// src/mocks serves exactly these shapes, so a router that matches them drops in unchanged.
import type {
  Abstention,
  ActionCard,
  AnchorReceipt,
  Approval,
  DataMode,
  Figure,
  FinancingNeed,
  FinancingOption,
  ForecastBand,
  Invoice,
  LenderProfile,
  MeshObligation,
  Money,
  Period,
  PricePoint,
  Principal,
  Role,
  Scenario,
  Variance,
  VendorQuote,
} from "./contracts";

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

/** POST /api/cash/whatif body (WP-04): shocks applied to the same seeded simulation.
 *  Percentages are decimal strings; the answer is a CashForecast for the shocked inputs. */
export interface WhatIfRequest {
  sales_change_pct: string;
  cost_change_pct: string;
  collection_delay_days: number;
  one_off_cost: Money;
}

// ---- Receivables (WP-05) -------------------------------------------------------------------

export type AgingBucket = "0_30" | "31_60" | "61_90" | "90_plus";

/** One open invoice with its risk (0-100, top factors as i18n keys) and dispute state. */
export interface ReceivableRow {
  invoice: Invoice;
  counterparty_label: string;
  days_overdue: number;
  bucket: AgingBucket;
  risk_score: string;
  risk_factor_keys: string[];
  disputed: boolean;
  dispute_reason?: string | null;
}

export interface CustomerCredit {
  counterparty_token: string;
  counterparty_label: string;
  open: Money;
  avg_days_late: string;
  credit_limit: Figure | null;
  stop_credit: boolean;
}

/** GET /api/receivables. Figures: receivables.open, receivables.overdue, receivables.dso. */
export interface ReceivablesOverview {
  as_of: string;
  figures: Figure[];
  aging: Array<{ bucket: AgingBucket; amount: Money; count: number }>;
  invoices: ReceivableRow[];
  customers: CustomerCredit[];
}

/** GET /api/receivables/plan: the reminder ladder as DRAFT action cards, soonest first. */
export interface ReceivablesPlan {
  reminders: ActionCard[];
}

// ---- Financing (WP-06) ---------------------------------------------------------------------

/** POST /api/financing/match {FinancingNeed}: ranked options, lender track records, and the
 *  application pack draft for the best eligible option (EXECUTE card). */
export interface FinancingMatch {
  need: FinancingNeed;
  options: FinancingOption[];
  lenders: LenderProfile[];
  application: ActionCard | null;
}

// ---- Analysis (WP-07) ----------------------------------------------------------------------

export interface StatementLine {
  label_key: string;
  figure: Figure;
  /** Subtotals are drawn bold with a rule above. */
  total?: boolean;
}

/** GET /api/analysis/statements: cash-basis P&L, balance-sheet-lite and cash flow. */
export interface Statements {
  period: Period;
  pnl: StatementLine[];
  balance_sheet: StatementLine[];
  cash_flow: StatementLine[];
}

/** GET /api/analysis/variance: expected vs reality for the last frozen forecast (N1). */
export interface VarianceReport {
  period: Period;
  variances: Variance[];
  accuracy: Figure;
}

/** POST /api/analysis/scenarios {decisions}: each decision simulated; the best risk-adjusted
 *  one named (N12). */
export interface ScenarioComparison {
  scenarios: Scenario[];
  recommended_id: string;
}

// ---- Mesh (WP-08) --------------------------------------------------------------------------

/** GET /api/mesh/obligations: the opted-in debt graph this tenant may see. */
export interface MeshGraph {
  obligations: MeshObligation[];
  /** Tenant id -> display label, e.g. "sme_fabric" -> "Islampur Fabric House". */
  labels: Record<string, string>;
}

/** GET /api/mesh/rounds/:id/verify: digest recomputed and compared with the anchor. */
export interface RoundVerification {
  round_id: string;
  valid: boolean;
  recomputed_digest: string;
  anchor: AnchorReceipt | null;
}

// ---- Market (WP-09) ------------------------------------------------------------------------

export interface WatchItem {
  commodity: string;
  unit: string;
  latest: PricePoint;
  median_4w: Money;
  change_pct: string;
  history: PricePoint[];
}

export interface MarketAlert {
  id: string;
  commodity: string;
  direction: "drop" | "rise";
  change: Figure;
  observed_on: string;
  source: PricePoint["source"];
}

export interface VendorRank {
  rank: number;
  vendor_label: string;
  quote: VendorQuote;
  landed_cost: Figure;
  breakdown: Figure[];
}

export interface NegotiationRequest {
  commodity: string;
  quantity: string;
  offer_price: Money;
  payment_days: number;
}

export interface NegotiationStep {
  text_key: string;
  figures: Figure[];
}

/** POST /api/market/negotiate: walk-away, target and a step-by-step script (N19). */
export interface NegotiationPlan {
  walk_away: Figure;
  target: Figure;
  steps: NegotiationStep[];
}

// ---- Messages, approvals, reports, trust, settings (WP-11/12/13/16) -------------------------

/** WP-11 approvals for EXECUTE cards: POST /api/approvals {card} (X-Idempotency-Key) -> pending;
 *  POST /api/approvals/{id}/approve (X-Step-Up-Code, owner) -> approved;
 *  POST /api/approvals/{id}/execute (X-Idempotency-Key) -> executed, with `result`.
 *  GET /api/approvals?status=pending lists the same view. */
export interface ApprovalView {
  approval: Approval;
  action_type: ActionCard["action_type"];
  card: ActionCard;
  result?: Record<string, string> | null;
  replayed?: boolean;
}

/** GET /api/audit/verify (WP-11): the tenant's hash chain, recomputed. */
export interface ChainReport {
  tenant_id: string;
  valid: boolean;
  length: number;
  head_hash: string;
  first_bad_seq?: number | null;
  reason?: string | null;
  anchors_checked?: number;
}

/** GET /api/audit/anchors (WP-11): daily anchors of the chain head, newest first. */
export interface AuditAnchor {
  day: string;
  digest: string;
  chain: AnchorReceipt["chain"];
  tx_hash: string | null;
  block_number: number | null;
  explorer_url: string | null;
  anchored_at: string;
  heads: number;
}

export interface AbstentionLogEntry {
  id: string;
  at: string;
  question: string;
  abstention: Abstention;
}

/** GET /api/trust/drill: the nightly audit drill (P8). */
export interface AuditDrill {
  run_at: string;
  planted: number;
  caught: number;
  catch_rate: Figure;
}

export interface ShareRequest {
  lender_label: string;
  scopes: string[];
  days: number;
}

/** GET/POST /api/settings (WP-12 opt-ins). */
export interface UserSettings {
  auto_send_reminders: boolean;
  email_alerts: boolean;
}

/** POST /api/ingest/commit (WP-02). */
export interface IngestCommitRequest {
  preview_id: string;
  file_digest: string;
  confirmed_rows: string[];
}

export interface IngestCommitResult {
  committed: number;
  skipped: number;
}
