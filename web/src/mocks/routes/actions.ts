// Mock of WP-11's approvals API (backend/app/api/auth.py): EXECUTE cards only, requested with an
// idempotency key, approved by the owner with a step-up code, then executed (record only).
import type { ActionCard, Approval } from "../../api/contracts";
import type { ApprovalView } from "../../api/types";
import { callerRole, DEMO_TOTP_CODE, type ApprovalRecord, type MockDb } from "../db";
import { NOW, TENANT } from "../fixtures/common";
import { apiError, ok, type MockResult, type MockRoute } from "../http";

function view(record: ApprovalRecord, replayed = false): ApprovalView {
  return { approval: record.approval, action_type: record.card.action_type, card: record.card, result: record.result ?? null, replayed };
}

function find(db: MockDb, id: string | undefined): ApprovalRecord | undefined {
  return db.approvals.find((record) => record.approval.id === id);
}

function conflict(record: ApprovalRecord): MockResult {
  return apiError(409, `approval_${record.approval.status}`, `error.approval_${record.approval.status}`);
}

export const actionRoutes: MockRoute[] = [
  {
    method: "POST",
    pattern: "/api/approvals",
    handler: (req, db) => {
      const key = req.headers.get("X-Idempotency-Key");
      if (!key) return apiError(400, "idempotency_key_required", "error.idempotency_key_required");
      const replay = db.approvals.find((record) => record.approval.idempotency_key === key);
      if (replay) return ok(view(replay, true));
      const card = (req.body as { card?: ActionCard } | undefined)?.card;
      if (!card) return apiError(422, "invalid_card", "error.invalid_card");
      if (card.tier === "DENY") return apiError(403, "action_denied", "error.action_denied");
      if (card.tier !== "EXECUTE") return apiError(422, "approval_not_needed", "error.approval_not_needed");
      if (!["owner", "accountant"].includes(callerRole(db))) return apiError(403, "forbidden", "error.forbidden");
      const pending = db.approvals.find((record) => record.card.id === card.id && record.approval.status === "pending");
      if (pending) return ok(view(pending, true));
      const approval: Approval = {
        id: `ap-${db.approvals.length + 1}`,
        tenant_id: db.session?.principal.tenant_id ?? TENANT,
        action_card_id: card.id,
        tier: "EXECUTE",
        requested_by: db.session?.principal.user_id ?? "u-owner",
        status: "pending",
        step_up_verified: false,
        idempotency_key: key,
        created_at: NOW,
        expires_at: "2026-10-01T18:00:00Z",
      };
      const record: ApprovalRecord = { approval, card };
      db.approvals.push(record);
      return { status: 201, body: view(record) };
    },
  },
  {
    method: "GET",
    pattern: "/api/approvals",
    handler: (req, db) => {
      const status = req.query.get("status");
      return ok(db.approvals.filter((record) => !status || record.approval.status === status).map((record) => view(record)));
    },
  },
  {
    method: "POST",
    pattern: "/api/approvals/:id/approve",
    handler: (req, db) => {
      if (callerRole(db) !== "owner") return apiError(403, "forbidden", "error.forbidden");
      const code = req.headers.get("X-Step-Up-Code");
      if (!code) return apiError(401, "step_up_required", "error.step_up_required");
      if (code !== DEMO_TOTP_CODE) return apiError(401, "invalid_step_up", "error.invalid_step_up");
      const record = find(db, req.params.id);
      if (!record) return apiError(404, "not_found", "error.not_found");
      if (record.approval.status !== "pending") return conflict(record);
      record.approval = { ...record.approval, status: "approved", decided_by: db.session?.principal.user_id ?? "u-owner", step_up_verified: true };
      return ok(view(record));
    },
  },
  {
    method: "POST",
    pattern: "/api/approvals/:id/execute",
    handler: (req, db) => {
      const key = req.headers.get("X-Idempotency-Key");
      if (!key) return apiError(400, "idempotency_key_required", "error.idempotency_key_required");
      const record = find(db, req.params.id);
      if (!record) return apiError(404, "not_found", "error.not_found");
      if (record.approval.status === "executed") return ok(view(record, true));
      if (record.approval.status !== "approved") return conflict(record);
      record.approval = { ...record.approval, status: "executed" };
      record.result = { status: "recorded", action_type: record.card.action_type, note: "no external system is connected; the approved action is recorded only" };
      return ok(view(record));
    },
  },
];
