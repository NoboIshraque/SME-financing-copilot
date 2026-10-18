// Mock WP-04 output for the grocery: a 13-week band, headline figures, alerts and their fixes.
import type { ActionCard, Alert, ForecastBand, ForecastPoint } from "../../api/contracts";
import type { CashForecast } from "../../api/types";
import { AS_OF, NOW, SEED, TENANT, dayAfterAsOf, figure, money } from "./common";

export const BUFFER = 100000;
export const HORIZON_DAYS = 91;

// Likely (P50) balance at a few days after the as-of date; straight lines in between. Dips:
// two supplier bills on 3 Oct, rent on the 5th, salaries on the last day of each month.
const P50_ANCHORS: ReadonlyArray<readonly [number, number]> = [
  [0, 427842],
  [2, 445000],
  [3, 280000],
  [5, 255000],
  [15, 215000],
  [30, 160000],
  [31, 96000],
  [33, 92000],
  [36, 85000],
  [41, 140000],
  [60, 230000],
  [61, 170000],
  [66, 150000],
  [91, 265000],
];

function likely(day: number): number {
  for (let i = 1; i < P50_ANCHORS.length; i += 1) {
    const [d1, v1] = P50_ANCHORS[i] as readonly [number, number];
    const [d0, v0] = P50_ANCHORS[i - 1] as readonly [number, number];
    if (day <= d1) return Math.round(v0 + ((v1 - v0) * (day - d0)) / (d1 - d0));
  }
  return P50_ANCHORS[P50_ANCHORS.length - 1]?.[1] ?? 0;
}

/** P(balance < buffer) read off the P10/P50/P90 band (mock interpolation, two decimals). */
function belowBuffer(p10: number, p50: number, p90: number): string {
  let p: number;
  if (BUFFER <= p10) p = Math.max(0, 0.1 - (0.1 * (p10 - BUFFER)) / (p50 - p10));
  else if (BUFFER <= p50) p = 0.1 + (0.4 * (BUFFER - p10)) / (p50 - p10);
  else if (BUFFER <= p90) p = 0.5 + (0.4 * (BUFFER - p50)) / (p90 - p50);
  else p = Math.min(1, 0.9 + (0.1 * (BUFFER - p90)) / (p90 - p50));
  return p.toFixed(2);
}

export function forecastPoints(): ForecastPoint[] {
  return Array.from({ length: HORIZON_DAYS }, (_, i) => {
    const day = i + 1;
    const p50 = likely(day);
    const p10 = p50 - (1500 * day + 5000);
    const p90 = p50 + (1300 * day + 5000);
    return { day: dayAfterAsOf(day), p10: money(p10), p50: money(p50), p90: money(p90), p_below_buffer: belowBuffer(p10, p50, p90) };
  });
}

export function forecastBand(): ForecastBand {
  return {
    tenant_id: TENANT,
    as_of: AS_OF,
    horizon_days: HORIZON_DAYS,
    paths: 1000,
    seed: SEED,
    opening_balance: money(427842),
    buffer: money(BUFFER),
    points: forecastPoints(),
    data_mode: "synthetic",
    generated_at: NOW,
  };
}

const MC = { paths: "1000", seed: String(SEED), horizon_days: String(HORIZON_DAYS) };

export function cashForecast(): CashForecast {
  return {
    band: forecastBand(),
    figures: [
      figure("fig-cash-balance", "cash.closing_balance", "427842.00", "BDT", {
        formula_id: "cash.closing_balance",
        input_fact_ids: ["fact-opening-2026-09", "fact-cash-in-2026-09", "fact-cash-out-2026-09"],
        source_row_ids: ["bank_statement.csv#L820", "bkash_statement.csv#L3533", "nagad_statement.csv#L1548", "cash_book.csv#L3448"],
      }),
      figure("fig-cash-buffer", "cash.buffer_target", "100000.00", "BDT", {
        formula_id: "cash.buffer_target",
        parameters: { ...MC, coverage: "19 of 20 paths" },
      }),
      figure("fig-cash-runway", "cash.runway_days", "31", "days", {
        formula_id: "cash.runway_days",
        input_fact_ids: ["fig-cash-buffer"],
        parameters: MC,
      }),
      figure("fig-cash-lowest", "cash.lowest_likely_balance", "85000.00", "BDT", {
        formula_id: "cash.forecast_p50_min",
        parameters: MC,
      }),
    ],
  };
}

