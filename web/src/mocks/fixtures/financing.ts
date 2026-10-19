// Mock WP-06 output. Products mirror rows of data/public/financing/bd.yaml (public data, checked
// 2026-10-18); costs are for the request below and illustrative. Lender track records come from
// the synthetic mesh history and are labelled synthetic.
import type { ActionCard, FinancingNeed, FinancingOption, FinancingProduct, LenderProfile } from "../../api/contracts";
import type { FinancingMatch } from "../../api/types";
import { TENANT, figure, money } from "./common";

const BB_FEE = [{ name: "processing (BB ceiling 0.5%)", kind: "percent_of_principal" as const, value: "0.5", timing: "upfront" as const }];

function product(p: Partial<FinancingProduct> & Pick<FinancingProduct, "id" | "provider" | "name" | "kind" | "nominal_rate_pa">): FinancingProduct {
  return { rate_type: "reducing_balance", data_mode: "public", checked_on: "2026-10-18", fees: BB_FEE, rules: [], ...p };
}

function option(
  rank: number,
  p: FinancingProduct,
  apr: string,
  cost: number,
  status: "pass" | "fail" | "not_on_record",
  reasons: FinancingOption["eligibility"]["reasons"],
  extra: { speed: number; likelihood: string; breach: string; score: string; reasonKeys?: string[] },
): FinancingOption {
  return {
    rank,
    product: p,
    effective_apr: apr,
    total_cost: money(cost),
    eligibility: { product_id: p.id, status, reasons },
    speed_days: extra.speed,
    approval_likelihood: extra.likelihood,
    p_buffer_breach: extra.breach,
    score: extra.score,
    reason_keys: extra.reasonKeys ?? [],
    figures: [
      figure(`fig-apr-${p.id}`, "financing.effective_apr", apr, "percent", {
        formula_id: "financing.effective_annual_rate",
        parameters: { nominal_rate_pa: p.nominal_rate_pa, rate_type: p.rate_type, tenor_days: "180", fees: String(p.fees?.length ?? 0) },
      }),
      figure(`fig-cost-${p.id}`, "financing.total_cost", `${cost}.00`, "BDT", {
        formula_id: "financing.total_cost",
        parameters: { amount: "200000.00", tenor_days: "180" },
      }),
    ],
  };
}

const pass = (rule_id: string, message_key: string, observed_value: string | null = null) => ({ rule_id, message_key, status: "pass" as const, observed_value });

