// Provenance drawer (N13): the formula, inputs and source rows behind a number. Figures are
// explained by the fact ledger (WP-01, GET /api/explain/{id}); when it has no explanation yet the
// drawer shows the provenance recorded on the figure itself, and says so.
import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiRequestError } from "../api/client";
import { api } from "../api/endpoints";
import { useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { ProvenanceContext, type Explainable } from "./provenance";
import { ErrorState, LoadingState } from "./States";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title}</h3>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}

function RowList({ rows }: { rows: readonly string[] }) {
  return (
    <ul className="space-y-1 font-mono text-xs">
      {rows.map((row) => (
        <li key={row} className="break-all rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">{row}</li>
      ))}
    </ul>
  );
}

function DrawerBody({ item }: { item: Explainable }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const figureId = item.figure?.id;
  const explanation = useQuery({
    queryKey: ["explain", figureId],
    queryFn: () => api.explain(figureId ?? ""),
    enabled: Boolean(figureId),
    retry: false,
    staleTime: Infinity,
  });
  const recorded = item.figure?.provenance ?? item.provenance;
  const notExplained = explanation.isError && explanation.error instanceof ApiRequestError && explanation.error.status === 404;
  const data = explanation.data;
  const dataMode = item.figure?.data_mode ?? item.dataMode;

  return (
    <>
      <p className="mt-1 text-3xl font-bold tabular-nums">{item.shown}</p>
      {dataMode && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t(`dataMode.${dataMode}`)}</p>}

      {figureId && explanation.isPending && <div className="mt-4"><LoadingState /></div>}
      {explanation.isError && !notExplained && <div className="mt-4"><ErrorState error={explanation.error} onRetry={() => void explanation.refetch()} /></div>}

      {data ? (
        <>
          <Section title={t("provenance.formula")}>
            <code className="block rounded-lg bg-slate-100 p-2 text-sm dark:bg-slate-800">{data.formula.expression}</code>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t("provenance.formulaId", { id: data.formula.formula_id, version: data.formula.version })}</p>
          </Section>
          <Section title={t("provenance.inputs")}>
            {data.inputs.length === 0 ? (
              <p className="text-sm text-slate-600 dark:text-slate-400">{t("provenance.noInputs")}</p>
            ) : (
              <table className="w-full text-sm">
                <caption className="sr-only">{t("provenance.inputs")}</caption>
                <tbody>
                  {data.inputs.map((input) => (
                    <tr key={input.fact_id} className="border-t border-slate-100 dark:border-slate-800">
                      <th scope="row" className="py-1 text-left font-normal">{text(`metric.${input.metric}`)}</th>
                      <td className="py-1 text-right tabular-nums">{format.value(input.value, input.unit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          <Section title={t("provenance.sources")}>
            {data.masked && <p className="mb-1.5 text-sm text-amber-800 dark:text-amber-200">{t("provenance.masked")}</p>}
            {data.source_rows.length === 0 ? <p className="text-sm text-slate-600 dark:text-slate-400">{t("provenance.noRows")}</p> : <RowList rows={data.source_rows} />}
          </Section>
        </>
      ) : (
        recorded &&
        (!figureId || notExplained) && (
          <>
            {notExplained && <p className="mt-4 rounded-lg bg-slate-100 p-2 text-sm dark:bg-slate-800">{t("provenance.recordedOnly")}</p>}
            <Section title={t("provenance.formula")}>
              <p className="text-sm">{t("provenance.formulaId", { id: recorded.formula_id, version: recorded.formula_version })}</p>
            </Section>
            {recorded.parameters && Object.keys(recorded.parameters).length > 0 && (
              <Section title={t("provenance.parameters")}>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-sm">
                  {Object.entries(recorded.parameters).map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt className="text-slate-600 dark:text-slate-400">{key}</dt>
                      <dd className="font-mono text-xs">{value}</dd>
                    </div>
                  ))}
                </dl>
              </Section>
            )}
            {recorded.input_fact_ids && recorded.input_fact_ids.length > 0 && (
              <Section title={t("provenance.inputs")}><RowList rows={recorded.input_fact_ids} /></Section>
            )}
            {recorded.source_row_ids && recorded.source_row_ids.length > 0 && (
              <Section title={t("provenance.sources")}><RowList rows={recorded.source_row_ids} /></Section>
            )}
          </>
        )
      )}
      <p className="mt-6 text-xs text-slate-500 dark:text-slate-400">{t("provenance.codeComputes")}</p>
    </>
  );
}

export function ProvenanceProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const titleId = useId();
  const [item, setItem] = useState<Explainable | null>(null);
  return (
    <ProvenanceContext.Provider value={setItem}>
      {children}
      <Dialog open={item !== null} onClose={() => setItem(null)} labelledBy={titleId} placement="right" panelClassName="h-dvh w-full max-w-md">
        {item && (
          <>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-300">{t("provenance.title")}</p>
                <h2 id={titleId} className="text-lg font-semibold">{item.label}</h2>
              </div>
              <button type="button" onClick={() => setItem(null)} aria-label={t("provenance.close")} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800">
                <Icon name="close" />
              </button>
            </div>
            <DrawerBody item={item} />
          </>
        )}
      </Dialog>
    </ProvenanceContext.Provider>
  );
}
