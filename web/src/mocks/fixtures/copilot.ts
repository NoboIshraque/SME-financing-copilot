// Mock WP-10 output: today's recommendation for the grocery. The narrated text carries no
// numbers (CLAUDE.md rule 1): every figure is in `figures`, `claims` or on the action cards.
import type { Recommendation } from "../../api/contracts";
import { CARD_REMIND, CARD_RETIME, CARD_STANDBY } from "./cash";
import { NOW, TENANT } from "./common";

export function todayRecommendation(): Recommendation {
  return {
    id: "rec-today-2026-09-30",
    tenant_id: TENANT,
    question: "What should I do today?",
    answer_text:
      "Your likely balance dips below your buffer at the end of October, when salaries and the weekly supplier bill fall on the same day. Paying that supplier after salary day closes most of the gap, and a reminder to Customer 9 brings cash in sooner.",
    action_cards: [CARD_RETIME, CARD_REMIND, CARD_STANDBY],
    critic_objection:
      "Supplier 2 has refused new dates before. If they refuse again, the reminder alone covers only part of the gap, so line up standby financing too.",
    agreement: {
      question: "Which lever closes the end-of-October gap at the lowest cost?",
      votes: [
        { model: "gemini:flash", choice: "retime_payable" },
        { model: "groq:gpt-oss-120b", choice: "retime_payable" },
        { model: "groq:qwen", choice: "standby_facility" },
      ],
      winning_choice: "retime_payable",
      agreement_rate: "0.67",
      threshold: "0.67",
      stakes: "medium",
    },
    stability: {
      recommendation_id: "rec-today-2026-09-30",
      baseline_choice: "retime_payable",
      results: [
        { name: "sales_minus_10", kind: "stress", choice: "retime_payable", held: true },
        { name: "sales_minus_20", kind: "stress", choice: "standby_facility", held: false },
        { name: "late_payer", kind: "stress", choice: "retime_payable", held: true },
        { name: "inputs_plus_8", kind: "stress", choice: "retime_payable", held: true },
        { name: "rates_plus_2pp", kind: "stress", choice: "retime_payable", held: true },
        { name: "surprise_bill", kind: "stress", choice: "standby_facility", held: false },
        { name: "rows_shuffled", kind: "noise", choice: "retime_payable", held: true },
        { name: "parties_renamed", kind: "noise", choice: "retime_payable", held: true },
        { name: "question_reworded", kind: "noise", choice: "retime_payable", held: true },
        { name: "dates_shifted_format", kind: "noise", choice: "retime_payable", held: true },
      ],
      score: "0.8",
      what_would_flip: ["sales_minus_20", "surprise_bill"],
    },
    tools_used: ["cash.forecast", "cash.gaps", "cash.levers", "receivables.plan"],
    data_mode: "synthetic",
    created_at: NOW,
  };
}
