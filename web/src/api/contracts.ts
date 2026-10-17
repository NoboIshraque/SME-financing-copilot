/* Generated from docs/api/contracts.json (contracts v1.1.0). Do not edit. */
/* Money amounts are decimal strings: never convert them to floats. */

export type Detail = string | null;
export type MessageKey = string;
/**
 * Exactly what is missing, e.g. 'at least 90 days of sales'
 */
export type Missing = string[];
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AbstentionReason".
 */
export type AbstentionReason =
  | "insufficient_data"
  | "low_agreement"
  | "unverifiable"
  | "out_of_scope"
  | "policy"
  | "budget_exhausted";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ActionType".
 */
export type ActionType =
  | "view"
  | "send_reminder"
  | "send_message"
  | "draft_loan_application"
  | "retime_payable"
  | "request_advance"
  | "offer_early_pay_discount"
  | "propose_netting_round"
  | "approve_netting_round"
  | "share_passport"
  | "set_credit_limit"
  | "record_dispute"
  | "change_bank_details"
  | "add_payee"
  | "disable_audit"
  | "export_raw_pii"
  | "move_money";
/**
 * Where data came from. Shown to users; synthetic data is always labelled.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "DataMode".
 */
export type DataMode = "synthetic" | "real_anonymised" | "public" | "live";
export type Id = string;
/**
 * i18n key for the label
 */
export type LabelKey = string;
export type FormulaId = string;
export type FormulaVersion = number;
export type InputFactIds = string[];
export type SourceRowIds = string[];
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Unit".
 */
export type Unit =
  "BDT" | "USD" | "CNY" | "ratio" | "percent" | "days" | "count" | "probability" | "score";
export type Value = string;
export type ExpiresAt = string | null;
export type Figures = Figure[];
export type Id1 = string;
/**
 * Permission tier of an action (FEATURES P2).
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Tier".
 */
export type Tier = "READ" | "SUGGEST" | "DRAFT" | "EXECUTE" | "DENY";
export type TitleKey = string;
export type AgreementRate = string;
export type Question = string;
/**
 * low | medium | high
 */
export type Stakes = string;
export type Threshold = string;
/**
 * @minItems 1
 */
export type Votes = [Vote, ...Vote[]];
export type Choice = string;
/**
 * Provider/model id, e.g. 'groq:gpt-oss-120b'
 */
export type Model = string;
export type Rationale = string | null;
export type WinningChoice = string;
export type CreatedAt = string;
export type DedupeKey = string;
/**
 * Ranked fixes, cheapest first
 */
export type Fixes = ActionCard[];
/**
 * @maxItems 3
 */
export type Drivers = [] | [GapDriver] | [GapDriver, GapDriver] | [GapDriver, GapDriver, GapDriver];
export type Amount = string;
export type Currency = "BDT" | "USD" | "CNY";
export type CounterpartyToken = string | null;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "DriverKind".
 */
export type DriverKind =
  "late_customer" | "bill_due" | "obligation" | "seasonal_dip" | "stock_build" | "cost_shock";
export type LabelKey1 = string;
/**
 * Invoice/bill/obligation id
 */
export type ReferenceId = string | null;
export type Figures1 = Figure[];
export type FirstBreachDay = string;
export type LeadTimeDays = number;
export type Probability = string;
export type WorstDay = string;
export type Id2 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "LeadingIndicator".
 */
export type LeadingIndicator =
  | "dso_rising"
  | "top_customer_slowing"
  | "stock_building"
  | "sales_below_seasonal_norm"
  | "payroll_or_emi_at_risk";
export type Indicators = LeadingIndicator[];
export type TenantId = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AlertTier".
 */
export type AlertTier = "watch" | "warning" | "critical";
export type TitleKey1 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AnchorChain".
 */
export type AnchorChain = "offline" | "sepolia";
export type AnchoredAt = string;
export type BlockNumber = number | null;
export type Digest = string;
export type ExplorerUrl = string | null;
export type TxHash = string | null;
export type Code = string;
export type MessageKey1 = string;
export type ActionCardId = string;
export type CreatedAt1 = string;
export type DecidedBy = string | null;
export type ExpiresAt1 = string;
export type Id3 = string;
export type IdempotencyKey = string;
export type RequestedBy = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ApprovalStatus".
 */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "executed";
export type StepUpVerified = boolean;
export type TenantId1 = string;
export type AttesterTenant = string;
export type CreatedAt2 = string;
/**
 * SHA-256 of the attested record
 */
export type Digest1 = string;
export type Id4 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AttestationKind".
 */
export type AttestationKind = "confirm" | "dispute";
export type ObligationId = string;
export type Action = string;
export type Actor = string;
export type At = string;
export type DetailsDigest = string;
export type Hash = string;
export type PrevHash = string;
export type Seq = number;
export type Target = string | null;
export type TenantId2 = string;
export type CounterpartyToken1 = string;
export type DueDate = string;
export type Id5 = string;
export type IssueDate = string;
export type PaidDate = string | null;
export type SourceRef = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "DocumentStatus".
 */
