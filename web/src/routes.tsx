import type { ReactNode } from "react";
import type { RouteObject } from "react-router-dom";

import { LoginScreen } from "./auth/LoginScreen";
import { RequireAuth, ScreenGate } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { NotFound } from "./components/NotFound";
import { Placeholder } from "./components/Placeholder";
import { SCREENS, type Screen } from "./navigation";
import { CashScreen } from "./screens/cash/CashScreen";
import { FinancingScreen } from "./screens/financing/FinancingScreen";
import { ReceivablesScreen } from "./screens/receivables/ReceivablesScreen";
import { TodayScreen } from "./screens/today/TodayScreen";

// WP-14 replaces each Placeholder with the real screen, milestone by milestone.
const SCREEN_ELEMENTS: Record<Screen, ReactNode> = {
  today: <TodayScreen />,
  cash: <CashScreen />,
  receivables: <ReceivablesScreen />,
  financing: <FinancingScreen />,
  analysis: <Placeholder screen="analysis" />,
  mesh: <Placeholder screen="mesh" />,
  market: <Placeholder screen="market" />,
  messages: <Placeholder screen="messages" />,
  reports: <Placeholder screen="reports" />,
  trust: <Placeholder screen="trust" />,
  settings: <Placeholder screen="settings" />,
};

function gated(screen: Screen): ReactNode {
  return <ScreenGate screen={screen}>{SCREEN_ELEMENTS[screen]}</ScreenGate>;
}

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginScreen /> },
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
