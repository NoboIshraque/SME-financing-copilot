// Mock of the WP-04 cash router.
import { alerts, cashForecast, gaps, whatIf } from "../fixtures/cash";
import { ok, type MockRoute } from "../http";

export const cashRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/cash/alerts", handler: () => ok(alerts()) },
  { method: "GET", pattern: "/api/cash/forecast", handler: () => ok(cashForecast()) },
  { method: "GET", pattern: "/api/cash/gaps", handler: () => ok(gaps()) },
  { method: "POST", pattern: "/api/cash/whatif", handler: (req) => ok(whatIf(req.body)) },
];
