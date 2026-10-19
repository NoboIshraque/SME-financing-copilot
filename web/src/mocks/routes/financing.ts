// Mock of the WP-06 financing router.
import type { FinancingNeed } from "../../api/contracts";
import { financingMatch, lenderProfiles } from "../fixtures/financing";
import { apiError, ok, type MockRoute } from "../http";

export const financingRoutes: MockRoute[] = [
  {
    method: "POST",
    pattern: "/api/financing/match",
    handler: (req) => {
      const need = req.body as FinancingNeed | undefined;
      if (!need?.amount?.amount || !/^\d+(\.\d+)?$/.test(need.amount.amount) || Number(need.amount.amount) <= 0) {
        return apiError(422, "invalid_need", "error.invalid_need");
      }
      return ok(financingMatch(need));
    },
  },
  {
    method: "GET",
    pattern: "/api/financing/lenders/:id",
    handler: (req) => {
      const lender = lenderProfiles().find((profile) => profile.lender_id === req.params.id);
      return lender ? ok(lender) : apiError(404, "not_found", "error.not_found");
    },
  },
];
