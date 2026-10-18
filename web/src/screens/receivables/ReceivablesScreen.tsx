// Receivables (FEATURES Q2): what customers owe, how old it is, who is risky, the reminder
// ladder as approvable drafts, credit limits, and a dispute log.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { compareDecimal, toChartNumber } from "../../api/decimal";
import { api } from "../../api/endpoints";
import type { ReceivableRow, ReceivablesOverview } from "../../api/types";
import { ActionCardView } from "../../components/ActionCardView";
import { Dialog } from "../../components/Dialog";
import { FigureValue } from "../../components/FigureValue";
import { EmptyState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { describeError, useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";

const DISPUTE_REASONS = ["quality", "quantity", "price", "not_received", "other"] as const;

function riskLevel(score: string): "high" | "medium" | "low" {
  if (compareDecimal(score, "60") >= 0) return "high";
  if (compareDecimal(score, "35") >= 0) return "medium";
  return "low";
}

const RISK_STYLE = {
  high: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
  medium: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100",
  low: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
};

function DisputeDialog({ row, onClose }: { row: ReceivableRow; onClose: () => void }) {
  const { t } = useTranslation();
  const text = useServerText();
  const queryClient = useQueryClient();
  const titleId = useId();
  const [reason, setReason] = useState<string>(DISPUTE_REASONS[0]);
  const record = useMutation({
    mutationFn: () => api.receivables.dispute(row.invoice.id, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["receivables"] });
      void queryClient.invalidateQueries({ queryKey: ["cash"] });
      onClose();
    },
  });
  const error = record.isError ? describeError(record.error) : null;
  return (
    <Dialog open onClose={onClose} labelledBy={titleId}>
      <h2 id={titleId} className="text-lg font-semibold">{t("receivables.disputeTitle")}</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
        {row.counterparty_label} · {row.invoice.source_ref.split("#").pop()}
      </p>
      <p className="mt-2 text-sm">{t("receivables.disputeHelp")}</p>
      <fieldset className="mt-4 space-y-2">
        <legend className="text-sm font-medium">{t("receivables.reason")}</legend>
        {DISPUTE_REASONS.map((code) => (
          <label key={code} className="flex items-center gap-2 text-sm">
            <input type="radio" name="reason" value={code} checked={reason === code} onChange={() => setReason(code)} className="accent-teal-700" />
            {t(`receivables.reasons.${code}`)}
          </label>
        ))}
      </fieldset>
      {error && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{text(error.key, error.values)}</p>}
      <div className="mt-5 flex gap-3">
        <button type="button" onClick={onClose} className="flex-1 rounded-xl border border-slate-300 px-4 py-3 font-medium dark:border-slate-600">
          {t("common.cancel")}
        </button>
        <button type="button" onClick={() => record.mutate()} disabled={record.isPending} className="flex-1 rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white disabled:opacity-60">
          {t("receivables.recordDispute")}
        </button>
      </div>
    </Dialog>
  );
}

function InvoiceRow({ row, onDispute }: { row: ReceivableRow; onDispute: (row: ReceivableRow) => void }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const queryClient = useQueryClient();
  const resolve = useMutation({
    mutationFn: () => api.receivables.resolve(row.invoice.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["receivables"] });
      void queryClient.invalidateQueries({ queryKey: ["cash"] });
    },
  });
  const level = riskLevel(row.risk_score);
  const number = row.invoice.source_ref.split("#").pop() ?? row.invoice.id;
  return (
    <li className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800" aria-label={`${row.counterparty_label} ${number}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{row.counterparty_label}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {number} · {t("receivables.due", { date: format.date(row.invoice.due_date) })}
            {row.days_overdue > 0 && <> · {t("receivables.late", { days: format.days(row.days_overdue) })}</>}
          </p>
        </div>
        <p className="text-lg font-semibold tabular-nums">{format.money(row.invoice.amount)}</p>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className={`rounded-full px-2 py-0.5 font-semibold ${RISK_STYLE[level]}`}>
          {t(`receivables.risk.${level}`)} · {format.number(row.risk_score, 0)}/100
        </span>
        {row.risk_factor_keys.map((key) => (
          <span key={key} className="rounded-full px-2 py-0.5 ring-1 ring-slate-300 dark:ring-slate-700">{text(key)}</span>
        ))}
      </div>
      {row.disputed ? (
        <div className="mt-3 rounded-xl bg-violet-50 p-3 text-sm dark:bg-violet-950/50">
          <p className="font-semibold">
            {t("receivables.disputed")}: {t(`receivables.reasons.${row.dispute_reason ?? "other"}`, { defaultValue: row.dispute_reason ?? "" })}
          </p>
          <p>{t("receivables.excluded")}</p>
          <button type="button" onClick={() => resolve.mutate()} disabled={resolve.isPending} className="mt-2 rounded-lg border border-violet-400 px-3 py-1.5 font-medium">
            {t("receivables.resolve")}
          </button>
        </div>
      ) : (
        <button type="button" onClick={() => onDispute(row)} className="mt-3 text-sm font-medium text-teal-800 underline dark:text-teal-300">
          {t("receivables.recordDispute")}
        </button>
      )}
    </li>
  );
}