export function financingMatch(need: FinancingNeed): FinancingMatch {
  const supplier = product({
    id: "nonloan-supplier-term-extension",
    provider: "Supplier 2",
    name: "Ask for 14 more days on the 31 Oct bill",
    kind: "supplier_term_extension",
    rate_type: "none",
    nominal_rate_pa: "0",
    rate_basis: "own_terms",
    fees: [],
    data_mode: "synthetic",
    checked_on: null,
    notes: "Covers ৳82,618 of the need, not all of it.",
  });
  const refinance = product({
    id: "bd-bb-cmsme-wc-refinance-2026",
    provider: "Bangladesh Bank (via participating banks)",
    name: "CMSME working capital refinance fund (Tk 5,000 crore)",
    kind: "refinance_scheme",
    nominal_rate_pa: "9.0",
    rate_basis: "regulatory_cap",
    source_url: null,
  });
  const bankAsia = product({
    id: "bd-bankasia-micro-wc",
    provider: "Bank Asia PLC",
    name: "Cottage/micro working capital (rate sheet)",
    kind: "working_capital",
    nominal_rate_pa: "13.0",
    rate_basis: "rate_sheet_upper",
  });
  const sbac = product({
    id: "bd-sbac-cmsme-term",
    provider: "South Bangla Agriculture and Commerce (SBAC) Bank PLC",
    name: "CMSME term / working capital loan",
    kind: "term_loan",
    nominal_rate_pa: "15.25",
    rate_basis: "published",
  });
  const prime = product({
    id: "bd-primebank-chalti",
    provider: "Prime Bank PLC",
    name: "Prime Chalti (SME working capital)",
    kind: "working_capital",
    nominal_rate_pa: "15.0",
    rate_basis: "rate_sheet_upper",
    collateral_required: true,
  });
  const bkash = product({
    id: "bd-citybank-bkash-loan",
    provider: "The City Bank PLC (via bKash)",
    name: "bKash digital loan",
    kind: "nano_loan",
    rate_type: "daily_debit",
    nominal_rate_pa: "9.0",
    rate_basis: "last_published",
    max_amount: money(50000),
    collateral_required: false,
  });

  const options = [
    option(1, supplier, "0", 0, "pass", [pass("supplier-history", "rule.supplier_relationship", "14")], {
      speed: 2, likelihood: "0.5", breach: "0.21", score: "88", reasonKeys: ["financing.reason.cheapest", "financing.reason.partial"],
    }),
    option(2, refinance, "10.52", 6250, "pass", [pass("wc-fund-no-default", "rule.no_default"), pass("wc-fund-licence", "rule.trade_licence_typical")], {
      speed: 24, likelihood: "0.55", breach: "0.06", score: "81", reasonKeys: ["financing.reason.low_cost", "financing.reason.fits_forecast"],
    }),
    option(3, bankAsia, "15.31", 8583, "pass", [pass("bankasia-wc-licence", "rule.trade_licence_typical")], {
      speed: 10, likelihood: "0.6", breach: "0.08", score: "74", reasonKeys: ["financing.reason.fast"],
    }),
    option(4, sbac, "17.71", 9896, "pass", [pass("sbac-licence", "rule.trade_licence_typical")], {
      speed: 21, likelihood: "0.45", breach: "0.09", score: "69",
    }),
    option(5, prime, "17.43", 9750, "not_on_record", [
      pass("prime-experience", "rule.business_age", "74"),
      { rule_id: "prime-collateral", message_key: "rule.collateral", status: "not_on_record", observed_value: null },
    ], { speed: 16, likelihood: "0.3", breach: "0.09", score: "55" }),
    option(6, bkash, "9.94", 2213, "fail", [
      pass("bkash-user", "rule.bkash_account"),
      { rule_id: "bkash-max", message_key: "rule.max_amount", status: "fail", observed_value: need.amount.amount },
    ], { speed: 0, likelihood: "0", breach: "0.31", score: "0" }),
  ];

  return { need, options, lenders: lenderProfiles(), application: CARD_APPLY };
}

export function lenderProfiles(): LenderProfile[] {
  const lender = (lender_id: string, name: string, events: number, gap: string, days: string, hidden: number, disputes: number): LenderProfile => ({
    lender_id, name, licence_status: "licensed", regulator: "Bangladesh Bank", events_count: events,
    quoted_vs_realised_apr_gap: gap, median_disbursal_days: days, hidden_fee_incidents: hidden, disputes, data_mode: "synthetic",
  });
  return [
    lender("bb-refinance", "Bangladesh Bank (via participating banks)", 9, "0.2", "24", 0, 0),
    lender("bank-asia", "Bank Asia PLC", 14, "0.3", "9", 0, 0),
    lender("sbac", "South Bangla Agriculture and Commerce (SBAC) Bank PLC", 3, "0.6", "21", 0, 1),
    lender("prime", "Prime Bank PLC", 6, "1.1", "16", 1, 0),
    lender("city-bkash", "The City Bank PLC (via bKash)", 31, "0.0", "0", 0, 0),
  ];
}

export const CARD_APPLY: ActionCard = {
  id: "act-apply-bb-refinance",
  title_key: "action.submit_loan_application",
  action_type: "submit_loan_application",
  tier: "EXECUTE",
  payload: { counterparty_label: "CMSME working capital refinance fund", product_id: "bd-bb-cmsme-wc-refinance-2026" },
  cost: figure("fig-apply-cost", "financing.total_cost", "6250.00", "BDT", { formula_id: "financing.total_cost", parameters: { amount: "200000.00", tenor_days: "180" } }),
};

export const DEFAULT_NEED: FinancingNeed = {
  tenant_id: TENANT,
  amount: money(200000),
  needed_by: "2026-10-25",
  tenor_days: 180,
  purpose_key: "purpose.working_capital",
};