export type DocumentStatus = "open" | "partially_paid" | "paid" | "disputed" | "written_off";
export type TenantId3 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Channel".
 */
export type Channel = "bkash" | "nagad" | "rocket" | "bank" | "cash" | "card" | "other";
export type ClaimId = string;
export type Reason = string | null;
export type RecomputedValue = string | null;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "CheckStatus".
 */
export type CheckStatus = "verified" | "rejected" | "unverifiable";
export type FormulaId1 = string | null;
export type Id6 = string;
export type InputFactIds1 = string[];
export type Text = string;
export type Value1 = string | null;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Currency".
 */
export type Currency1 = "BDT" | "USD" | "CNY";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Direction".
 */
export type Direction = "inflow" | "outflow";
export type Confidence = string;
export type Flagged = boolean;
export type CounterpartyToken2 = string;
export type DueDate1 = string;
export type Id7 = string;
export type IssueDate1 = string;
export type PaidDate1 = string | null;
export type SourceRef1 = string;
export type TenantId4 = string;
export type RowRef = string;
export type TxCategory =
  | "sales"
  | "collection"
  | "purchase"
  | "supplier_payment"
  | "rent"
  | "salary"
  | "loan_repayment"
  | "loan_disbursement"
  | "utility"
  | "tax"
  | "owner_draw"
  | "owner_topup"
  | "transfer"
  | "fee"
  | "other";
export type CounterpartyToken3 = string | null;
export type Id8 = string;
export type InvoiceId = string | null;
export type OccurredAt = string;
export type Reference = string | null;
/**
 * Source file + row, e.g. 'bkash.csv#L42'
 */
export type SourceRef2 = string;
export type TenantId5 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "DraftStatus".
 */
export type DraftStatus = "draft" | "approved" | "sent" | "rejected";
export type ProductId = string;
export type MessageKey2 = string;
export type ObservedValue = string | null;
export type RuleId = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "EligibilityStatus".
 */
export type EligibilityStatus = "pass" | "fail" | "not_on_record";
export type Reasons = EligibilityReason[];
export type DescriptionKey = string;
export type Id9 = string;
/**
 * Fact metric name, e.g. 'business_age_months'
 */
export type Metric = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "RuleOp".
 */
export type RuleOp = ">=" | "<=" | "==" | "exists";
export type Threshold1 = string | null;
export type Digest2 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "EvidenceKind".
 */
export type EvidenceKind =
  | "mobile_money_statement"
  | "bank_statement"
  | "trade_licence"
  | "etin"
  | "bin_vat"
  | "utility_bill"
  | "lender_report";
export type End = string;
export type Granularity = "day" | "week" | "month" | "quarter" | "year";
export type Start = string;
/**
 * True when checked against its source, not self-declared
 */
export type Verified = boolean;
export type FactId = string;
export type Metric1 = string;
export type Value2 = string;
export type FigureId = string;
/**
 * Human-readable formula, e.g. 'receivables / sales * days'
 */
export type Expression = string;
/**
 * e.g. 'cash.dso'
 */
export type FormulaId2 = string;
export type Version = number;
export type Inputs = ExplainedInput[];
/**
 * True if source rows were masked for the caller's role
 */
export type Masked = boolean;
export type SourceRows = string[];
export type Value3 = string;
export type ComputedAt = string | null;
export type EntityToken = string | null;
export type Id10 = string;
export type Metric2 = string;
export type SourceRefs = string[];
export type TenantId6 = string;
export type Value4 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FeeKind".
 */
export type FeeKind = "fixed" | "percent_of_principal" | "compulsory_deposit_percent";
export type Name = string;
export type FeeTiming = "upfront" | "periodic" | "at_maturity";
export type Value5 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FeeTiming".
 */
export type FeeTiming1 = "upfront" | "periodic" | "at_maturity";
export type NeededBy = string;
export type PurposeKey = string;
export type TenantId7 = string;
export type TenorDays = number;
export type ApprovalLikelihood = string;
/**
 * True annual cost in percent, fees included
 */
export type EffectiveApr = string;
export type Figures2 = Figure[];
export type PBufferBreach = string;
export type CheckedOn = string | null;
export type CollateralRequired = boolean;
export type Fees = Fee[];
export type Id11 = string;
/**
 * True for illustrative products (e.g. the P14 China pack)
 */
export type IsModelled = boolean;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ProductKind".
 */
export type ProductKind =
  | "term_loan"
  | "working_capital"
  | "nano_loan"
  | "refinance_scheme"
  | "factoring"
  | "invoice_discounting"
  | "leasing"
  | "mfi_loan"
  | "buyer_early_pay"
  | "supplier_term_extension"
  | "mesh_netting"
  | "owner_topup"
  | "grant"
  | "digital_credit_modelled";
export type MaxTenorDays = number | null;
export type MinTenorDays = number | null;
export type Name1 = string;
/**
 * Percent per year as published, e.g. 9
 */
export type NominalRatePa = string;
export type Notes = string | null;
export type Provider = string;
/**
 * How we know the rate. Shown next to every rate in the UI.
 */
