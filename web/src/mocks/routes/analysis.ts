// Mock of the WP-07 analysis router.
import { COMPARISON_PREFIX, ratios, scenarioComparison, stability, statements, variance } from "../fixtures/analysis";
import { apiError, field, ok, type MockRoute } from "../http";

export const analysisRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/analysis/statements", handler: () => ok(statements()) },
  { method: "GET", pattern: "/api/analysis/ratios", handler: () => ok(ratios()) },
  { method: "GET", pattern: "/api/analysis/variance", handler: () => ok(variance()) },
  {
    method: "POST",
    pattern: "/api/analysis/scenarios",
    handler: (req) => {
      const decisions = (req.body as { decisions?: unknown } | undefined)?.decisions;
      return ok(scenarioComparison(Array.isArray(decisions) ? decisions.map(String) : []));
    },
  },
  {
    method: "POST",
    pattern: "/api/analysis/stability",
    handler: (req) =>
      field(req.body, "recommendation_id").startsWith(COMPARISON_PREFIX)
        ? ok(stability())
        : apiError(404, "not_found", "analysis.unknown_recommendation"),
  },
];
