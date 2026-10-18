import type { Alert, AlertTier } from "../../api/contracts";

export const ALERT_TIER_ORDER: readonly AlertTier[] = ["critical", "warning", "watch"];

/** Highest tier first; within a tier, the soonest gap first. */
export function sortAlerts(alerts: readonly Alert[]): Alert[] {
  return [...alerts].sort((a, b) => {
    const byTier = ALERT_TIER_ORDER.indexOf(a.tier) - ALERT_TIER_ORDER.indexOf(b.tier);
    if (byTier !== 0) return byTier;
    return (a.gap?.first_breach_day ?? "9999").localeCompare(b.gap?.first_breach_day ?? "9999");
  });
}
