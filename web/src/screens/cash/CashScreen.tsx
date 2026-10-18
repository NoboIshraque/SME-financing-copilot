// Cash: 13-week forecast with P10/P50/P90 bands, gap markers, what-if sliders, and the ranked
// fixes as approvable action cards.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useDeferredValue, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ActionCard, ForecastBand } from "../../api/contracts";
import { api } from "../../api/endpoints";
import { findFigure } from "../../api/figures";
import type { CashForecast } from "../../api/types";
import { ActionCardView } from "../../components/ActionCardView";
import { FigureValue } from "../../components/FigureValue";
import { EmptyState, ErrorState, LoadingState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";
import { ForecastChart } from "./ForecastChart";

interface Shocks {
  sales: number;
  costs: number;
  delay: number;
  oneOff: number;
}

const NO_SHOCKS: Shocks = { sales: 0, costs: 0, delay: 0, oneOff: 0 };

const SLIDERS: Array<{ key: keyof Shocks; min: number; max: number; step: number }> = [
  { key: "sales", min: -30, max: 30, step: 5 },
  { key: "costs", min: -10, max: 20, step: 2 },
  { key: "delay", min: 0, max: 30, step: 5 },
  { key: "oneOff", min: 0, max: 200000, step: 10000 },
];

function WeeklyTable({ band }: { band: ForecastBand }) {
  const { t } = useTranslation();
  const format = useFormat();
  const weeks = band.points.filter((_, i) => (i + 1) % 7 === 0);
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-sm font-medium text-teal-800 dark:text-teal-300">{t("cash.showNumbers")}</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-right text-sm tabular-nums">
          <caption className="sr-only">{t("cash.tableCaption")}</caption>
          <thead className="text-slate-500 dark:text-slate-400">
            <tr>
              <th scope="col" className="py-1 text-left font-medium">{t("cash.week")}</th>
              <th scope="col" className="font-medium">{t("cash.p10")}</th>
              <th scope="col" className="font-medium">{t("cash.p50")}</th>
              <th scope="col" className="font-medium">{t("cash.p90")}</th>
              <th scope="col" className="font-medium">{t("cash.chanceBelow")}</th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((point, i) => (
              <tr key={point.day} className="border-t border-slate-100 dark:border-slate-800">
                <th scope="row" className="py-1 text-left font-normal">
                  {t("cash.weekN", { n: i + 1, date: format.date(point.day) })}
                </th>
                <td>{format.money(point.p10)}</td>
                <td className="font-semibold">{format.money(point.p50)}</td>
                <td>{format.money(point.p90)}</td>
                <td>{format.probability(point.p_below_buffer)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function WhatIfPanel({ shocks, onChange, result }: { shocks: Shocks; onChange: (s: Shocks) => void; result?: CashForecast }) {
  const { t } = useTranslation();
  const format = useFormat();
  const active = JSON.stringify(shocks) !== JSON.stringify(NO_SHOCKS);
  const valueText = (key: keyof Shocks, value: number) =>
    key === "delay" ? format.days(value) : key === "oneOff" ? format.money({ amount: `${value}.00` }) : `${format.number(String(value), 0)}%`;
  const runway = findFigure(result?.figures, "cash.runway_days");
  const lowest = findFigure(result?.figures, "cash.lowest_likely_balance");
  return (
    <section aria-labelledby="h-whatif" className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <h3 id="h-whatif" className="text-lg font-semibold">{t("cash.whatIfTitle")}</h3>
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("cash.whatIfHelp")}</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {SLIDERS.map(({ key, min, max, step }) => (
          <label key={key} className="block text-sm">
            <span className="flex justify-between font-medium">
              {t(`cash.slider.${key}`)}
              <span className="tabular-nums text-slate-600 dark:text-slate-300">{valueText(key, shocks[key])}</span>
            </span>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={shocks[key]}
              aria-valuetext={valueText(key, shocks[key])}
              onChange={(event) => onChange({ ...shocks, [key]: Number(event.target.value) })}
              className="mt-1 w-full accent-teal-700"
            />
          </label>
        ))}
      </div>
      {active && (
        <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-3" aria-live="polite">
          {runway && (
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t("cash.whatIfRunway")}</p>
              <FigureValue figure={runway} className="text-xl font-semibold" />
            </div>
          )}
          {lowest && (
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t("cash.whatIfLowest")}</p>
              <FigureValue figure={lowest} className="text-xl font-semibold" />
            </div>
          )}
          <button type="button" onClick={() => onChange(NO_SHOCKS)} className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium dark:border-slate-600">
            {t("cash.reset")}
          </button>
        </div>
      )}
    </section>
  );
}

export function CashScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  const text = useServerText();
  useDocumentTitle(t("nav.cash"));
  const forecast = useQuery({ queryKey: ["cash", "forecast"], queryFn: api.cash.forecast });
  const gaps = useQuery({ queryKey: ["cash", "gaps"], queryFn: api.cash.gaps });
  const alerts = useQuery({ queryKey: ["cash", "alerts"], queryFn: api.cash.alerts });
  const [shocks, setShocks] = useState<Shocks>(NO_SHOCKS);
  const deferred = useDeferredValue(shocks);
  const active = JSON.stringify(deferred) !== JSON.stringify(NO_SHOCKS);
  const whatIf = useQuery({
    queryKey: ["cash", "whatif", deferred.sales, deferred.costs, deferred.delay, deferred.oneOff],
    queryFn: () =>
      api.cash.whatIf({
        sales_change_pct: String(deferred.sales),
        cost_change_pct: String(deferred.costs),
        collection_delay_days: deferred.delay,
        one_off_cost: { amount: `${deferred.oneOff}.00`, currency: "BDT" },
      }),
    enabled: active,
    placeholderData: keepPreviousData,
  });

  const fixes = new Map<string, ActionCard>();
  for (const alert of alerts.data ?? []) for (const fix of alert.fixes ?? []) fixes.set(fix.id, fix);

  return (
    <section aria-labelledby="h-cash" className="space-y-6">
      <h2 id="h-cash" className="text-xl font-semibold">{t("nav.cash")}</h2>

      <section aria-labelledby="h-forecast" className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <h3 id="h-forecast" className="text-lg font-semibold">{t("cash.forecastTitle")}</h3>
        <QueryView query={forecast}>
          {(data) => {
            const balance = findFigure(data.figures, "cash.closing_balance");
            const runway = findFigure(data.figures, "cash.runway_days");
            const buffer = findFigure(data.figures, "cash.buffer_target");
            return (
              <>
                <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2 text-sm">
                  {[balance, runway, buffer].map(
                    (figure) =>
                      figure && (
                        <div key={figure.id}>
                          <dt className="text-slate-600 dark:text-slate-400">{text(figure.label_key)}</dt>
                          <dd className="text-xl font-semibold">
                            <FigureValue figure={figure} />
                          </dd>
                        </div>
                      ),
                  )}
                </dl>
                <p className="mt-3 flex flex-wrap gap-4 text-xs text-slate-600 dark:text-slate-400">
                  <span><span className="mr-1 inline-block h-0.5 w-4 bg-teal-700 align-middle" />{t("cash.p50")}</span>
                  <span><span className="mr-1 inline-block h-2 w-4 bg-teal-500/30 align-middle" />{t("cash.bandLegend")}</span>
                  <span><span className="mr-1 inline-block h-0.5 w-4 border-t-2 border-dashed border-red-600 align-middle" />{t("cash.bufferLine")}</span>
                  {active && <span><span className="mr-1 inline-block h-0.5 w-4 border-t-2 border-dashed border-amber-600 align-middle" />{t("cash.whatIfLine")}</span>}
                </p>
                <ForecastChart band={data.band} whatIf={active ? whatIf.data?.band : undefined} gaps={gaps.data ?? []} />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t("cash.simulated", { paths: format.number(String(data.band.paths), 0), seed: data.band.seed })}
                </p>
                <WeeklyTable band={data.band} />
              </>
            );
          }}
        </QueryView>
      </section>

      <section aria-labelledby="h-gaps" className="space-y-3">
        <h3 id="h-gaps" className="text-lg font-semibold">{t("cash.gapsTitle")}</h3>
        {gaps.isPending ? (
          <LoadingState />
        ) : gaps.isError ? (
          <ErrorState error={gaps.error} onRetry={() => void gaps.refetch()} />
        ) : gaps.data.length === 0 ? (
          <EmptyState>{t("cash.noGaps")}</EmptyState>
        ) : (
          <ul className="space-y-2">
            {gaps.data.map((gap) => (
              <li key={gap.first_breach_day} className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm dark:border-red-900 dark:bg-red-950/50">
                <p className="font-semibold">
                  {t("cash.gapLine", { date: format.date(gap.first_breach_day, "long"), days: format.days(gap.lead_time_days) })}
                </p>
                <p>
                  {t("today.chance")}: <span className="font-semibold">{format.probability(gap.probability)}</span> · {t("today.shortfall")}:{" "}
                  <span className="font-semibold">{format.money(gap.expected_shortfall)}</span>
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <WhatIfPanel shocks={shocks} onChange={setShocks} result={active ? whatIf.data : undefined} />

      <section aria-labelledby="h-levers" className="space-y-3">
        <h3 id="h-levers" className="text-lg font-semibold">{t("cash.leversTitle")}</h3>
        {fixes.size === 0 ? (
          <EmptyState>{t("cash.noLevers")}</EmptyState>
        ) : (
          <ul className="space-y-3">
            {[...fixes.values()].map((card, index) => (
              <li key={card.id}>
                <ActionCardView card={card} primary={index === 0} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
