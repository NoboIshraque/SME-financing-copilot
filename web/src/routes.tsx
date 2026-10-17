import type { RouteObject } from "react-router-dom";

import { AppShell, SCREENS } from "./components/AppShell";
import { Placeholder } from "./components/Placeholder";

// WP-14 replaces each Placeholder with the real screen.
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: SCREENS.map((screen) =>
      screen === "today"
        ? { index: true, element: <Placeholder screen="today" /> }
        : { path: screen, element: <Placeholder screen={screen} /> },
    ),
  },
];
