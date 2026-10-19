// Financing (P1, N20): describe the need, get every realistic option ranked by true annual cost
// and fit, with eligibility reasons, the lender's track record, and a draft application.
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { FinancingNeed, FinancingOption, LenderProfile } from "../../api/contracts";
import { api } from "../../api/endpoints";
import { findFigure } from "../../api/figures";
import type { FinancingMatch } from "../../api/types";
import { useRequiredSession } from "../../auth/session";
import { ActionCardView } from "../../components/ActionCardView";
import { FigureValue } from "../../components/FigureValue";
import { ErrorState } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";
import { parseAmount } from "./amount";

const TENORS = [90, 180, 365] as const;
const PURPOSES = ["working_capital", "stock", "equipment", "other"] as const;

const ELIGIBILITY_STYLE = {
  pass: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  fail: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100",
  not_on_record: "bg-slate-200 text-slate-800 dark:bg-slate-800 dark:text-slate-100",
};

function LenderCheck({ lender }: { lender: LenderProfile }) {
  const { t } = useTranslation();
  const format = useFormat();
  return (
    <details className="mt-3 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
      <summary className="cursor-pointer font-medium">{t("financing.lenderCheck")}</summary>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
        <dt className="text-slate-600 dark:text-slate-400">{t("financing.licence")}</dt>
        <dd>{t(`financing.licenceStatus.${lender.licence_status}`)}{lender.regulator ? ` · ${lender.regulator}` : ""}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("financing.aprGap")}</dt>
        <dd>{lender.quoted_vs_realised_apr_gap != null ? t("financing.points", { value: format.number(lender.quoted_vs_realised_apr_gap, 2) }) : "—"}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("financing.disbursal")}</dt>
        <dd>{lender.median_disbursal_days != null ? format.days(lender.median_disbursal_days) : "—"}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("financing.hiddenFees")}</dt>
        <dd>{format.number(String(lender.hidden_fee_incidents ?? 0), 0)}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("financing.disputes")}</dt>
        <dd>{format.number(String(lender.disputes ?? 0), 0)}</dd>
      </dl>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {t("financing.trackRecord", { count: lender.events_count })} · {t(`dataMode.${lender.data_mode}`)}
      </p>
    </details>
  );
}

