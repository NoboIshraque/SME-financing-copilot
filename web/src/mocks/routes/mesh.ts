// Mock of the WP-08 mesh router: graph, rounds, EXECUTE approval with step-up, verification.
import { callerRole, DEMO_TOTP_CODE } from "../db";
import { initialRounds, meshGraph } from "../fixtures/mesh";
import { apiError, ok, type MockRoute } from "../http";

export const meshRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/mesh/obligations", handler: (_req, db) => ok(meshGraph(db.session?.principal.tenant_id ?? "sme_garment")) },
  {
    method: "GET",
    pattern: "/api/mesh/rounds",
    handler: (_req, db) => {
      const tenant = db.session?.principal.tenant_id ?? "sme_garment";
      return ok(db.rounds.filter((round) => round.participants.includes(tenant)));
    },
  },
  {
    method: "POST",
    pattern: "/api/mesh/rounds/propose",
    handler: (_req, db) => {
      const tenant = db.session?.principal.tenant_id ?? "sme_garment";
      const open = db.rounds.find((round) => round.status === "proposed" && round.participants.includes(tenant));
      if (open) return ok(open);
      // Like the API: a ring member gets a fresh round over the open debts, approved by nobody yet.
      const template = initialRounds().find((round) => round.status === "proposed" && round.participants.includes(tenant));
      if (!template) return apiError(409, "nothing_to_net", "error.nothing_to_net");
      const fresh = { ...template, id: `${template.id}-new`, approvals: {} };
      db.rounds.push(fresh);
      return ok(fresh);
    },
  },
  {
    method: "POST",
    pattern: "/api/mesh/rounds/:id/approve",
    handler: (req, db) => {
      const round = db.rounds.find((candidate) => candidate.id === req.params.id);
      const tenant = db.session?.principal.tenant_id ?? "sme_garment";
      if (!round) return apiError(404, "not_found", "error.not_found");
      if (!round.participants.includes(tenant)) return apiError(403, "not_a_participant", "error.not_a_participant");
      if (callerRole(db) !== "owner") return apiError(403, "owner_only", "error.owner_only");
      if (req.headers.get("X-Step-Up-Code") !== DEMO_TOTP_CODE) return apiError(403, "step_up_failed", "error.step_up_failed");
      round.approvals = { ...round.approvals, [tenant]: true };
      return ok(round);
    },
  },
  {
    method: "GET",
    pattern: "/api/mesh/rounds/:id/verify",
    handler: (req, db) => {
      const round = db.rounds.find((candidate) => candidate.id === req.params.id);
      if (!round?.anchor) return apiError(404, "not_anchored", "error.not_anchored");
      return ok({ round_id: round.id, valid: true, recomputed_digest: round.anchor.digest, anchor: round.anchor });
    },
  },
];
