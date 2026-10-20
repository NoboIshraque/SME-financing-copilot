// One cash alert: what, when, how much and why (FEATURES Q1), plus early warning signs.
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { Alert, AlertTier } from "../../api/contracts";
import { findFigure } from "../../api/figures";
import { FigureValue, Num } from "../../components/FigureValue";
import { AlertTierBadge } from "../../components/TierBadge";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";

const FRAME: Record<AlertTier, string> = {
  critical: "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/60",
  warning: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/50",
  watch: "border-sky-200 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40",
};

/** `level` keeps headings in order: 3 when pinned under the screen title, 5 inside a tier group. */
export function AlertCard({ alert, level }: { alert: Alert; level: 3 | 4 | 5 }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const gap = alert.gap;
  const titleId = useId();
  const shortfall = findFigure(gap?.figures, "cash.expected_shortfall");
  const probability = findFigure(gap?.figures, "cash.breach_probability");
  const fixes = alert.fixes?.length ?? 0;
  const Heading = `h${level}` as const;

  return (
    <article aria-labelledby={titleId} className={`rounded-2xl border p-4 ${FRAME[alert.tier]}`} data-alert-tier={alert.tier}>
      <div className="flex flex-wrap items-center gap-2">
        <AlertTierBadge tier={alert.tier} />
        <Heading id={titleId} className="font-semibold">
          {text(alert.title_key)}
        </Heading>
      </div>

      {gap && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-slate-600 dark:text-slate-400">{t("today.chance")}</dt>
            <dd className="text-lg font-semibold">
              {probability ? <FigureValue figure={probability} /> : format.probability(gap.probability)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-600 dark:text-slate-400">{t("today.shortfall")}</dt>
            <dd className="text-lg font-semibold">
              {shortfall ? <FigureValue figure={shortfall} /> : format.money(gap.expected_shortfall)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-600 dark:text-slate-400">{t("today.firstDay")}</dt>
            <dd className="font-medium">
              {format.date(gap.first_breach_day)}{" "}
              <span className="text-slate-600 dark:text-slate-400">
                ({t("today.inDays", { days: format.days(gap.lead_time_days) })})
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-slate-600 dark:text-slate-400">{t("today.worstDay")}</dt>
            <dd className="font-medium">{format.date(gap.worst_day)}</dd>
          </div>
        </dl>
      )}

      {gap?.drivers && gap.drivers.length > 0 && (
        <div className="mt-3">
          <p className="text-sm font-medium">{t("today.why")}</p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {gap.drivers.map((driver, index) => (
              <li key={`${driver.kind}-${driver.label_key}-${driver.reference_id ?? index}`} className="flex justify-between gap-3">
                <span>{text(driver.label_key)}</span>
                <Num
                  value={driver.amount.amount}
                  unit="BDT"
                  label={text(driver.label_key)}
                  provenance={{ formula_id: "raw.source_row", formula_version: 1, source_row_ids: driver.reference_id ? [driver.reference_id] : [] }}
                  dataMode={alert.data_mode}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {alert.indicators && alert.indicators.length > 0 && (
        <div className="mt-3">
          <p className="text-sm font-medium">{t("today.signs")}</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {alert.indicators.map((indicator) => (
              <li key={indicator} className="rounded-full bg-white/70 px-2.5 py-1 text-xs ring-1 ring-slate-300 dark:bg-slate-900/60 dark:ring-slate-700">
                {t(`indicator.${indicator}`)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {fixes > 0 && (
        <Link to="/cash" className="mt-3 inline-block text-sm font-medium text-teal-800 underline dark:text-teal-300">
          {t("today.seeFixes", { count: fixes })}
        </Link>
      )}
    </article>
  );
}
