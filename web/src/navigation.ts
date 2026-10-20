// Screens, their paths, and which roles see them in the navigation.
import type { Role } from "./api/contracts";
import type { IconName } from "./components/Icon";

export const SCREENS = [
  "today",
  "cash",
  "receivables",
  "financing",
  "analysis",
  "mesh",
  "market",
  "messages",
  "reports",
  "trust",
  "settings",
] as const;
export type Screen = (typeof SCREENS)[number];

export const SCREEN_ICONS: Record<Screen, IconName> = {
  today: "today",
  cash: "cash",
  receivables: "receivables",
  financing: "financing",
  analysis: "analysis",
  mesh: "mesh",
  market: "market",
  messages: "messages",
  reports: "reports",
  trust: "trust",
  settings: "settings",
};

/** Shown in the phone's bottom bar; everything else sits behind "More". */
export const QUICK_SCREENS: readonly Screen[] = ["today", "cash", "receivables", "financing"];

/**
 * Screens each role sees. A convenience for a calm UI only: the API enforces every permission
 * (WP-11), so hiding a link is never the security boundary.
 */
export const SCREEN_ACCESS: Record<Role, readonly Screen[]> = {
  owner: SCREENS,
  // Not Trust: its audit log needs audit:read, which the accountant does not hold.
  accountant: SCREENS.filter((screen) => screen !== "trust"),
  staff: ["today", "receivables", "market", "messages", "settings"],
  lender_viewer: ["reports", "settings"],
  compliance: ["trust", "reports", "messages", "settings"],
};

export function screenPath(screen: Screen): string {
  return screen === "today" ? "/" : `/${screen}`;
}

export function canSee(role: Role, screen: Screen): boolean {
  return SCREEN_ACCESS[role].includes(screen);
}

/** Where a role lands after signing in. */
export function homePath(role: Role): string {
  return screenPath(SCREEN_ACCESS[role][0] ?? "settings");
}