export const CARD_REMIND: ActionCard = {
  id: "act-remind-customer-9",
  title_key: "action.send_reminder",
  action_type: "send_reminder",
  tier: "DRAFT",
  payload: { counterparty_label: "Customer 9", due_date: "2026-09-21", invoice_count: "4" },
  impact: figure("fig-act-remind-impact", "action.expected_collection", "8208.00", "BDT", {
    formula_id: "receivables.overdue_sum",
    source_row_ids: ["baki_register.csv#L688", "baki_register.csv#L692", "baki_register.csv#L697", "baki_register.csv#L700"],
  }),
  expires_at: "2026-10-01T18:00:00Z",
};

export const CARD_RETIME: ActionCard = {
  id: "act-retime-supplier-2",
  title_key: "action.retime_payable",
  action_type: "retime_payable",
  tier: "EXECUTE",
  payload: { counterparty_label: "Supplier 2", due_date: "2026-10-31", new_date: "2026-11-10" },
  impact: figure("fig-act-retime-impact", "action.gap_reduced", "48500.00", "BDT", {
    formula_id: "cash.lever_gap_reduction",
    input_fact_ids: ["fig-gap-shortfall"],
    parameters: MC,
  }),
  cost: figure("fig-act-retime-cost", "action.cost", "0.00", "BDT", {
    formula_id: "cash.lever_cost",
    parameters: { terms_days: "14" },
  }),
  expires_at: "2026-10-01T18:00:00Z",
};

export const CARD_STANDBY: ActionCard = {
  id: "act-view-financing",
  title_key: "action.compare_financing",
  action_type: "view",
  tier: "READ",
  payload: { screen: "financing" },
};

export function alerts(): Alert[] {
  return [
    {
      id: "al-gap-2026-10-31",
      tenant_id: TENANT,
      tier: "warning",
      title_key: "alert.gap_ahead",
      gap: {
        first_breach_day: "2026-10-31",
        lead_time_days: 31,
        probability: "0.54",
        expected_shortfall: money(48500),
        worst_day: "2026-11-05",
        drivers: [
          { kind: "obligation", label_key: "driver.salary", amount: money(60000), reference_id: "sme_grocery:OBL-2" },
          { kind: "bill_due", label_key: "driver.supplier_bill", amount: money(82618), counterparty_token: "PARTY_efd9a5e9e9" },
          { kind: "late_customer", label_key: "driver.late_customer", amount: money(8208), counterparty_token: "PARTY_9ad3f2ee60" },
        ],
        figures: [
          figure("fig-gap-shortfall", "cash.expected_shortfall", "48500.00", "BDT", { formula_id: "cash.expected_shortfall", parameters: MC }),
          figure("fig-gap-probability", "cash.breach_probability", "0.54", "probability", { formula_id: "cash.p_below_buffer", parameters: MC }),
        ],
      },
      indicators: ["top_customer_slowing"],
      fixes: [CARD_RETIME, CARD_REMIND],
      dedupe_key: "gap:2026-10-31",
      created_at: NOW,
      data_mode: "synthetic",
    },
    {
      id: "al-sales-norm",
      tenant_id: TENANT,
      tier: "watch",
      title_key: "alert.sales_below_norm",
      gap: null,
      indicators: ["sales_below_seasonal_norm", "dso_rising"],
      fixes: [],
      dedupe_key: "indicator:sales-2026-09",
      created_at: NOW,
      data_mode: "synthetic",
    },
  ];
}
