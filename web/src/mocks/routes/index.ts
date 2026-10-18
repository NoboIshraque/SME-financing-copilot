// Every mock route, one module per backend router.
import type { MockRoute } from "../http";
import { actionRoutes } from "./actions";
import { analysisRoutes } from "./analysis";
import { authRoutes } from "./auth";
import { cashRoutes } from "./cash";
import { copilotRoutes } from "./copilot";
import { financingRoutes } from "./financing";
import { inboxRoutes } from "./inbox";
import { marketRoutes } from "./market";
import { meshRoutes } from "./mesh";
import { receivablesRoutes } from "./receivables";

export const ROUTES: MockRoute[] = [...authRoutes, ...cashRoutes, ...copilotRoutes, ...actionRoutes, ...receivablesRoutes, ...financingRoutes, ...analysisRoutes, ...meshRoutes, ...marketRoutes, ...inboxRoutes];
