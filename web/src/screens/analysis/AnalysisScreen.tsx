// Analysis (N1, N12, N16): statements, ratios, expected vs reality, scenario comparison and the
// decision stability bar.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { compareDecimal } from "../../api/decimal";
import { api } from "../../api/endpoints";
import type { Statements } from "../../api/types";
import { FigureValue } from "../../components/FigureValue";
import { StabilityBar } from "../../components/StabilityBar";
import { ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";

const STATEMENTS = ["pnl", "balance_sheet", "cash_flow"] as const;
const DECISIONS = ["retime_supplier", "take_loan", "offer_discount", "do_nothing"] as const;
const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";

function StatementTables({ data }: { data: Statements }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const [which, setWhich] = useState<(typeof STATEMENTS)[number]>("pnl");
  return (
    <>
      <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("analysis.statementChoice")}>
        {STATEMENTS.map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={which === name}
            onClick={() => setWhich(name)}
            className={`rounded-full px-3 py-1.5 text-sm ${which === name ? "bg-teal-700 font-semibold text-white" : "bg-slate-100 dark:bg-slate-800"}`}
          >
            {t(`analysis.statement.${name}`)}
          </button>
        ))}
      </div>
      <table className="mt-3 w-full text-sm">
        <caption className="text-left text-xs text-slate-500 dark:text-slate-400">
          {t(`analysis.statement.${which}`)} · {format.date(data.period.start)}–{format.date(data.period.end, "long")}
        </caption>
        <tbody>
          {data[which].map((row) => (
            <tr key={row.label_key} className={row.total ? "border-t border-slate-300 font-semibold dark:border-slate-600" : ""}>
              <th scope="row" className="py-1 text-left font-normal">{text(row.label_key)}</th>
              <td className="py-1 text-right"><FigureValue figure={row.figure} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function AnalysisScreen() {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  useDocumentTitle(t("nav.analysis"));
  const statements = useQuery({ queryKey: ["analysis", "statements"], queryFn: api.analysis.statements });
  const ratios = useQuery({ queryKey: ["analysis", "ratios"], queryFn: api.analysis.ratios });
  const variance = useQuery({ queryKey: ["analysis", "variance"], queryFn: api.analysis.variance });
  const [decisions, setDecisions] = useState<string[]>([...DECISIONS]);
  const compare = useMutation({ mutationFn: (chosen: string[]) => api.analysis.scenarios(chosen) });
  // The stability of the recommended choice: /stability re-runs the comparison it was handed.
  const comparisonId = compare.data?.recommendation_id;
  const stability = useQuery({
    queryKey: ["analysis", "stability", comparisonId],
    queryFn: () => api.analysis.stability(comparisonId ?? ""),
    enabled: Boolean(comparisonId),
  });

  return (
    <section aria-labelledby="h-analysis" className="space-y-6">
      <h2 id="h-analysis" className="text-xl font-semibold">{t("nav.analysis")}</h2>

      <section aria-labelledby="h-statements" className={card}>
        <h3 id="h-statements" className="text-lg font-semibold">{t("analysis.statementsTitle")}</h3>
        <QueryView query={statements}>{(data) => <StatementTables data={data} />}</QueryView>
      </section>

      <section aria-labelledby="h-ratios" className="space-y-2">
        <h3 id="h-ratios" className="text-lg font-semibold">{t("analysis.ratiosTitle")}</h3>
        <QueryView query={ratios}>
          {(data) => (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.map((ratio) => (
                <li key={ratio.name} className={card} aria-label={text(`ratio.${ratio.name}`)}>
                  <p className="text-sm text-slate-600 dark:text-slate-400">{text(`ratio.${ratio.name}`)}</p>
                  <p className="text-2xl font-semibold tabular-nums">{ratio.value === null || ratio.value === undefined ? t("analysis.notApplicable") : format.value(ratio.value, ratio.unit)}</p>
                  {ratio.benchmark && <p className="text-xs text-slate-500 dark:text-slate-400">{t("analysis.benchmark", { value: ratio.benchmark })}</p>}
                  {ratio.interpretation_key && <p className="mt-1 text-sm">{text(ratio.interpretation_key)}</p>}
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-variance" className={card}>
        <h3 id="h-variance" className="text-lg font-semibold">{t("analysis.varianceTitle")}</h3>
        <QueryView query={variance}>
          {(data) => (
            <>
              <p className="mt-1 text-sm">
                {t("analysis.accuracy")}: <FigureValue figure={data.accuracy} className="font-semibold" />
              </p>
              <table className="mt-3 w-full text-sm">
                <caption className="sr-only">{t("analysis.varianceTitle")}</caption>
                <thead className="text-slate-500 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="text-left font-medium">{t("analysis.metric")}</th>
                    <th scope="col" className="text-right font-medium">{t("analysis.expected")}</th>
                    <th scope="col" className="text-right font-medium">{t("analysis.actual")}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.variances].sort((a, b) => a.rank - b.rank).map((row) => {
                    const direction = compareDecimal(row.actual, row.expected);
                    return (
                      <tr key={row.metric} className="border-t border-slate-100 dark:border-slate-800">
                        <th scope="row" className="py-1 text-left font-normal">{text(`metric.${row.metric}`)}</th>
                        <td className="py-1 text-right tabular-nums">{format.value(row.expected, row.unit)}</td>
                        <td className="py-1 text-right tabular-nums font-semibold">
                          {format.value(row.actual, row.unit)}{" "}
                          <span className="sr-only">{t(direction < 0 ? "analysis.below" : direction > 0 ? "analysis.above" : "analysis.onTarget")}</span>
                          <span aria-hidden="true">{direction < 0 ? "▼" : direction > 0 ? "▲" : "="}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-scenarios" className={card}>
        <h3 id="h-scenarios" className="text-lg font-semibold">{t("analysis.scenariosTitle")}</h3>
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("analysis.scenariosHelp")}</p>
        <fieldset className="mt-3 space-y-1">
          <legend className="sr-only">{t("analysis.decisions")}</legend>
          {DECISIONS.map((decision) => (
            <label key={decision} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={decisions.includes(decision)}
                onChange={(event) => setDecisions(event.target.checked ? [...decisions, decision] : decisions.filter((d) => d !== decision))}
                className="accent-teal-700"
              />
              {text(`decision.${decision}`)}
            </label>
          ))}
        </fieldset>
        <button
          type="button"
          disabled={decisions.length < 2 || compare.isPending}
          onClick={() => compare.mutate(decisions)}
          className="mt-3 rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60"
        >
          {t("analysis.compare")}
        </button>
        {compare.isError && <ErrorState error={compare.error} />}
        {compare.data && (
          <table className="mt-4 w-full text-sm">
            <caption className="sr-only">{t("analysis.scenariosTitle")}</caption>
            <thead className="text-slate-500 dark:text-slate-400">
              <tr>
                <th scope="col" className="text-left font-medium">{t("analysis.decision")}</th>
                <th scope="col" className="text-right font-medium">{t("analysis.expectedOutcome")}</th>
                <th scope="col" className="text-right font-medium">{t("analysis.worst5")}</th>
                <th scope="col" className="text-right font-medium">{t("analysis.breach")}</th>
              </tr>
            </thead>
            <tbody>
              {compare.data.scenarios.map((scenario) => {
                const best = scenario.id === compare.data.recommended_id;
                return (
                  <tr key={scenario.id} className={`border-t border-slate-100 dark:border-slate-800 ${best ? "bg-emerald-50 font-semibold dark:bg-emerald-950/40" : ""}`}>
                    <th scope="row" className="py-1.5 text-left font-normal">
                      {text(scenario.name_key)}
                      {best && <span className="ml-2 rounded-full bg-emerald-600 px-2 py-0.5 text-xs text-white">{t("analysis.recommended")}</span>}
                    </th>
                    <td className="text-right tabular-nums">{format.money(scenario.expected_outcome)}</td>
                    <td className="text-right tabular-nums">{format.money(scenario.worst_5pct_outcome)}</td>
                    <td className="text-right tabular-nums">{format.probability(scenario.p_buffer_breach)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="h-stability" className={card}>
        <h3 id="h-stability" className="text-lg font-semibold">{t("analysis.stabilityTitle")}</h3>
        {comparisonId ? (
          <QueryView query={stability}>{(report) => <StabilityBar report={report} />}</QueryView>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-400">{t("analysis.stabilityHint")}</p>
        )}
      </section>
    </section>
  );
}
