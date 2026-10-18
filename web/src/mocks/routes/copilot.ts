// Mock of the WP-10 copilot router.
import { todayRecommendation } from "../fixtures/copilot";
import { ok, type MockRoute } from "../http";

export const copilotRoutes: MockRoute[] = [
  { method: "GET", pattern: "/api/copilot/today", handler: () => ok(todayRecommendation()) },
];