function OptionCard({ option, lender }: { option: FinancingOption; lender?: LenderProfile }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const { product, eligibility } = option;
  const apr = findFigure(option.figures, "financing.effective_apr");
  const cost = findFigure(option.figures, "financing.total_cost");
  const titleId = useId();
  return (
    <article aria-labelledby={titleId} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-700 text-sm font-bold text-white" aria-label={t("financing.rank", { rank: option.rank })}>
          {format.number(String(option.rank), 0)}
        </span>
        <div className="min-w-0 flex-1">
          <h4 id={titleId} className="font-semibold">{product.name}</h4>
          <p className="text-sm text-slate-600 dark:text-slate-400">{product.provider}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ELIGIBILITY_STYLE[eligibility.status]}`}>
          {t(`financing.eligibility.${eligibility.status}`)}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-slate-600 dark:text-slate-400">{t("financing.trueCost")}</dt>
          <dd className="text-lg font-semibold">{apr ? <FigureValue figure={apr} /> : format.percent(option.effective_apr)}</dd>
        </div>
        <div>
          <dt className="text-slate-600 dark:text-slate-400">{t("financing.totalCost")}</dt>
          <dd className="text-lg font-semibold">{cost ? <FigureValue figure={cost} /> : format.money(option.total_cost)}</dd>
        </div>
        <div>
          <dt className="text-slate-600 dark:text-slate-400">{t("financing.speed")}</dt>
          <dd>{format.days(option.speed_days)}</dd>
        </div>
        {!option.reason_keys?.includes("fit.no_forecast") && (
          <div>
            <dt className="text-slate-600 dark:text-slate-400">{t("financing.fit")}</dt>
            <dd>{t("financing.breach", { chance: format.probability(option.p_buffer_breach) })}</dd>
          </div>
        )}
      </dl>
      <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
        {t("financing.nominal", { rate: format.percent(product.nominal_rate_pa) })} · {t(`financing.rateBasis.${product.rate_basis ?? "published"}`)}
        {product.is_modelled ? ` · ${t("financing.modelled")}` : ""} · {t("financing.likelihood", { chance: format.probability(option.approval_likelihood) })}
      </p>

      {option.reason_keys && option.reason_keys.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2 text-xs">
          {option.reason_keys.map((key) => (
            <li key={key} className="rounded-full bg-teal-50 px-2 py-0.5 text-teal-900 dark:bg-teal-950 dark:text-teal-100">{text(key)}</li>
          ))}
        </ul>
      )}

      {eligibility.reasons && eligibility.reasons.length > 0 && (
        <div className="mt-3">
          <p className="text-sm font-medium">{t("financing.why")}</p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {eligibility.reasons.map((reason) => (
              <li key={reason.rule_id} data-status={reason.status}>
                <span aria-hidden="true">{reason.status === "pass" ? "✓ " : reason.status === "fail" ? "✗ " : "? "}</span>
                {text(reason.message_key)} — {t(`financing.ruleStatus.${reason.status}`)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {product.notes && <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{product.notes}</p>}
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {product.source_url ? (
          <a href={product.source_url} target="_blank" rel="noopener noreferrer" className="underline">
            {t("financing.source")}
          </a>
        ) : (
          t(`dataMode.${product.data_mode}`)
        )}
        {product.checked_on && <> · {t("financing.checkedOn", { date: format.date(product.checked_on, "long") })}</>}
      </p>
      {lender && <LenderCheck lender={lender} />}
    </article>
  );
}

function Results({ match }: { match: FinancingMatch }) {
  const { t } = useTranslation();
  const lenders = new Map(match.lenders.map((lender) => [lender.name, lender]));
  const options = [...match.options].sort((a, b) => a.rank - b.rank);
  return (
    <section aria-labelledby="h-options" className="space-y-3">
      <h3 id="h-options" className="text-lg font-semibold">{t("financing.optionsTitle")}</h3>
      {match.application && (
        <div className="space-y-2">
          <p className="text-sm text-slate-600 dark:text-slate-400">{t("financing.applicationHelp")}</p>
          <ActionCardView card={match.application} primary />
        </div>
      )}
      <ol className="space-y-3">
        {options.map((option) => (
          <li key={option.product.id}>
            <OptionCard option={option} lender={lenders.get(option.product.provider)} />
          </li>
        ))}
      </ol>
    </section>
  );
}

export function FinancingScreen() {
  const { t } = useTranslation();
  useDocumentTitle(t("nav.financing"));
  const session = useRequiredSession();
  const ids = { amount: useId(), date: useId(), tenor: useId(), purpose: useId(), error: useId() };
  const [amount, setAmount] = useState("200000");
  const [neededBy, setNeededBy] = useState("2026-10-25");
  const [tenor, setTenor] = useState<number>(180);
  const [purpose, setPurpose] = useState<(typeof PURPOSES)[number]>("working_capital");
  const [invalid, setInvalid] = useState(false);
  const match = useMutation({ mutationFn: (need: FinancingNeed) => api.financing.match(need) });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const parsed = parseAmount(amount);
    setInvalid(parsed === null);
    if (parsed === null) return;
    match.mutate({
      tenant_id: session.principal.tenant_id,
      amount: { amount: parsed, currency: "BDT" },
      needed_by: neededBy,
      tenor_days: tenor,
      purpose_key: `purpose.${purpose}`,
    });
  };

  const field = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-600 dark:bg-slate-800";
  return (
    <section aria-labelledby="h-financing" className="space-y-6">
      <h2 id="h-financing" className="text-xl font-semibold">{t("nav.financing")}</h2>
      <form onSubmit={submit} noValidate aria-labelledby="h-need" className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <h3 id="h-need" className="text-lg font-semibold">{t("financing.needTitle")}</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={ids.amount} className="mb-1 block text-sm font-medium">{t("financing.amount")}</label>
            <input id={ids.amount} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-invalid={invalid || undefined} aria-describedby={invalid ? ids.error : undefined} className={field} />
          </div>
          <div>
            <label htmlFor={ids.date} className="mb-1 block text-sm font-medium">{t("financing.neededBy")}</label>
            <input id={ids.date} type="date" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} className={field} />
          </div>
          <div>
            <label htmlFor={ids.tenor} className="mb-1 block text-sm font-medium">{t("financing.tenor")}</label>
            <select id={ids.tenor} value={tenor} onChange={(e) => setTenor(Number(e.target.value))} className={field}>
              {TENORS.map((days) => (
                <option key={days} value={days}>{t("financing.months", { count: days / 30 })}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={ids.purpose} className="mb-1 block text-sm font-medium">{t("financing.purpose")}</label>
            <select id={ids.purpose} value={purpose} onChange={(e) => setPurpose(e.target.value as (typeof PURPOSES)[number])} className={field}>
              {PURPOSES.map((code) => (
                <option key={code} value={code}>{t(`purpose.${code}`)}</option>
              ))}
            </select>
          </div>
        </div>
        {invalid && <p id={ids.error} role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{t("financing.amountInvalid")}</p>}
        <button type="submit" disabled={match.isPending} className="mt-4 w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60 sm:w-auto">
          {match.isPending ? t("financing.matching") : t("financing.find")}
        </button>
      </form>
      {match.isError && <ErrorState error={match.error} />}
      {match.data && <Results match={match.data} />}
    </section>
  );
}
