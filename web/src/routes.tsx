import type { ReactNode } from "react";
import type { RouteObject } from "react-router-dom";

import { LoginScreen } from "./auth/LoginScreen";
import { RequireAuth, ScreenGate } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { NotFound } from "./components/NotFound";
import { SCREENS, type Screen } from "./navigation";
import { VerifyScreen } from "./screens/reports/VerifyScreen";
import { SettingsScreen } from "./screens/settings/SettingsScreen";
import { TrustScreen } from "./screens/trust/TrustScreen";
import { ReportsScreen } from "./screens/reports/ReportsScreen";
import { MessagesScreen } from "./screens/messages/MessagesScreen";
import { MarketScreen } from "./screens/market/MarketScreen";
import { MeshScreen } from "./screens/mesh/MeshScreen";
import { AnalysisScreen } from "./screens/analysis/AnalysisScreen";
import { CashScreen } from "./screens/cash/CashScreen";
import { FinancingScreen } from "./screens/financing/FinancingScreen";
import { ReceivablesScreen } from "./screens/receivables/ReceivablesScreen";
import { TodayScreen } from "./screens/today/TodayScreen";

// One screen component per navigation entry.
const SCREEN_ELEMENTS: Record<Screen, ReactNode> = {
  today: <TodayScreen />,
  cash: <CashScreen />,
  receivables: <ReceivablesScreen />,
  financing: <FinancingScreen />,
  analysis: <AnalysisScreen />,
  mesh: <MeshScreen />,
  market: <MarketScreen />,
  messages: <MessagesScreen />,
  reports: <ReportsScreen />,
  trust: <TrustScreen />,
  settings: <SettingsScreen />,
};

function gated(screen: Screen): ReactNode {
  return <ScreenGate screen={screen}>{SCREEN_ELEMENTS[screen]}</ScreenGate>;
}

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginScreen /> },
  // Public: a lender checks a Trust Passport without an account.
  { path: "/verify/:passportId?", element: <VerifyScreen /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      ...SCREENS.map(
        (screen): RouteObject =>
          screen === "today" ? { index: true, element: gated(screen) } : { path: screen, element: gated(screen) },
      ),
      { path: "*", element: <NotFound /> },
    ],
  },
];
