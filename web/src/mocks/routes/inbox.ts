// Mocks of the approval queue (WP-11), messaging (WP-12), reports and passport (WP-13), audit and
// trust (WP-11/16), and settings (WP-12).
import type { ActionCard, ShareGrant } from "../../api/contracts";
import type { PendingApproval, UserSettings } from "../../api/types";
import { callerRole, DEMO_TOTP_CODE } from "../db";
import { NOW, TENANT } from "../fixtures/common";
import { abstentions, auditDrill, auditEvents, auditVerification } from "../fixtures/inbox";
import { apiError, field, ok, type MockRoute } from "../http";
import { CARD_SOURCES } from "./actions";

function pendingCards(decided: Set<string>): ActionCard[] {
  const seen = new Map<string, ActionCard>();
  for (const source of CARD_SOURCES) {
    for (const card of source()) {
      if ((card.tier === "DRAFT" || card.tier === "EXECUTE") && !decided.has(card.id)) seen.set(card.id, card);
    }
  }
  return [...seen.values()];
}

export const inboxRoutes: MockRoute[] = [
  {
    method: "GET",
    pattern: "/api/approvals",
    handler: (_req, db) => {
      const decided = new Set(db.approvals.map((approval) => approval.action_card_id));
      const pending: PendingApproval[] = pendingCards(decided).map((card) => ({
        card,
        approval: {
          id: `pending-${card.id}`,
          tenant_id: TENANT,
          action_card_id: card.id,
          tier: card.tier,
          requested_by: "copilot",
          status: "pending",
          idempotency_key: `queue-${card.id}`,
          created_at: NOW,
          expires_at: "2026-10-01T18:00:00Z",
        },
      }));
      return ok(pending);
    },
  },
  { method: "GET", pattern: "/api/messages/drafts", handler: (_req, db) => ok(db.drafts) },
  {
    method: "POST",
    pattern: "/api/messages/:id/approve",
    handler: (req, db) => {
      const draft = db.drafts.find((candidate) => candidate.id === req.params.id);
      if (!draft) return apiError(404, "not_found", "error.not_found");
      if (!["owner", "accountant"].includes(callerRole(db))) return apiError(403, "forbidden", "error.forbidden");
      if (draft.status === "draft") draft.status = "approved";
      return ok(draft);
    },
  },
  {
    method: "POST",
    pattern: "/api/messages/:id/send",
    handler: (req, db) => {
      const draft = db.drafts.find((candidate) => candidate.id === req.params.id);
      if (!draft) return apiError(404, "not_found", "error.not_found");
      if (draft.status !== "approved" && draft.status !== "sent") return apiError(409, "not_approved", "error.not_approved");
      draft.status = "sent";
      return ok(draft);
    },
  },
  { method: "GET", pattern: "/api/reports/passport", handler: (_req, db) => ok(db.passports) },
  {
    method: "POST",
    pattern: "/api/reports/passport",
    handler: (_req, db) => {
      const latest = db.passports[0];
      if (!latest) return apiError(409, "no_evidence", "error.no_evidence");
      const next = { ...latest, id: `pp-grocery-${latest.version + 1}`, version: latest.version + 1, issued_at: NOW, anchor: null };
      db.passports.unshift(next);
      return ok(next);
    },
  },
  { method: "GET", pattern: "/api/reports/shares", handler: (_req, db) => ok(db.shares) },
  {
    method: "POST",
    pattern: "/api/reports/passport/:id/share",
    handler: (req, db) => {
      if (callerRole(db) !== "owner") return apiError(403, "owner_only", "error.owner_only");
      if (req.headers.get("X-Step-Up-Code") !== DEMO_TOTP_CODE) return apiError(403, "step_up_failed", "error.step_up_failed");
      const label = field(req.body, "lender_label").trim();
      const body = req.body as { scopes?: unknown; days?: unknown };
      const scopes = Array.isArray(body.scopes) ? body.scopes.map(String) : [];
      const days = typeof body.days === "number" ? body.days : 0;
      if (!label || scopes.length === 0 || days < 1 || days > 30) return apiError(422, "invalid_share", "error.invalid_share");
      const grant: ShareGrant = {
        id: `grant-${db.shares.length + 1}`,
        tenant_id: TENANT,
        passport_id: req.params.id ?? "",
        lender_label: label,
        scopes: scopes as [string, ...string[]],
        created_at: NOW,
        expires_at: new Date(Date.parse(NOW) + days * 86_400_000).toISOString(),
        revoked: false,
      };
      db.shares.push(grant);
      return ok(grant);
    },
  },
  {
    method: "POST",
    pattern: "/api/reports/shares/:id/revoke",
    handler: (req, db) => {
      const grant = db.shares.find((candidate) => candidate.id === req.params.id);
      if (!grant) return apiError(404, "not_found", "error.not_found");
      grant.revoked = true;
      return ok(grant);
    },
  },
  {
    method: "GET",
    pattern: "/api/verify/:id",
    handler: (req, db) => {
      const passport = db.passports.find((candidate) => candidate.id === req.params.id);
      if (!passport) return apiError(404, "passport_not_found", "error.passport_not_found");
      return ok({
        passport_id: passport.id,
        recomputed_digest: passport.digest,
        anchored_digest: passport.anchor?.digest ?? null,
        valid: passport.anchor?.digest === passport.digest,
        checked_on: "2026-10-01",
      });
    },
  },
  { method: "GET", pattern: "/api/audit/verify", handler: () => ok(auditVerification()) },
  { method: "GET", pattern: "/api/audit/events", handler: () => ok(auditEvents()) },
  { method: "GET", pattern: "/api/copilot/abstentions", handler: () => ok(abstentions()) },
  { method: "GET", pattern: "/api/trust/drill", handler: () => ok(auditDrill()) },
  { method: "GET", pattern: "/api/settings", handler: (_req, db) => ok(db.settings) },
  {
    method: "POST",
    pattern: "/api/settings",
    handler: (req, db) => {
      const next = req.body as Partial<UserSettings>;
      if (next.auto_send_reminders !== db.settings.auto_send_reminders && callerRole(db) !== "owner") {
        return apiError(403, "owner_only", "error.owner_only");
      }
      db.settings = { auto_send_reminders: Boolean(next.auto_send_reminders), email_alerts: Boolean(next.email_alerts) };
      return ok(db.settings);
    },
  },
];
