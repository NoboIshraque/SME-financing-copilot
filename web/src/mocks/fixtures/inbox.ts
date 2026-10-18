// Mock WP-11/12/13/16 data: approval queue, message drafts, Trust Passport, audit chain,
// abstention log and audit drill. All synthetic.
import type { AuditEvent, MessageDraft, PassportVersion, ShareGrant } from "../../api/contracts";
import type { AbstentionLogEntry, AuditDrill, AuditVerification, UserSettings } from "../../api/types";
import { NOW, TENANT, figure } from "./common";

export function initialDrafts(): MessageDraft[] {
  const base = { tenant_id: TENANT, created_at: NOW, data_mode: "synthetic" as const, tier: "DRAFT" as const };
  return [
    {
      ...base,
      id: "msg-predue-11",
      template_id: "pre_due_reminder.v1",
      purpose: "pre_due_reminder",
      language: "bn",
      channel: "copy",
      recipient_token: "PARTY_f61f03321e",
      variables: { recipient_label: "Customer 11", amount: "2911.00", due_date: "2026-10-02" },
      body: "প্রিয় Customer 11, আপনার ৳২,৯১১ বাকি ২ অক্টোবর পরিশোধের কথা। বিকাশে পরিশোধের লিংক: [payment link]। ধন্যবাদ — মিরপুর মুদি স্টোর",
      status: "draft",
    },
    {
      ...base,
      id: "msg-overdue-9",
      template_id: "overdue_reminder.v1",
      purpose: "overdue_reminder",
      language: "en",
      channel: "email",
      recipient_token: "PARTY_9ad3f2ee60",
      variables: { recipient_label: "Customer 9", amount: "8208.00", invoice_count: "4" },
      body: "Dear Customer 9, 4 invoices totalling Tk 8,208 are now overdue. Please pay by bKash using this link: [payment link]. Thank you, Mirpur Mudi Store.",
      status: "draft",
    },
    {
      ...base,
      id: "msg-supplier-2",
      template_id: "supplier_term_extension.v1",
      purpose: "supplier_term_extension",
      language: "en",
      channel: "copy",
      recipient_token: "PARTY_efd9a5e9e9",
      variables: { recipient_label: "Supplier 2", new_date: "2026-11-10" },
      body: "Dear Supplier 2, could we pay the bill due on 31 October on 10 November instead, within our usual terms? Thank you, Mirpur Mudi Store.",
      status: "approved",
    },
  ];
}

export function initialPassports(): PassportVersion[] {
  return [
    {
      id: "pp-grocery-2",
      tenant_id: TENANT,
      version: 2,
      issued_at: "2026-09-30T12:00:00Z",
      digest: "3c9e1a7b5d2f4e6081a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f7a8",
      evidence: [
        { kind: "mobile_money_statement", digest: "a1".repeat(32), verified: true, period: { start: "2026-04-01", end: "2026-09-30" } },
        { kind: "bank_statement", digest: "b2".repeat(32), verified: true, period: { start: "2026-04-01", end: "2026-09-30" } },
        { kind: "trade_licence", digest: "c3".repeat(32), verified: true },
        { kind: "etin", digest: "d4".repeat(32), verified: false },
      ],
      attestations_confirmed: 12,
      attestations_disputed: 1,
      abstention_rate: "0.06",
      audit_drill_catch_rate: "0.9",
      anchor: { chain: "sepolia", digest: "3c9e1a7b5d2f4e6081a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f7a8", tx_hash: "0x8d2a4c6e8f0a1b3c5d7e9f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c", block_number: 6612345, explorer_url: null, anchored_at: "2026-09-30T12:05:00Z" },
      data_mode: "synthetic",
    },
    {
      id: "pp-grocery-1",
      tenant_id: TENANT,
      version: 1,
      issued_at: "2026-06-30T12:00:00Z",
      digest: "7a".repeat(32),
      evidence: [{ kind: "mobile_money_statement", digest: "e5".repeat(32), verified: true }],
      attestations_confirmed: 7,
      attestations_disputed: 0,
      abstention_rate: null,
      audit_drill_catch_rate: null,
      anchor: null,
      data_mode: "synthetic",
    },
  ];
}

export function initialShares(): ShareGrant[] {
  return [
    { id: "grant-1", tenant_id: TENANT, passport_id: "pp-grocery-2", lender_label: "Lender 1 (demo)", scopes: ["passport:read"], created_at: NOW, expires_at: "2026-10-25T18:00:00Z", revoked: false },
  ];
}

export function auditVerification(): AuditVerification {
  return {
    valid: true,
    length: 1284,
    head_hash: "f0e1d2c3b4a5968778695a4b3c2d1e0f1a2b3c4d5e6f708192a3b4c5d6e7f809",
    anchor: { chain: "sepolia", digest: "f0e1d2c3b4a5968778695a4b3c2d1e0f1a2b3c4d5e6f708192a3b4c5d6e7f809", tx_hash: "0x2b4d6f8a0c1e3a5c7e9a1c3e5a7c9e1a3c5e7a9c1e3a5c7e9a1c3e5a7c9e1a3c", block_number: 6612400, explorer_url: null, anchored_at: "2026-09-30T23:59:00Z" },
    broken_at_seq: null,
  };
}

export function auditEvents(): AuditEvent[] {
  const event = (seq: number, at: string, actor: string, action: string, tier: AuditEvent["tier"], target: string | null): AuditEvent => ({
    seq, at, actor, action, tier, target, tenant_id: TENANT,
    details_digest: `${seq}`.padStart(64, "a"), prev_hash: `${seq - 1}`.padStart(64, "0"), hash: `${seq}`.padStart(64, "f"),
  });
  return [
    event(1284, "2026-09-30T17:58:00Z", "u-owner", "approve", "EXECUTE", "act-retime-supplier-2"),
    event(1283, "2026-09-30T17:40:00Z", "copilot", "quarantine_input", "DENY", "chat-msg-77"),
    event(1282, "2026-09-30T17:31:00Z", "u-accountant", "approve", "DRAFT", "msg-overdue-9"),
    event(1281, "2026-09-30T16:02:00Z", "copilot", "abstain", "SUGGEST", "rec-loan-size"),
    event(1280, "2026-09-30T15:44:00Z", "u-owner", "share_passport", "EXECUTE", "grant-1"),
  ];
}

export function abstentions(): AbstentionLogEntry[] {
  return [
    {
      id: "ab-1",
      at: "2026-09-30T16:02:00Z",
      question: "How big a loan can I safely take for Eid stock?",
      abstention: { reason: "insufficient_data", message_key: "abstain.insufficient_data", missing: ["last year's Eid-ul-Adha sales (only 5 months of history)"] },
    },
    {
      id: "ab-2",
      at: "2026-09-28T11:20:00Z",
      question: "Which supplier should I drop?",
      abstention: { reason: "low_agreement", message_key: "abstain.low_agreement", missing: [] },
    },
  ];
}

export function auditDrill(): AuditDrill {
  return {
    run_at: "2026-09-30T02:00:00Z",
    planted: 20,
    caught: 18,
    catch_rate: figure("fig-drill-rate", "trust.drill_catch_rate", "0.9", "probability", {
      formula_id: "trust.audit_drill_catch_rate",
      parameters: { planted: "20", caught: "18", ledger: "sandbox copy" },
    }),
  };
}

export const DEFAULT_SETTINGS: UserSettings = { auto_send_reminders: false, email_alerts: true };
