// Mock WP-05 output for the grocery. Invoices are the universe's open baki entries as of
// 30 Sep 2026 (data/synthetic/universe/sme_grocery/baki_register.csv); labels are party tokens'
// neutral display labels.
import type { ActionCard, Invoice } from "../../api/contracts";
import type { AgingBucket, CustomerCredit, ReceivableRow, ReceivablesOverview } from "../../api/types";
import { CARD_REMIND } from "./cash";
import { AS_OF, TENANT, figure, money } from "./common";

const CUSTOMERS: Record<string, string> = {
  PARTY_9e932d2298: "Customer 10",
  PARTY_9ad3f2ee60: "Customer 9",
  PARTY_1a3dca5e9e: "Customer 2",
  PARTY_13b4d8cd46: "Customer 1",
  PARTY_f61f03321e: "Customer 11",
};

// [number, party, issue, due, amount, days overdue, bucket by invoice age, risk, factor keys]
const ROWS: Array<[string, string, string, string, number, number, AgingBucket, string, string[]]> = [
  ["00786", "PARTY_9e932d2298", "2026-08-27", "2026-09-11", 3601, 19, "31_60", "78", ["risk.days_late", "risk.history_slow", "risk.amount_above_usual"]],
  ["00796", "PARTY_9e932d2298", "2026-09-03", "2026-09-18", 1340, 12, "0_30", "71", ["risk.days_late", "risk.history_slow"]],
  ["00801", "PARTY_9ad3f2ee60", "2026-09-06", "2026-09-21", 2605, 9, "0_30", "64", ["risk.many_open", "risk.days_late"]],
  ["00802", "PARTY_9e932d2298", "2026-09-06", "2026-09-21", 863, 9, "0_30", "62", ["risk.history_slow"]],
  ["00806", "PARTY_9ad3f2ee60", "2026-09-08", "2026-09-23", 1115, 7, "0_30", "58", ["risk.many_open"]],
  ["00812", "PARTY_1a3dca5e9e", "2026-09-11", "2026-09-26", 1014, 4, "0_30", "31", ["risk.days_late"]],
  ["00813", "PARTY_9ad3f2ee60", "2026-09-12", "2026-09-27", 2609, 3, "0_30", "55", ["risk.many_open", "risk.amount_above_usual"]],
  ["00815", "PARTY_13b4d8cd46", "2026-09-13", "2026-09-28", 516, 2, "0_30", "18", ["risk.recent_payment"]],
  ["00817", "PARTY_9ad3f2ee60", "2026-09-14", "2026-09-29", 1879, 1, "0_30", "49", ["risk.many_open"]],
  ["00818", "PARTY_9ad3f2ee60", "2026-09-15", "2026-09-30", 697, 0, "0_30", "41", ["risk.many_open"]],
  ["00819", "PARTY_9e932d2298", "2026-09-16", "2026-10-01", 2709, 0, "0_30", "60", ["risk.history_slow"]],
  ["00820", "PARTY_f61f03321e", "2026-09-17", "2026-10-02", 2911, 0, "0_30", "22", ["risk.recent_payment"]],
];

function invoice(number: string, party: string, issue: string, due: string, amount: number, disputed: boolean): Invoice {
  return {
    id: `${TENANT}:GRO-INV-${number}`,
    tenant_id: TENANT,
    counterparty_token: party,
    issue_date: issue,
    due_date: due,
    amount: money(amount),
    amount_paid: money(0),
    status: disputed ? "disputed" : "open",
    source_ref: `baki_register.csv#INV-${number}`,
    data_mode: "synthetic",
  };
}

export function receivableRows(disputes: Record<string, string>): ReceivableRow[] {
  return ROWS.map(([number, party, issue, due, amount, overdue, bucket, risk, factors]) => {
    const id = `${TENANT}:GRO-INV-${number}`;
    const reason = disputes[id];
    return {
      invoice: invoice(number, party, issue, due, amount, reason !== undefined),
      counterparty_label: CUSTOMERS[party] ?? "Customer",
      days_overdue: overdue,
      bucket,
      risk_score: risk,
      risk_factor_keys: reason !== undefined ? ["risk.disputed", ...factors].slice(0, 3) : factors,
      disputed: reason !== undefined,
      dispute_reason: reason ?? null,
    };
  });
}

const CREDIT: Array<[string, number, string, number, boolean]> = [
  ["PARTY_9ad3f2ee60", 8905, "9.2", 8000, true],
  ["PARTY_9e932d2298", 8513, "14.5", 10000, false],
  ["PARTY_f61f03321e", 2911, "1.0", 6000, false],
  ["PARTY_1a3dca5e9e", 1014, "2.4", 6000, false],
  ["PARTY_13b4d8cd46", 516, "3.1", 5000, false],
];

export function receivablesOverview(disputes: Record<string, string>): ReceivablesOverview {
  const invoices = receivableRows(disputes);
  const buckets: AgingBucket[] = ["0_30", "31_60", "61_90", "90_plus"];
  const customers: CustomerCredit[] = CREDIT.map(([token, open, late, limit, stop]) => ({
    counterparty_token: token,
    counterparty_label: CUSTOMERS[token] ?? "Customer",
    open: money(open),
    avg_days_late: late,
    credit_limit: figure(`fig-limit-${token}`, "receivables.credit_limit", `${limit}.00`, "BDT", {
      formula_id: "receivables.credit_limit",
      parameters: { policy_cap: "10000.00" },
    }),
    stop_credit: stop,
  }));
  return {
    as_of: AS_OF,
    figures: [
      figure("fig-rcv-open", "receivables.open", "21859.00", "BDT", {
        formula_id: "receivables.open",
        source_row_ids: invoices.map((row) => row.invoice.source_ref),
      }),
      figure("fig-rcv-overdue", "receivables.overdue", "15542.00", "BDT", { formula_id: "receivables.overdue_sum" }),
      figure("fig-rcv-dso", "receivables.dso", "11.2", "days", {
        formula_id: "receivables.dso",
        input_fact_ids: ["fact-receivables-2026-09", "fact-net-sales-2026-09"],
      }),
    ],
    aging: buckets.map((bucket) => {
      const inBucket = invoices.filter((row) => row.bucket === bucket);
      return { bucket, count: inBucket.length, amount: money(inBucket.reduce((sum, row) => sum + Number(row.invoice.amount.amount), 0)) };
    }),
    invoices,
    customers,
  };
}

export const CARD_REMIND_10: ActionCard = {
  id: "act-remind-customer-10",
  title_key: "action.send_reminder",
  action_type: "send_reminder",
  tier: "DRAFT",
  payload: { counterparty_label: "Customer 10", due_date: "2026-09-11", invoice_count: "3" },
  impact: figure("fig-act-remind10-impact", "action.expected_collection", "5804.00", "BDT", { formula_id: "receivables.overdue_sum" }),
};

export const CARD_PREDUE_11: ActionCard = {
  id: "act-predue-customer-11",
  title_key: "action.send_pre_due_reminder",
  action_type: "send_reminder",
  tier: "DRAFT",
  payload: { counterparty_label: "Customer 11", due_date: "2026-10-02", invoice_count: "1", draft_id: "msg-predue-11" },
  impact: figure("fig-act-predue11-impact", "action.expected_collection", "2911.00", "BDT", { formula_id: "receivables.open_sum" }),
};

export function reminderPlan(): ActionCard[] {
  return [CARD_REMIND, CARD_REMIND_10, CARD_PREDUE_11];
}
