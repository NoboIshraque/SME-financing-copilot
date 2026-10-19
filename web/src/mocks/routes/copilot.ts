// Mock of the WP-10 copilot router and the WP-02 ingest router. Canned answers by intent; the
// injection guard (WP-11) quarantines instructions that try to override the rules.
import type { IngestPreview, Recommendation } from "../../api/contracts";
import { CARD_REMIND } from "../fixtures/cash";
import { NOW, TENANT, figure, money } from "../fixtures/common";
import { todayRecommendation } from "../fixtures/copilot";
import { CARD_REMIND_10 } from "../fixtures/receivables";
import { apiError, field, ok, type MockRoute } from "../http";

const INJECTION = /ignore (all |the )?(previous|prior) instructions|disregard your rules|skip the code|পূর্বের সব নির্দেশ|নির্দেশ উপেক্ষা|忽略(之前|以上)的?(所有)?指令/i;
const SALARY = /salar|payroll|বেতন|工资/i;
const LOAN_SIZE = /(how (big|much)|কত বড়|কত টাকার|多少|多大).*(loan|ঋণ|贷款)|(loan|ঋণ|贷款).*(how (big|much)|কত|多少)/i;

function base(question: string): Recommendation {
  return { id: `rec-${question.length}-${question.charCodeAt(0)}`, tenant_id: TENANT, question, created_at: NOW, data_mode: "synthetic" };
}

function answer(question: string): Recommendation {
  if (SALARY.test(question)) return { ...todayRecommendation(), id: "rec-ask-salary", question };
  if (LOAN_SIZE.test(question)) {
    return {
      ...base(question),
      abstention: {
        reason: "insufficient_data",
        message_key: "abstain.insufficient_data",
        missing: ["last year's Eid-ul-Adha sales (only 5 months of history)", "the stock you plan to buy and its supplier quotes"],
      },
      tools_used: ["cash.forecast", "financing.match"],
    };
  }
  const overdue = figure("fig-ask-overdue-10", "receivables.overdue", "5804.00", "BDT", { formula_id: "receivables.overdue_sum", source_row_ids: ["baki_register.csv#INV-00786", "baki_register.csv#INV-00796", "baki_register.csv#INV-00802"] });
  return {
    ...base(question),
    answer_text: "Chase Customer 10 first: they owe the most overdue money and usually pay slowly. Customer 9 comes next.",
    figures: [overdue],
    claims: [
      { id: "claim-ask-1", text: "Customer 10 has Tk 5,804 overdue across 3 invoices.", value: "5804.00", unit: "BDT", formula_id: "receivables.overdue_sum", input_fact_ids: ["fact-rcv-customer-10"] },
      { id: "claim-ask-2", text: "Customer 10 pays 14.5 days late on average.", value: "14.5", unit: "days", formula_id: "receivables.avg_days_late", input_fact_ids: ["fact-late-customer-10"] },
    ],
    checks: [
      { claim_id: "claim-ask-1", status: "verified", recomputed_value: "5804.00" },
      { claim_id: "claim-ask-2", status: "verified", recomputed_value: "14.5" },
    ],
    action_cards: [CARD_REMIND_10, CARD_REMIND],
    critic_objection: "Customer 10 is a regular buyer; a firm reminder could cost you their weekly orders. Keep the tone friendly.",
    agreement: {
      question: "Which customer should be chased first?",
      votes: [
        { model: "gemini:flash", choice: "customer_10" },
        { model: "groq:gpt-oss-120b", choice: "customer_10" },
        { model: "groq:qwen", choice: "customer_10" },
      ],
      winning_choice: "customer_10",
      agreement_rate: "1",
      threshold: "0.67",
      stakes: "low",
    },
    tools_used: ["receivables.plan"],
  };
}

function preview(name: string): IngestPreview {
  const photo = /\.(jpe?g|png|heic|webp)$/i.test(name);
  if (photo) {
    const draftInvoice = (row: string, amount: number, party: string) => ({
      id: `${TENANT}:OCR-${row}`, tenant_id: TENANT, counterparty_token: party, issue_date: "2026-09-29", due_date: "2026-10-14",
      amount: money(amount), amount_paid: money(0), status: "open" as const, source_ref: `${name}#${row}`, data_mode: "synthetic" as const,
    });
    return {
      preview_id: "pv-photo-1", tenant_id: TENANT, source_format: "ledger_photo", file_digest: "c".repeat(64), data_mode: "synthetic",
      drafts: [
        { row_ref: "line1", confidence: "0.92", flagged: false, invoice: draftInvoice("line1", 1250, "PARTY_13b4d8cd46") },
        { row_ref: "line2", confidence: "0.88", flagged: false, invoice: draftInvoice("line2", 640, "PARTY_1a3dca5e9e") },
        { row_ref: "line3", confidence: "0.62", flagged: true, invoice: draftInvoice("line3", 3100, "PARTY_48b57fb1d4") },
      ],
    };
  }
  const tx = (n: number, amount: number) => ({
    id: `${TENANT}-UP${n}`, tenant_id: TENANT, occurred_at: `2026-10-0${n}T10:00:00+06:00`, amount: money(amount), direction: "inflow" as const,
    channel: "bkash" as const, category: "sales" as const, source_ref: `${name}#L${n + 1}`, data_mode: "synthetic" as const,
  });
  return {
    preview_id: "pv-csv-1", tenant_id: TENANT, source_format: "bkash_statement", file_digest: "b".repeat(64), data_mode: "synthetic",
    transactions: [tx(1, 2479), tx(2, 922), tx(3, 1647)],
    duplicates_skipped: 1,
    unparsed: [{ row_ref: `${name}#L19`, reason_key: "ingest.bad_date", raw_excerpt: "31/02/2026 ..." }],
  };
}

export const copilotRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/copilot/today", handler: () => ok(todayRecommendation()) },
  {
    method: "POST",
    pattern: "/api/copilot/ask",
    handler: (req) => {
      const question = field(req.body, "question").trim();
      if (!question) return apiError(422, "empty_question", "error.empty_question");
      if (INJECTION.test(question)) return apiError(422, "input_quarantined", "error.input_quarantined");
      return ok(answer(question));
    },
  },
  {
    method: "POST",
    pattern: "/api/ingest/preview",
    handler: (req) => {
      const file = req.body instanceof FormData ? req.body.get("file") : null;
      if (!(file instanceof File)) return apiError(422, "no_file", "error.no_file");
      return ok(preview(file.name));
    },
  },
  {
    method: "POST",
    pattern: "/api/ingest/commit",
    handler: (req) => {
      const body = req.body as { tenant_id?: string; preview_id?: string; file_digest?: string; confirm?: unknown };
      if (!body.tenant_id) return apiError(422, "tenant_required", "error.tenant_required");
      if (!body.preview_id || !/^[0-9a-f]{64}$/.test(body.file_digest ?? "")) return apiError(422, "digest_mismatch", "error.digest_mismatch");
      const csv = body.preview_id === "pv-csv-1";
      return ok({
        preview_id: body.preview_id,
        transactions: csv ? 3 : 0,
        invoices: 0,
        bills: 0,
        drafts_confirmed: Array.isArray(body.confirm) ? body.confirm.length : 0,
        duplicates_skipped: csv ? 1 : 0,
        committed_at: NOW,
      });
    },
  },
];