export type RateBasis =
  "published" | "rate_sheet_upper" | "regulatory_cap" | "last_published" | "modelled" | "own_terms";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "RateType".
 */
export type RateType = "reducing_balance" | "flat" | "daily_debit" | "discount" | "none";
export type Rules = EligibilityRule[];
export type SourceUrl = string | null;
export type Rank = number;
export type ReasonKeys = string[];
export type Score = string;
export type SpeedDays = number;
export type AsOf = string;
export type GeneratedAt = string;
export type HorizonDays = number;
export type Paths = number;
export type Day = string;
export type PBelowBuffer = string;
export type Points = ForecastPoint[];
export type Seed = number;
export type TenantId8 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Frequency".
 */
export type Frequency = "weekly" | "monthly" | "quarterly" | "yearly";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Granularity".
 */
export type Granularity1 = "day" | "week" | "month" | "quarter" | "year";
export type Bills = Bill[];
export type Drafts = DraftRow[];
export type DuplicatesSkipped = number;
/**
 * Keyed digest of the file
 */
export type FileDigest = string;
export type Invoices = Invoice[];
export type PreviewId = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "SourceFormat".
 */
export type SourceFormat =
  | "bkash_statement"
  | "nagad_statement"
  | "bank_csv"
  | "ledger_csv"
  | "ledger_xlsx"
  | "ledger_photo"
  | "unknown";
export type TenantId9 = string;
export type Transactions = Transaction[];
/**
 * Masked by WP-03 before storage
 */
export type RawExcerpt = string;
export type ReasonKey = string;
export type RowRef1 = string;
export type Unparsed = UnparsedRow[];
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Language".
 */
export type Language = "en" | "bn" | "zh";
export type Disputes = number;
export type EventsCount = number;
export type HiddenFeeIncidents = number;
export type LenderId = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "LicenceStatus".
 */
export type LicenceStatus = "licensed" | "not_found" | "revoked" | "unknown";
export type MedianDisbursalDays = string | null;
export type Name2 = string;
/**
 * Average realised minus quoted APR, percentage points
 */
export type QuotedVsRealisedAprGap = string | null;
/**
 * e.g. 'Bangladesh Bank', 'MRA'
 */
export type Regulator = string | null;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "LeverKind".
 */
export type LeverKind =
  | "retime_payable"
  | "stagger_purchase"
  | "request_advance"
  | "early_pay_discount"
  | "netting"
  | "standby_facility"
  | "surplus_sweep";
export type Attested = boolean;
export type CreditorTenant = string;
export type DebtorTenant = string;
export type DueDate2 = string;
export type Id12 = string;
export type InvoiceRef = string | null;
export type ObligationStatus = "open" | "in_round" | "settled" | "disputed";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "MessageChannel".
 */
export type MessageChannel = "in_app" | "email" | "copy";
export type Body = string;
export type CreatedAt3 = string;
export type Id13 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "MessagePurpose".
 */
export type MessagePurpose =
  | "pre_due_reminder"
  | "overdue_reminder"
  | "payment_plan_offer"
  | "supplier_term_extension"
  | "lender_update"
  | "netting_invitation"
  | "sale_memo";
export type RecipientToken = string;
export type DraftStatus1 = "draft" | "approved" | "sent" | "rejected";
export type TemplateId = string;
export type TenantId10 = string;
export type CreatedAt4 = string;
export type ExpiresAt2 = string;
export type Id14 = string;
/**
 * @minItems 2
 */
export type ObligationIds = [string, string, ...string[]];
/**
 * @minItems 2
 */
export type Participants = [string, string, ...string[]];
export type PayeeTenant = string;
export type PayerTenant = string;
export type Settlements = Settlement[];
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "RoundStatus".
 */
export type RoundStatus = "proposed" | "approved" | "rejected" | "expired" | "settled";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ObligationKind".
 */
export type ObligationKind =
  "rent" | "salary" | "emi" | "utility" | "tax" | "subscription" | "other";
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ObligationStatus".
 */
export type ObligationStatus1 = "open" | "in_round" | "settled" | "disputed";
/**
 * Neutral label safe to show anywhere, e.g. 'Customer 3'
 */
export type DisplayLabel = string;
export type Id15 = string;
/**
 * True if this party is itself a Hishab tenant (mesh peer)
 */
export type IsTenant = boolean;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "PartyRole".
 */
export type PartyRole =
  | "self"
  | "customer"
  | "supplier"
  | "lender"
  | "employee"
  | "landlord"
  | "government"
  | "utility"
  | "other";
export type TenantId11 = string;
export type Token = string;
export type AbstentionRate = string | null;
export type AttestationsConfirmed = number;
export type AttestationsDisputed = number;
export type AuditDrillCatchRate = string | null;
export type Digest3 = string;
export type Evidence = EvidenceItem[];
export type Id16 = string;
export type IssuedAt = string;
export type TenantId12 = string;
export type Version1 = number;
/**
 * e.g. 'rice_coarse'
 */
export type Commodity = string;
/**
 * e.g. 'Dhaka' or 'World'
 */
export type Market = string;
export type ObservedOn = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "PriceSource".
 */
