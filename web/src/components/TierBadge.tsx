// Labels for permission tiers (FEATURES P2) and alert tiers (FEATURES Q1).
import { useTranslation } from "react-i18next";

import type { AlertTier, Tier } from "../api/contracts";

const TIER_STYLE: Record<Tier, string> = {
  READ: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  SUGGEST: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100",
  DRAFT: "bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100",
  EXECUTE: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
  DENY: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
};

/** Permission tier of an action card, with what it means as its accessible description. */
export function TierBadge({ tier }: { tier: Tier }) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${TIER_STYLE[tier]}`}
      title={t(`tierHelp.${tier}`)}
      data-tier={tier}
    >
      {t(`tier.${tier}`)}
      <span className="sr-only">: {t(`tierHelp.${tier}`)}</span>
    </span>
  );
}

const ALERT_STYLE: Record<AlertTier, string> = {
  critical: "bg-red-600 text-white",
  warning: "bg-amber-500 text-slate-950",
  watch: "bg-sky-700 text-white",
};

export function AlertTierBadge({ tier }: { tier: AlertTier }) {
  const { t } = useTranslation();
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wide ${ALERT_STYLE[tier]}`}>
      {t(`alertTier.${tier}`)}
    </span>
  );
}
