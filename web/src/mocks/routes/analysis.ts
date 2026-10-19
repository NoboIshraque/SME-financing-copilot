// Mock of the WP-07 analysis router.
import { ratios, scenarioComparison, stability, statements, variance } from "../fixtures/analysis";
import { ok, type MockRoute } from "../http";

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
  { method: "POST", pattern: "/api/analysis/stability", handler: () => ok(stability()) },
];
