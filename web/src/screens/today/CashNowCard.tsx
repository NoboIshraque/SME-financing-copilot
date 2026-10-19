// Cash now and runway: the big number on Today.
import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { compareDecimal } from "../../api/decimal";
import { findFigure } from "../../api/figures";
import type { CashForecast } from "../../api/types";
import { FigureValue } from "../../components/FigureValue";
import { QueryView } from "../../components/States";

export function CashNowCard({ query }: { query: UseQueryResult<CashForecast> }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="h-cash-now" className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <h3 id="h-cash-now" className="text-sm font-medium text-slate-600 dark:text-slate-400">
        {t("today.cashNow")}
      </h3>
      <QueryView query={query}>
        {(forecast) => {
          const balance = findFigure(forecast.figures, "cash.closing_balance");
          const runway = findFigure(forecast.figures, "cash.runway_days");
          const buffer = findFigure(forecast.figures, "cash.buffer_target");
          const lowest = findFigure(forecast.figures, "cash.lowest_likely_balance");
          const clear = runway ? compareDecimal(runway.value, String(forecast.band.horizon_days)) >= 0 : false;
          return (
            <>
              {balance && <FigureValue figure={balance} className="mt-1 block text-4xl font-bold tracking-tight" />}
              <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                {runway && (
                  <div className="col-span-2">
                    <dt className="text-slate-600 dark:text-slate-400">{t("today.runway")}</dt>
                    <dd>
                      {clear ? (
                        <span className="font-medium text-emerald-800 dark:text-emerald-300">{t("today.runwayClear")}</span>
                      ) : (
                        <>
                          <FigureValue figure={runway} className="text-xl font-semibold" />{" "}
                          <span className="text-slate-600 dark:text-slate-400">{t("today.runwayHelp")}</span>
                        </>
                      )}
                    </dd>
                  </div>
                )}
                  {buffer && (
                    <div>
                      <dt className="text-slate-600 dark:text-slate-400">{t("today.buffer")}</dt>
                      <dd className="font-semibold">
                        <FigureValue figure={buffer} />
                      </dd>
                    </div>
                  )}
                  {lowest && (
                    <div>
                      <dt className="text-slate-600 dark:text-slate-400">{t("today.lowest")}</dt>
                      <dd className="font-semibold">
                        <FigureValue figure={lowest} />
                      </dd>
                    </div>
                  )}
              </dl>
              <Link to="/cash" className="mt-4 inline-block text-sm font-medium text-teal-800 underline dark:text-teal-300">
                {t("today.seeForecast")}
              </Link>
            </>
          );
        }}
      </QueryView>
    </section>
  );
}