export type PriceSource = "tcb" | "agripricebd" | "worldbank_pinksheet" | "vendor" | "manual";
export type SourceUrl1 = string | null;
/**
 * e.g. 'kg', 'litre', 'metric_ton'
 */
export type Unit1 = string;
/**
 * Required for lender_viewer (consented, expiring access)
 */
export type ExpiresAt3 = string | null;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Role".
 */
export type Role = "owner" | "accountant" | "staff" | "lender_viewer" | "compliance";
export type Scopes = string[];
export type TenantId13 = string;
export type UserId = string;
/**
 * How we know the rate. Shown next to every rate in the UI.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "RateBasis".
 */
export type RateBasis1 =
  "published" | "rate_sheet_upper" | "regulatory_cap" | "last_published" | "modelled" | "own_terms";
export type Benchmark = string | null;
export type InterpretationKey = string | null;
/**
 * e.g. 'current_ratio'
 */
export type Name3 = string;
/**
 * None when the denominator is zero or missing
 */
export type Value6 = string | null;
/**
 * @maxItems 3
 */
export type ActionCards =
  [] | [ActionCard] | [ActionCard, ActionCard] | [ActionCard, ActionCard, ActionCard];
export type AnswerText = string | null;
export type Checks = CheckResult[];
export type Claims = Claim[];
export type CreatedAt5 = string;
export type CriticObjection = string | null;
export type Figures3 = Figure[];
export type Id17 = string;
export type Question1 = string;
export type BaselineChoice = string;
export type RecommendationId = string;
/**
 * @minItems 1
 */
export type Results = [VariationResult, ...VariationResult[]];
export type Choice1 = string;
export type Held = boolean;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "VariationKind".
 */
export type VariationKind = "stress" | "noise";
/**
 * e.g. 'sales_minus_20' or 'rows_shuffled'
 */
export type Name4 = string;
/**
 * Share of variations where the choice held
 */
export type Score1 = string;
export type WhatWouldFlip = string[];
export type TenantId14 = string;
export type ToolsUsed = string[];
export type CounterpartyToken4 = string;
/**
 * Day of month (or weekday 1-7)
 */
export type DayOfPeriod = number;
export type EndDate = string | null;
export type Id18 = string;
export type SourceRef3 = string;
export type StartDate = string;
export type TenantId15 = string;
export type Id19 = string;
export type NameKey = string;
export type PBufferBreach1 = string;
export type Paths1 = number;
export type Seed1 = number;
export type CreatedAt6 = string;
export type ExpiresAt4 = string;
export type Id20 = string;
export type LenderLabel = string;
export type PassportId = string;
export type Revoked = boolean;
/**
 * @minItems 1
 */
export type Scopes1 = [string, ...string[]];
export type TenantId16 = string;
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "TxCategory".
 */
export type TxCategory1 =
  | "sales"
  | "collection"
  | "purchase"
  | "supplier_payment"
  | "rent"
  | "salary"
  | "loan_repayment"
  | "loan_disbursement"
  | "utility"
  | "tax"
  | "owner_draw"
  | "owner_topup"
  | "transfer"
  | "fee"
  | "other";
export type Actual = string;
export type Expected = string;
export type Metric3 = string;
export type Rank1 = number;
export type Commodity1 = string;
export type LeadTimeDays1 = number;
/**
 * Share of past orders delivered on time (SME's own history)
 */
export type OnTimeRate = string | null;
export type QuotedOn = string;
export type Unit2 = string;
export type VendorToken = string;
export type AnchoredDigest = string | null;
export type CheckedOn1 = string;
export type PassportId1 = string;
export type RecomputedDigest = string;
export type Valid = boolean;

