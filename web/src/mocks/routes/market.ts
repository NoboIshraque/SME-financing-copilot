// Mock of the WP-09 market router.
import type { NegotiationRequest } from "../../api/types";
import { marketAlerts, negotiationPlan, vendorRanking, watchlist } from "../fixtures/market";
import { apiError, field, ok, type MockRoute } from "../http";

export const marketRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/market/prices", handler: () => ok(watchlist()) },
  { method: "GET", pattern: "/api/market/alerts", handler: () => ok(marketAlerts()) },
  {
    method: "POST",
    pattern: "/api/market/vendors/rank",
    handler: (req) => {
      if (!/^\d+(\.\d+)?$/.test(field(req.body, "quantity"))) return apiError(422, "invalid_quantity", "error.invalid_quantity");
      return ok(vendorRanking(field(req.body, "commodity")));
    },
  },
  { method: "POST", pattern: "/api/market/negotiate", handler: (req) => ok(negotiationPlan(req.body as NegotiationRequest)) },
];
