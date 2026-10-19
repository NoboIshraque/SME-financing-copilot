// Mock WP-07 output for the grocery, September 2026 (cash basis). Cash in/out match the
// universe's September totals; balance lines match the cash and receivables mocks.
import type { Ratio, Scenario, StabilityReport } from "../../api/contracts";
import type { ScenarioComparison, StatementLine, Statements, VarianceReport } from "../../api/types";
import { figure, money } from "./common";
import { todayRecommendation } from "./copilot";

const PERIOD = { start: "2026-09-01", end: "2026-09-30", granularity: "month" as const };

function line(key: string, amount: string, total = false): StatementLine {
  return {
    label_key: `statement.${key}`,
    total,
    figure: figure(`fig-stmt-${key}`, `statement.${key}`, amount, "BDT", {
      formula_id: `statement.${key}`,
      input_fact_ids: [`fact-${key}-2026-09`],
    }),
  };
}

export function statements(): Statements {
  return {
    period: PERIOD,
    pnl: [
      line("cash_sales", "1452300.00"),
      line("credit_sales", "128450.00"),
      line("net_sales", "1580750.00", true),
      line("purchases", "1342000.00"),
      line("gross_profit", "238750.00", true),
      line("rent", "35000.00"),
      line("salaries", "60000.00"),
      line("utilities", "9000.00"),
      line("fees", "3200.00"),
      line("net_profit", "131550.00", true),
    ],
    balance_sheet: [
      line("cash", "427842.00"),
      line("receivables", "21859.00"),
      line("payables", "165236.00"),
      line("loans", "0.00"),
      line("net_position", "284465.00", true),
    ],
    cash_flow: [
      line("opening_cash", "348635.00"),
      line("cash_in", "1608740.00"),
      line("cash_out", "1529533.00"),
      line("closing_cash", "427842.00", true),
    ],
  };
}

function ratio(name: string, value: string | null, unit: Ratio["unit"], interpretation: string | null, benchmark: string | null = null): Ratio {
  return {
    name,
    value,
    unit,
    period: PERIOD,
    benchmark,
    interpretation_key: interpretation,
    provenance: { formula_id: `analysis.${name}`, formula_version: 1, input_fact_ids: [`fact-${name}-inputs-2026-09`], source_row_ids: [] },
  };
}

export function ratios(): Ratio[] {
  return [
    ratio("gross_margin", "15.1", "percent", "interpretation.typical_grocery", "12-18"),
    ratio("net_margin", "8.3", "percent", "interpretation.healthy"),
    ratio("current_ratio", "2.73", "ratio", "interpretation.healthy", "1.5"),
    ratio("dso", "11.2", "days", "interpretation.healthy"),
    ratio("dpo", "3.7", "days", "interpretation.pays_fast"),
    ratio("top_customer_share", "15.4", "percent", "interpretation.concentrated"),
    ratio("dscr", null, "ratio", "interpretation.no_debt"),
  ];
}

export function variance(): VarianceReport {
  const v = (metric: string, expected: string, actual: string, rank: number) => ({ metric, expected, actual, rank, unit: "BDT" as const, period: PERIOD });
  return {
    period: PERIOD,
    variances: [
      v("net_sales", "1620000.00", "1580750.00", 1),
      v("collections", "140000.00", "119700.00", 2),
      v("purchases", "1310000.00", "1342000.00", 3),
      v("closing_balance", "455000.00", "427842.00", 4),
    ],
    accuracy: figure("fig-forecast-accuracy", "analysis.forecast_accuracy", "94.2", "percent", {
      formula_id: "analysis.forecast_accuracy",
      parameters: { snapshot: "2026-09-01", method: "1 - weighted absolute percentage error" },
    }),
  };
}

const SCENARIOS: Record<string, [number, number, string]> = {
  retime_supplier: [318000, 112000, "0.07"],
  take_loan: [296000, 141000, "0.03"],
  offer_discount: [271000, 61000, "0.19"],
  do_nothing: [265000, 18000, "0.41"],
};

export function scenarioComparison(decisions: string[]): ScenarioComparison {
  const chosen = decisions.filter((decision) => decision in SCENARIOS);
  const scenarios: Scenario[] = chosen.map((decision) => {
    const [expected, worst, breach] = SCENARIOS[decision] as [number, number, string];
    return {
      id: `sc-${decision}`,
      name_key: `decision.${decision}`,
      assumptions: { decision },
      expected_outcome: money(expected),
      worst_5pct_outcome: money(worst),
      p_buffer_breach: breach,
      paths: 1000,
      seed: 20261020,
    };
  });
  return { scenarios, recommended_id: chosen.includes("retime_supplier") ? "sc-retime_supplier" : (scenarios[0]?.id ?? "") };
}

export function stability(): StabilityReport {
  const report = todayRecommendation().stability;
  if (!report) throw new Error("today recommendation has no stability report");
  return report;
}