export interface HishabContracts {
  Abstention?: Abstention;
  AbstentionReason?: AbstentionReason;
  ActionCard?: ActionCard;
  ActionType?: ActionType;
  AgreementReport?: AgreementReport;
  Alert?: Alert;
  AlertTier?: AlertTier;
  AnchorChain?: AnchorChain;
  AnchorReceipt?: AnchorReceipt;
  ApiError?: ApiError;
  Approval?: Approval;
  ApprovalStatus?: ApprovalStatus;
  Attestation?: Attestation;
  AttestationKind?: AttestationKind;
  AuditEvent?: AuditEvent;
  Bill?: Bill;
  CashGap?: CashGap;
  Channel?: Channel;
  CheckResult?: CheckResult;
  CheckStatus?: CheckStatus;
  Claim?: Claim;
  Currency?: Currency1;
  DataMode?: DataMode;
  Direction?: Direction;
  DocumentStatus?: DocumentStatus;
  DraftRow?: DraftRow;
  DraftStatus?: DraftStatus;
  DriverKind?: DriverKind;
  Eligibility?: Eligibility;
  EligibilityReason?: EligibilityReason;
  EligibilityRule?: EligibilityRule;
  EligibilityStatus?: EligibilityStatus;
  EvidenceItem?: EvidenceItem;
  EvidenceKind?: EvidenceKind;
  ExplainedInput?: ExplainedInput;
  Explanation?: Explanation;
  Fact?: Fact;
  Fee?: Fee;
  FeeKind?: FeeKind;
  FeeTiming?: FeeTiming1;
  Figure?: Figure;
  FinancingNeed?: FinancingNeed;
  FinancingOption?: FinancingOption;
  FinancingProduct?: FinancingProduct;
  ForecastBand?: ForecastBand;
  ForecastPoint?: ForecastPoint;
  FormulaRef?: FormulaRef;
  Frequency?: Frequency;
  GapDriver?: GapDriver;
  Granularity?: Granularity1;
  IngestPreview?: IngestPreview;
  Invoice?: Invoice;
  Language?: Language;
  LeadingIndicator?: LeadingIndicator;
  LenderProfile?: LenderProfile;
  LeverKind?: LeverKind;
  LicenceStatus?: LicenceStatus;
  MeshObligation?: MeshObligation;
  MessageChannel?: MessageChannel;
  MessageDraft?: MessageDraft;
  MessagePurpose?: MessagePurpose;
  Money?: Money;
  NettingRound?: NettingRound;
  ObligationKind?: ObligationKind;
  ObligationStatus?: ObligationStatus1;
  Party?: Party;
  PartyRole?: PartyRole;
  PassportVersion?: PassportVersion;
  Period?: Period;
  PricePoint?: PricePoint;
  PriceSource?: PriceSource;
  Principal?: Principal;
  ProductKind?: ProductKind;
  Provenance?: Provenance;
  RateBasis?: RateBasis1;
  RateType?: RateType;
  Ratio?: Ratio;
  Recommendation?: Recommendation;
  RecurringObligation?: RecurringObligation;
  Role?: Role;
  RoundStatus?: RoundStatus;
  RuleOp?: RuleOp;
  Scenario?: Scenario;
  Settlement?: Settlement;
  ShareGrant?: ShareGrant;
  SmoothingLever?: SmoothingLever;
  SourceFormat?: SourceFormat;
  StabilityReport?: StabilityReport;
  Tier?: Tier;
  Transaction?: Transaction;
  TxCategory?: TxCategory1;
  Unit?: Unit;
  UnparsedRow?: UnparsedRow;
  Variance?: Variance;
  VariationKind?: VariationKind;
  VariationResult?: VariationResult;
  VendorQuote?: VendorQuote;
  VerifyResult?: VerifyResult;
  Vote?: Vote;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Abstention".
 */
export interface Abstention {
  detail?: Detail;
  message_key: MessageKey;
  missing?: Missing;
  reason: AbstentionReason;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ActionCard".
 */
export interface ActionCard {
  action_type: ActionType;
  cost?: Figure | null;
  expires_at?: ExpiresAt;
  figures?: Figures;
  id: Id1;
  /**
   * Effect, e.g. gap reduced by Tk X
   */
  impact?: Figure | null;
  payload?: Payload;
  tier: Tier;
  title_key: TitleKey;
}
/**
 * A number shown to a user. Always computed by code, always explainable.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Figure".
 */
export interface Figure {
  data_mode: DataMode;
  id: Id;
  label_key: LabelKey;
  provenance: Provenance;
  unit: Unit;
  value: Value;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Provenance".
 */
export interface Provenance {
  formula_id: FormulaId;
  formula_version: FormulaVersion;
  input_fact_ids?: InputFactIds;
  parameters?: Parameters;
  source_row_ids?: SourceRowIds;
}
/**
 * Non-fact inputs such as seed or horizon, as strings
 */
export interface Parameters {
  [k: string]: string;
}
export interface Payload {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AgreementReport".
 */
export interface AgreementReport {
  agreement_rate: AgreementRate;
  question: Question;
  stakes: Stakes;
  threshold: Threshold;
  votes: Votes;
  winning_choice: WinningChoice;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Vote".
 */
export interface Vote {
  choice: Choice;
  model: Model;
  rationale?: Rationale;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Alert".
 */
export interface Alert {
  created_at: CreatedAt;
  data_mode: DataMode;
  dedupe_key: DedupeKey;
  fixes?: Fixes;
  gap?: CashGap | null;
  id: Id2;
  indicators?: Indicators;
  tenant_id: TenantId;
  tier: AlertTier;
  title_key: TitleKey1;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "CashGap".
 */
export interface CashGap {
  drivers?: Drivers;
  expected_shortfall: Money;
  figures?: Figures1;
  first_breach_day: FirstBreachDay;
  lead_time_days: LeadTimeDays;
  probability: Probability;
  worst_day: WorstDay;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "GapDriver".
 */
export interface GapDriver {
  amount: Money;
  counterparty_token?: CounterpartyToken;
  kind: DriverKind;
  label_key: LabelKey1;
  reference_id?: ReferenceId;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Money".
 */
export interface Money {
  amount: Amount;
  currency?: Currency;
}
/**
 * Proof that a digest was anchored. Only a SHA-256 hex digest ever goes on chain.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AnchorReceipt".
 */
export interface AnchorReceipt {
  anchored_at: AnchoredAt;
  block_number?: BlockNumber;
  chain: AnchorChain;
  digest: Digest;
  explorer_url?: ExplorerUrl;
  tx_hash?: TxHash;
}
/**
 * Error body returned by every endpoint. `message_key` is an i18n key.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  code: Code;
  detail?: Detail1;
  message_key: MessageKey1;
}
export interface Detail1 {
  [k: string]: string;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Approval".
 */
export interface Approval {
  action_card_id: ActionCardId;
  created_at: CreatedAt1;
  decided_by?: DecidedBy;
  expires_at: ExpiresAt1;
  id: Id3;
  idempotency_key: IdempotencyKey;
  requested_by: RequestedBy;
  status: ApprovalStatus;
  step_up_verified?: StepUpVerified;
  tenant_id: TenantId1;
  tier: Tier;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Attestation".
 */
export interface Attestation {
  attester_tenant: AttesterTenant;
  created_at: CreatedAt2;
  digest: Digest1;
  id: Id4;
  kind: AttestationKind;
  obligation_id: ObligationId;
}
/**
 * One link of the append-only, SHA-256 hash-chained audit log.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "AuditEvent".
 */
export interface AuditEvent {
  action: Action;
  actor: Actor;
  at: At;
  details_digest: DetailsDigest;
  hash: Hash;
  prev_hash: PrevHash;
  seq: Seq;
  target?: Target;
  tenant_id: TenantId2;
  tier?: Tier | null;
}
/**
 * Money the business owes a supplier.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Bill".
 */
export interface Bill {
  amount: Money;
  amount_paid: Money;
  counterparty_token: CounterpartyToken1;
  data_mode: DataMode;
  due_date: DueDate;
  id: Id5;
  issue_date: IssueDate;
  paid_date?: PaidDate;
  source_ref: SourceRef;
  status: DocumentStatus;
  tenant_id: TenantId3;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "CheckResult".
 */
export interface CheckResult {
  claim_id: ClaimId;
  reason?: Reason;
  recomputed_value?: RecomputedValue;
  status: CheckStatus;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Claim".
 */
export interface Claim {
  formula_id?: FormulaId1;
  id: Id6;
  input_fact_ids?: InputFactIds1;
  text: Text;
  unit?: Unit | null;
  value?: Value1;
}
/**
 * An OCR'd or uncertain row the owner must confirm before it is committed.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "DraftRow".
 */
export interface DraftRow {
  confidence: Confidence;
  flagged: Flagged;
  invoice?: Invoice | null;
  row_ref: RowRef;
  transaction?: Transaction | null;
}
/**
 * Money a customer owes the business (includes baki / credit sales).
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Invoice".
 */
export interface Invoice {
  amount: Money;
  amount_paid: Money;
  counterparty_token: CounterpartyToken2;
  data_mode: DataMode;
  due_date: DueDate1;
  id: Id7;
  issue_date: IssueDate1;
  paid_date?: PaidDate1;
  source_ref: SourceRef1;
  status: DocumentStatus;
  tenant_id: TenantId4;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Transaction".
 */
export interface Transaction {
  amount: Money1;
  category?: TxCategory;
  channel: Channel;
  counterparty_token?: CounterpartyToken3;
  data_mode: DataMode;
  direction: Direction;
  id: Id8;
  invoice_id?: InvoiceId;
  occurred_at: OccurredAt;
  reference?: Reference;
  source_ref: SourceRef2;
  tenant_id: TenantId5;
}
/**
 * Always positive; `direction` gives the sign
 */
export interface Money1 {
  amount: Amount;
  currency?: Currency;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Eligibility".
 */
export interface Eligibility {
  product_id: ProductId;
  reasons?: Reasons;
  status: EligibilityStatus;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "EligibilityReason".
 */
export interface EligibilityReason {
  message_key: MessageKey2;
  observed_value?: ObservedValue;
  rule_id: RuleId;
  status: EligibilityStatus;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "EligibilityRule".
 */
export interface EligibilityRule {
  description_key: DescriptionKey;
  id: Id9;
  metric: Metric;
  op: RuleOp;
  threshold?: Threshold1;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "EvidenceItem".
 */
export interface EvidenceItem {
  digest: Digest2;
  kind: EvidenceKind;
  period?: Period | null;
  verified: Verified;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Period".
 */
export interface Period {
  end: End;
  granularity?: Granularity;
  start: Start;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ExplainedInput".
 */
export interface ExplainedInput {
  fact_id: FactId;
  metric: Metric1;
  unit: Unit;
  value: Value2;
}
/**
 * Answer of `GET /explain/{figure_id}`.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Explanation".
 */
export interface Explanation {
  figure_id: FigureId;
  formula: FormulaRef;
  inputs: Inputs;
  masked: Masked;
  source_rows: SourceRows;
  unit: Unit;
  value: Value3;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FormulaRef".
 */
export interface FormulaRef {
  expression: Expression;
  formula_id: FormulaId2;
  version: Version;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Fact".
 */
export interface Fact {
  computed_at?: ComputedAt;
  data_mode: DataMode;
  entity_token?: EntityToken;
  id: Id10;
  metric: Metric2;
  period: Period;
  /**
   * None only for raw facts read straight from a source row
   */
  provenance?: Provenance | null;
  source_refs?: SourceRefs;
  tenant_id: TenantId6;
  unit: Unit;
  value: Value4;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Fee".
 */
export interface Fee {
  kind: FeeKind;
  name: Name;
  timing?: FeeTiming;
  value: Value5;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FinancingNeed".
 */
export interface FinancingNeed {
  amount: Money;
  needed_by: NeededBy;
  purpose_key?: PurposeKey;
  tenant_id: TenantId7;
  tenor_days: TenorDays;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FinancingOption".
 */
export interface FinancingOption {
  approval_likelihood: ApprovalLikelihood;
  effective_apr: EffectiveApr;
  eligibility: Eligibility;
  figures?: Figures2;
  p_buffer_breach: PBufferBreach;
  product: FinancingProduct;
  rank: Rank;
  reason_keys?: ReasonKeys;
  score: Score;
  speed_days: SpeedDays;
  total_cost: Money;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "FinancingProduct".
 */
export interface FinancingProduct {
  checked_on?: CheckedOn;
  collateral_required?: CollateralRequired;
  data_mode: DataMode;
  fees?: Fees;
  id: Id11;
  is_modelled?: IsModelled;
  kind: ProductKind;
  max_amount?: Money | null;
  max_tenor_days?: MaxTenorDays;
  min_amount?: Money | null;
  min_tenor_days?: MinTenorDays;
  name: Name1;
  nominal_rate_pa: NominalRatePa;
  notes?: Notes;
  provider: Provider;
  rate_basis?: RateBasis;
  rate_type: RateType;
  rules?: Rules;
  source_url?: SourceUrl;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ForecastBand".
 */
export interface ForecastBand {
  as_of: AsOf;
  buffer: Money;
  data_mode: DataMode;
  generated_at: GeneratedAt;
  horizon_days: HorizonDays;
  opening_balance: Money;
  paths: Paths;
  points: Points;
  seed: Seed;
  tenant_id: TenantId8;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ForecastPoint".
 */
export interface ForecastPoint {
  day: Day;
  p10: Money2;
  p50: Money3;
  p90: Money4;
  p_below_buffer: PBelowBuffer;
}
/**
 * Worst-case band (10th percentile balance)
 */
export interface Money2 {
  amount: Amount;
  currency?: Currency;
}
/**
 * Likely balance (median)
 */
export interface Money3 {
  amount: Amount;
  currency?: Currency;
}
/**
 * Best-case band (90th percentile balance)
 */
export interface Money4 {
  amount: Amount;
  currency?: Currency;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "IngestPreview".
 */
export interface IngestPreview {
  bills?: Bills;
  data_mode: DataMode;
  drafts?: Drafts;
  duplicates_skipped?: DuplicatesSkipped;
  file_digest: FileDigest;
  invoices?: Invoices;
  preview_id: PreviewId;
  source_format: SourceFormat;
  tenant_id: TenantId9;
  transactions?: Transactions;
  unparsed?: Unparsed;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "UnparsedRow".
 */
export interface UnparsedRow {
  raw_excerpt: RawExcerpt;
  reason_key: ReasonKey;
  row_ref: RowRef1;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "LenderProfile".
 */
export interface LenderProfile {
  data_mode: DataMode;
  disputes?: Disputes;
  events_count: EventsCount;
  hidden_fee_incidents?: HiddenFeeIncidents;
  lender_id: LenderId;
  licence_status: LicenceStatus;
  median_disbursal_days?: MedianDisbursalDays;
  name: Name2;
  quoted_vs_realised_apr_gap?: QuotedVsRealisedAprGap;
  regulator?: Regulator;
}
/**
 * `debtor_tenant` owes `creditor_tenant`. Both are Hishab tenants that opted in.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "MeshObligation".
 */
export interface MeshObligation {
  amount: Money;
  attested?: Attested;
  creditor_tenant: CreditorTenant;
  data_mode: DataMode;
  debtor_tenant: DebtorTenant;
  due_date: DueDate2;
  id: Id12;
  invoice_ref?: InvoiceRef;
  status?: ObligationStatus;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "MessageDraft".
 */
export interface MessageDraft {
  body: Body;
  channel: MessageChannel;
  created_at: CreatedAt3;
  data_mode: DataMode;
  id: Id13;
  language: Language;
  purpose: MessagePurpose;
  recipient_token: RecipientToken;
  status?: DraftStatus1;
  template_id: TemplateId;
  tenant_id: TenantId10;
  tier: Tier;
  variables?: Variables;
}
/**
 * Filled from typed facts only
 */
export interface Variables {
  [k: string]: string;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "NettingRound".
 */
export interface NettingRound {
  anchor?: AnchorReceipt | null;
  approvals?: Approvals;
  created_at: CreatedAt4;
  data_mode: DataMode;
  expires_at: ExpiresAt2;
  gross_total: Money;
  id: Id14;
  net_total: Money;
  obligation_ids: ObligationIds;
  participants: Participants;
  settlements: Settlements;
  status: RoundStatus;
}
/**
 * tenant -> approved?; missing = not answered yet
 */
export interface Approvals {
  [k: string]: boolean;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Settlement".
 */
export interface Settlement {
  amount: Money;
  payee_tenant: PayeeTenant;
  payer_tenant: PayerTenant;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Party".
 */
export interface Party {
  data_mode: DataMode;
  display_label: DisplayLabel;
  id: Id15;
  is_tenant?: IsTenant;
  role: PartyRole;
  tenant_id: TenantId11;
  token: Token;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "PassportVersion".
 */
export interface PassportVersion {
  abstention_rate?: AbstentionRate;
  anchor?: AnchorReceipt | null;
  attestations_confirmed: AttestationsConfirmed;
  attestations_disputed: AttestationsDisputed;
  audit_drill_catch_rate?: AuditDrillCatchRate;
  data_mode: DataMode;
  digest: Digest3;
  evidence: Evidence;
  id: Id16;
  issued_at: IssuedAt;
  tenant_id: TenantId12;
  version: Version1;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "PricePoint".
 */
export interface PricePoint {
  commodity: Commodity;
  data_mode: DataMode;
  high?: Money | null;
  low?: Money | null;
  market: Market;
  observed_on: ObservedOn;
  price: Money5;
  source: PriceSource;
  source_url?: SourceUrl1;
  unit: Unit1;
}
/**
 * Mid price; low/high when the source gives a range
 */
export interface Money5 {
  amount: Amount;
  currency?: Currency;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Principal".
 */
export interface Principal {
  expires_at?: ExpiresAt3;
  role: Role;
  scopes?: Scopes;
  tenant_id: TenantId13;
  user_id: UserId;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Ratio".
 */
export interface Ratio {
  benchmark?: Benchmark;
  interpretation_key?: InterpretationKey;
  name: Name3;
  period: Period;
  provenance: Provenance;
  unit: Unit;
  value: Value6;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Recommendation".
 */
export interface Recommendation {
  abstention?: Abstention | null;
  action_cards?: ActionCards;
  agreement?: AgreementReport | null;
  answer_text?: AnswerText;
  checks?: Checks;
  claims?: Claims;
  created_at: CreatedAt5;
  critic_objection?: CriticObjection;
  data_mode: DataMode;
  figures?: Figures3;
  id: Id17;
  question: Question1;
  stability?: StabilityReport | null;
  tenant_id: TenantId14;
  tools_used?: ToolsUsed;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "StabilityReport".
 */
export interface StabilityReport {
  baseline_choice: BaselineChoice;
  recommendation_id: RecommendationId;
  results: Results;
  score: Score1;
  what_would_flip?: WhatWouldFlip;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "VariationResult".
 */
export interface VariationResult {
  choice: Choice1;
  held: Held;
  kind: VariationKind;
  name: Name4;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "RecurringObligation".
 */
export interface RecurringObligation {
  amount: Money;
  counterparty_token: CounterpartyToken4;
  data_mode: DataMode;
  day_of_period: DayOfPeriod;
  end_date?: EndDate;
  frequency: Frequency;
  id: Id18;
  kind: ObligationKind;
  source_ref: SourceRef3;
  start_date: StartDate;
  tenant_id: TenantId15;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Scenario".
 */
export interface Scenario {
  assumptions: Assumptions;
  expected_outcome: Money;
  id: Id19;
  name_key: NameKey;
  p_buffer_breach: PBufferBreach1;
  paths: Paths1;
  seed: Seed1;
  worst_5pct_outcome: Money;
}
/**
 * Shock name -> size, e.g. {'sales_change_pct': -20}
 */
export interface Assumptions {
  [k: string]: string;
}
/**
 * Consented, scoped, expiring access for one lender.
 *
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "ShareGrant".
 */
export interface ShareGrant {
  created_at: CreatedAt6;
  expires_at: ExpiresAt4;
  id: Id20;
  lender_label: LenderLabel;
  passport_id: PassportId;
  revoked?: Revoked;
  scopes: Scopes1;
  tenant_id: TenantId16;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "SmoothingLever".
 */
export interface SmoothingLever {
  action: ActionCard;
  cost: Money;
  gap_reduction: Money;
  kind: LeverKind;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "Variance".
 */
export interface Variance {
  actual: Actual;
  expected: Expected;
  metric: Metric3;
  period: Period;
  rank: Rank1;
  unit: Unit;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "VendorQuote".
 */
export interface VendorQuote {
  commodity: Commodity1;
  data_mode: DataMode;
  delivery_cost: Money;
  lead_time_days: LeadTimeDays1;
  on_time_rate?: OnTimeRate;
  quoted_on: QuotedOn;
  unit: Unit2;
  unit_price: Money;
  vendor_token: VendorToken;
}
/**
 * This interface was referenced by `HishabContracts`'s JSON-Schema
 * via the `definition` "VerifyResult".
 */
export interface VerifyResult {
  anchored_digest?: AnchoredDigest;
  checked_on: CheckedOn1;
  passport_id: PassportId1;
  recomputed_digest: RecomputedDigest;
  valid: Valid;
}

export const CONTRACTS_VERSION = "1.1.0";