function Overview({ data }: { data: ReceivablesOverview }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const [disputing, setDisputing] = useState<ReceivableRow | null>(null);
  const largest = data.aging.reduce((max, bucket) => (compareDecimal(bucket.amount.amount, max) > 0 ? bucket.amount.amount : max), "0");
  const sorted = [...data.invoices].sort((a, b) => compareDecimal(b.risk_score, a.risk_score));
  return (
    <>
      <dl className="flex flex-wrap gap-x-8 gap-y-3 rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        {data.figures.map((figure) => (
          <div key={figure.id}>
            <dt className="text-sm text-slate-600 dark:text-slate-400">{text(figure.label_key)}</dt>
            <dd className="text-2xl font-semibold"><FigureValue figure={figure} /></dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="h-aging" className="space-y-2">
        <h3 id="h-aging" className="text-lg font-semibold">{t("receivables.agingTitle")}</h3>
        <ul className="space-y-2">
          {data.aging.map((bucket) => {
            const share = compareDecimal(largest, "0") > 0 ? Math.round((toChartNumber(bucket.amount.amount) / toChartNumber(largest)) * 100) : 0;
            return (
              <li key={bucket.bucket} className="grid grid-cols-[6.5rem_1fr_auto] items-center gap-3 text-sm">
                <span>{t(`receivables.bucket.${bucket.bucket}`)}</span>
                <span className="h-3 rounded-full bg-slate-100 dark:bg-slate-800" aria-hidden="true">
                  <span className="block h-3 rounded-full bg-teal-600" style={{ width: `${share}%` }} />
                </span>
                <span className="tabular-nums">
                  {format.money(bucket.amount)} ({t("receivables.invoiceCount", { count: bucket.count })})
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="h-invoices" className="space-y-2">
        <h3 id="h-invoices" className="text-lg font-semibold">{t("receivables.invoicesTitle")}</h3>
        {sorted.length === 0 ? (
          <EmptyState>{t("receivables.none")}</EmptyState>
        ) : (
          <ul className="space-y-3">
            {sorted.map((row) => (
              <InvoiceRow key={row.invoice.id} row={row} onDispute={setDisputing} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="h-credit" className="space-y-2">
        <h3 id="h-credit" className="text-lg font-semibold">{t("receivables.creditTitle")}</h3>
        <ul className="divide-y divide-slate-200 rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
          {data.customers.map((customer) => (
            <li key={customer.counterparty_token} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <span className="font-medium">{customer.counterparty_label}</span>
              <span className="text-slate-600 dark:text-slate-400">
                {t("receivables.owes", { amount: format.money(customer.open) })} · {t("receivables.avgLate", { days: format.days(customer.avg_days_late) })}
              </span>
              <span>
                {t("receivables.limit")}: {customer.credit_limit ? <FigureValue figure={customer.credit_limit} className="font-semibold" /> : "—"}
              </span>
              {customer.stop_credit && (
                <span className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-bold text-white">{t("receivables.stopCredit")}</span>
              )}
            </li>
          ))}
        </ul>
      </section>
      {disputing && <DisputeDialog row={disputing} onClose={() => setDisputing(null)} />}
    </>
  );
}

export function ReceivablesScreen() {
  const { t } = useTranslation();
  useDocumentTitle(t("nav.receivables"));
  const overview = useQuery({ queryKey: ["receivables", "overview"], queryFn: api.receivables.overview });
  const plan = useQuery({ queryKey: ["receivables", "plan"], queryFn: api.receivables.plan });
  return (
    <section aria-labelledby="h-receivables" className="space-y-6">
      <h2 id="h-receivables" className="text-xl font-semibold">{t("nav.receivables")}</h2>
      <section aria-labelledby="h-reminders" className="space-y-3">
        <h3 id="h-reminders" className="text-lg font-semibold">{t("receivables.remindersTitle")}</h3>
        <QueryView query={plan} isEmpty={(data) => data.reminders.length === 0} empty={t("receivables.noReminders")}>
          {(data) => (
            <ul className="space-y-3">
              {data.reminders.map((card, index) => (
                <li key={card.id}>
                  <ActionCardView card={card} primary={index === 0} />
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
      <QueryView query={overview}>{(data) => <Overview data={data} />}</QueryView>
    </section>
  );
}
