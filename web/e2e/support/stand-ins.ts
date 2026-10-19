// Stand-ins for backend answers a journey needs before their router lands. Local target only
// (hosted skips the journey instead); each use is annotated in the report, and the moment the
// real router answers, the real answer is used and the stand-in is never installed.
//
// GET /api/cash/alerts (WP-04): the offline mock's grocery story has a Warning-tier gap, while
// the journey "see a Critical alert -> approve a lever" needs FEATURES Q1's Critical tier (more
// than 20% chance within 7 days). This is the same gap, five days out. Synthetic (rule 8).
import { test, type Page } from "@playwright/test";

const money = (amount: string) => ({ amount, currency: "BDT" });

function figure(id: string, labelKey: string, value: string, unit: string, formulaId: string, inputs: string[] = []) {
  return {
    id,
    label_key: labelKey,
    value,
    unit,
    data_mode: "synthetic",
    provenance: { formula_id: formulaId, formula_version: 1, input_fact_ids: inputs, source_row_ids: [], parameters: { paths: "1000", seed: "20261020" } },
  };
}

export const CRITICAL_LEVER_ID = "e2e-lever-retime-supplier-2";

export function criticalAlert(tenantId: string) {
  return {
    id: "e2e-critical-gap-2026-10-05",
    tenant_id: tenantId,
    tier: "critical",
    title_key: "alert.payroll_at_risk",
    gap: {
      first_breach_day: "2026-10-05",
      lead_time_days: 5,
      probability: "0.41",
      expected_shortfall: money("64000.00"),
      worst_day: "2026-10-07",
      drivers: [
        { kind: "obligation", label_key: "driver.salary", amount: money("60000.00"), reference_id: `${tenantId}:OBL-2` },
        { kind: "bill_due", label_key: "driver.supplier_bill", amount: money("82618.00"), counterparty_token: "PARTY_efd9a5e9e9" },
      ],
      figures: [
        figure("e2e-fig-shortfall", "cash.expected_shortfall", "64000.00", "BDT", "cash.expected_shortfall"),
        figure("e2e-fig-probability", "cash.breach_probability", "0.41", "probability", "cash.p_below_buffer"),
      ],
    },
    indicators: ["payroll_or_emi_at_risk"],
    fixes: [
      {
        id: CRITICAL_LEVER_ID,
        title_key: "action.retime_payable",
        action_type: "retime_payable",
        tier: "EXECUTE",
        payload: { counterparty_label: "Supplier 2", due_date: "2026-10-06", new_date: "2026-10-16" },
        impact: figure("e2e-fig-lever-impact", "action.gap_reduced", "48500.00", "BDT", "cash.lever_gap_reduction", ["e2e-fig-shortfall"]),
        cost: figure("e2e-fig-lever-cost", "action.cost", "0.00", "BDT", "cash.lever_cost"),
      },
    ],
    dedupe_key: "gap:2026-10-05",
    created_at: "2026-09-30T18:00:00Z",
    data_mode: "synthetic",
  };
}

/** Answer GET /api/cash/alerts with the critical stand-in on this page. */
export async function standInCriticalAlert(page: Page, tenantId: string): Promise<void> {
  test.info().annotations.push({ type: "stand-in", description: "GET /api/cash/alerts: Critical gap (WP-04 router not landed)" });
  await page.route(/\/api\/cash\/alerts$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([criticalAlert(tenantId)]) }),
  );
}
