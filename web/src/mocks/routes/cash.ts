// Mock of the WP-04 cash router.
import { alerts, cashForecast } from "../fixtures/cash";
import { ok, type MockRoute } from "../http";

export const cashRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/cash/alerts", handler: () => ok(alerts()) },
  { method: "GET", pattern: "/api/cash/forecast", handler: () => ok(cashForecast()) },
];
