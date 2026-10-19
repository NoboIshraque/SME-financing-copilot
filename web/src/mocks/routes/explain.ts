// Mock of WP-01's GET /api/explain/{figure_id} for every figure the mock screens show.
import type { ExplainedInput, Explanation, Figure } from "../../api/contracts";
import { callerRole, type MockDb } from "../db";
import { ratios, statements, variance } from "../fixtures/analysis";
import { alerts, cashForecast } from "../fixtures/cash";
import { todayRecommendation } from "../fixtures/copilot";
import { DEFAULT_NEED, financingMatch } from "../fixtures/financing";
import { auditDrill } from "../fixtures/inbox";
import { marketAlerts, vendorRanking } from "../fixtures/market";
import { receivablesOverview, reminderPlan } from "../fixtures/receivables";
import { apiError, ok, type MockRoute } from "../http";

const FORMULAS: Record<string, string> = {
  "cash.closing_balance": "opening_balance + cash_in - cash_out",
  "cash.buffer_target": "balance that covers the worst dip in 19 of 20 simulated paths",
  "cash.runway_days": "days until the median (P50) balance first falls below the buffer",
  "cash.forecast_p50_min": "min over days of the median (P50) balance",
  "cash.expected_shortfall": "mean of (buffer - balance) over the paths that fall below the buffer",
  "cash.p_below_buffer": "share of simulated paths below the buffer on the first breach day",
  "cash.lever_gap_reduction": "expected_shortfall(before) - expected_shortfall(after lever)",
  "cash.lever_cost": "fees + interest + discount given up by the lever",
  "receivables.open": "sum(amount - amount_paid) over open invoices",
  "receivables.overdue_sum": "sum(amount - amount_paid) over invoices past their due date",
  "receivables.dso": "receivables / net_sales * days_in_period",
  "receivables.credit_limit": "min(policy cap, 2 x average monthly credit purchases x on-time share)",
  "financing.effective_annual_rate": "annualised IRR of the cash received vs every repayment and fee",
  "financing.total_cost": "sum(interest + fees) for this amount and tenor",
  "analysis.forecast_accuracy": "1 - weighted absolute percentage error of the frozen forecast",
  "market.change_vs_4w_median": "(latest price - 4-week median) / 4-week median * 100",
  "market.landed_cost_per_unit": "price + delivery per unit + waiting cost + reliability penalty",
  "trust.audit_drill_catch_rate": "caught / planted errors in last night's sandbox ledger",
};

const INPUTS: Record<string, ExplainedInput[]> = {
  "fig-cash-balance": [
    { fact_id: "fact-opening-2026-09", metric: "opening_balance", value: "348635.00", unit: "BDT" },
    { fact_id: "fact-cash-in-2026-09", metric: "cash_in", value: "1608740.00", unit: "BDT" },
    { fact_id: "fact-cash-out-2026-09", metric: "cash_out", value: "1529533.00", unit: "BDT" },
  ],
};

function isFigure(value: unknown): value is Figure {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.id === "string" && typeof candidate.label_key === "string" && typeof candidate.provenance === "object";
}

function collect(value: unknown, into: Map<string, Figure>): void {
  if (Array.isArray(value)) value.forEach((item) => collect(item, into));
  else if (typeof value === "object" && value !== null) {
    if (isFigure(value)) into.set(value.id, value);
    Object.values(value).forEach((child) => collect(child, into));
  }
}

function figures(db: MockDb): Map<string, Figure> {
  const all = new Map<string, Figure>();
  collect(
    [cashForecast(), alerts(), todayRecommendation(), receivablesOverview(db.disputes), reminderPlan(), financingMatch(DEFAULT_NEED), statements(), ratios(), variance(), marketAlerts(), vendorRanking("rice_coarse"), auditDrill()],
    all,
  );
  return all;
}

export const explainRoutes: MockRoute[] = [
  {
    method: "GET",
    pattern: "/api/explain/:id",
    handler: (req, db) => {
      const figure = figures(db).get(req.params.id ?? "");
      if (!figure) return apiError(404, "figure_not_found", "error.figure_not_found", { figure_id: req.params.id ?? "" });
      const masked = callerRole(db) === "lender_viewer";
      const explanation: Explanation = {
        figure_id: figure.id,
        formula: {
          formula_id: figure.provenance.formula_id,
          version: figure.provenance.formula_version,
          expression: FORMULAS[figure.provenance.formula_id] ?? figure.provenance.formula_id,
        },
        value: figure.value,
        unit: figure.unit,
        inputs: INPUTS[figure.id] ?? [],
        source_rows: masked ? [] : (figure.provenance.source_row_ids ?? []),
        masked,
      };
      return ok(explanation);
    },
  },
];
