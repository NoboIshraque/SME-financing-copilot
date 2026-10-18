// Every mock route, one module per backend router.
import type { MockRoute } from "../http";
import { authRoutes } from "./auth";

export const ROUTES: MockRoute[] = [...authRoutes];
