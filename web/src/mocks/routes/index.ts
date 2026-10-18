// Every mock route, one module per backend router.
import type { MockRoute } from "../http";
import { actionRoutes } from "./actions";
import { authRoutes } from "./auth";
import { cashRoutes } from "./cash";
import { copilotRoutes } from "./copilot";
import { receivablesRoutes } from "./receivables";

export const ROUTES: MockRoute[] = [...authRoutes, ...cashRoutes, ...copilotRoutes, ...actionRoutes, ...receivablesRoutes];
