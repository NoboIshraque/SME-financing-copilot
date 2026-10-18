// Mock of the WP-11 approval endpoint: tiers, owner-only EXECUTE with step-up, idempotency.
import type { ActionCard, Approval, Role, Tier } from "../../api/contracts";
import { callerRole, DEMO_TOTP_CODE } from "../db";
import { alerts } from "../fixtures/cash";
import { NOW, TENANT } from "../fixtures/common";
import { todayRecommendation } from "../fixtures/copilot";
import { CARD_APPLY } from "../fixtures/financing";
import { reminderPlan } from "../fixtures/receivables";
import { apiError, ok, type MockRoute } from "../http";

/** Every action card any mock screen shows; screens added later register theirs here. */
export const CARD_SOURCES: Array<() => readonly ActionCard[]> = [
  () => todayRecommendation().action_cards ?? [],
  () => alerts().flatMap((alert) => alert.fixes ?? []),
  reminderPlan,
  () => [CARD_APPLY],
];

const MAY_APPROVE: Record<Exclude<Tier, "READ" | "DENY">, readonly Role[]> = {
  SUGGEST: ["owner", "accountant", "staff"],
  DRAFT: ["owner", "accountant"],
  EXECUTE: ["owner"],
};

function findCard(id: string): ActionCard | undefined {
  for (const source of CARD_SOURCES) {
    const card = source().find((candidate) => candidate.id === id);
    if (card) return card;
  }
  return undefined;
}

export const actionRoutes: MockRoute[] = [
  {
    method: "POST",
    pattern: "/api/actions/:id/approve",
    handler: (req, db) => {
      const card = findCard(req.params.id ?? "");
      if (!card) return apiError(404, "not_found", "error.not_found");
      const key = req.headers.get("X-Idempotency-Key");
      if (!key) return apiError(400, "idempotency_required", "error.idempotency_required");
      const replay = db.approvals.find((approval) => approval.idempotency_key === key);
      if (replay) return ok(replay);
      if (card.tier === "DENY") return apiError(403, "action_denied", "error.action_denied");
      if (card.tier === "READ") return apiError(409, "nothing_to_approve", "error.nothing_to_approve");
      if (db.approvals.some((approval) => approval.action_card_id === card.id)) {
        return apiError(409, "already_decided", "error.already_decided");
      }
      const role = callerRole(db);
      if (!MAY_APPROVE[card.tier].includes(role)) {
        return card.tier === "EXECUTE"
          ? apiError(403, "owner_only", "error.owner_only")
          : apiError(403, "forbidden", "error.forbidden");
      }
      if (card.tier === "EXECUTE" && req.headers.get("X-Step-Up-Code") !== DEMO_TOTP_CODE) {
        return apiError(403, "step_up_failed", "error.step_up_failed");
      }
      const approval: Approval = {
        id: `ap-${db.approvals.length + 1}`,
        tenant_id: db.session?.principal.tenant_id ?? TENANT,
        action_card_id: card.id,
        tier: card.tier,
        requested_by: "copilot",
        decided_by: db.session?.principal.user_id ?? "u-owner",
        status: "approved",
        step_up_verified: card.tier === "EXECUTE",
        idempotency_key: key,
        created_at: NOW,
        expires_at: "2026-10-01T18:00:00Z",
      };
      db.approvals.push(approval);
      return ok(approval);
    },
  },
];
