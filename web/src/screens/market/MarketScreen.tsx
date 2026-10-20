// Market (N3, N19): watched input prices with honest publication dates, price alerts, vendors
// ranked by landed cost, and a step-by-step negotiation script with the numbers behind it.
// Prices come from TCB's published daily lists (WP-09); a part the server does not serve yet falls
// back to the bundled sample (`orSample`) and carries a "Sample data" label on its own card.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { compareDecimal } from "../../api/decimal";
import { api } from "../../api/endpoints";
import type { NegotiationRequest, WatchItem } from "../../api/types";
import { useSession } from "../../auth/session";
import { FigureValue } from "../../components/FigureValue";
import { EmptyState, ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";
import { parseAmount } from "../financing/amount";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";
/** Server answers carry the source list's date; the bundled sample has none. */
function livePrices(list: WatchItem[] | undefined): boolean {
  return Boolean(list && list.length > 0 && list.every((item) => item.published_on));
}

function SampleLabel() {
  const { t } = useTranslation();
  return (
    <p role="note" className="mt-1 rounded-lg bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900 dark:bg-amber-900/30 dark:text-amber-100">
      {t("market.sampleLabel")}
    </p>
  );
}

const field = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-600 dark:bg-slate-800";

function VendorRanking({ commodities }: { commodities: string[] }) {
  const { t } = useTranslation();
  // A self-service shop's own data is live: sample vendors are never shown to it as its own.
  const ownShop = useSession().data?.data_mode === "live";
  const text = useServerText();
  const format = useFormat();
  const ids = { commodity: useId(), quantity: useId() };
  const [commodity, setCommodity] = useState(commodities.includes("rice_coarse") ? "rice_coarse" : (commodities[0] ?? ""));
  const [quantity, setQuantity] = useState("500");
  const rank = useMutation({ mutationFn: () => api.market.rankVendors(commodity, quantity.trim()) });
  return (
    <section aria-labelledby="h-vendors" className={card}>
      <h3 id="h-vendors" className="text-lg font-semibold">{t("market.vendorsTitle")}</h3>
      <SampleLabel />
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor={ids.commodity} className="mb-1 block text-sm font-medium">{t("market.commodity")}</label>
          <select id={ids.commodity} value={commodity} onChange={(e) => setCommodity(e.target.value)} className={field}>
            {commodities.map((name) => <option key={name} value={name}>{text(`commodity.${name}`)}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.quantity} className="mb-1 block text-sm font-medium">{t("market.quantity")}</label>
          <input id={ids.quantity} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={field} />
        </div>
        <div className="flex items-end">
          <button type="button" onClick={() => rank.mutate()} disabled={rank.isPending} className="w-full rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
            {t("market.rank")}
          </button>
        </div>
      </div>
      {rank.isError && <div className="mt-3"><ErrorState error={rank.error} /></div>}
      {rank.data && ownShop && (
        <div className="mt-3"><EmptyState>{t("market.addQuote")}</EmptyState></div>
      )}
      {rank.data && !ownShop && (rank.data.length === 0 ? (
        <div className="mt-3"><EmptyState>{t("market.noQuotes")}</EmptyState></div>
      ) : (
        <ol className="mt-4 space-y-3">
          {rank.data.map((vendor) => (
            <li key={vendor.vendor_label} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700" aria-label={vendor.vendor_label}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-semibold">{format.number(String(vendor.rank), 0)}. {vendor.vendor_label}</p>
                <p className="text-lg font-semibold">
                  <FigureValue figure={vendor.landed_cost} /> <span className="text-sm font-normal text-slate-500">/ {text(`unit.${vendor.quote.unit}`)}</span>
                </p>
              </div>
              <dl className="mt-1 grid grid-cols-2 gap-x-4 text-sm sm:grid-cols-4">
                {vendor.breakdown.map((part) => (
                  <div key={part.id}>
                    <dt className="text-slate-500 dark:text-slate-400">{text(part.label_key)}</dt>
                    <dd><FigureValue figure={part} /></dd>
                  </div>
                ))}
              </dl>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {t("market.leadTime", { days: format.days(vendor.quote.lead_time_days) })}
                {vendor.quote.on_time_rate && <> · {t("market.onTime", { rate: format.probability(vendor.quote.on_time_rate) })}</>}
              </p>
            </li>
          ))}
        </ol>
      ))}
    </section>
  );
}

function Negotiation({ commodities }: { commodities: string[] }) {
  const { t } = useTranslation();
  const text = useServerText();
  const ids = { commodity: useId(), quantity: useId(), price: useId(), days: useId(), error: useId() };
  const [commodity, setCommodity] = useState(commodities.includes("rice_coarse") ? "rice_coarse" : (commodities[0] ?? ""));
  const [quantity, setQuantity] = useState("500");
  const [offer, setOffer] = useState("62");
  const [days, setDays] = useState(30);
  const [invalid, setInvalid] = useState(false);
  const plan = useMutation({ mutationFn: (body: NegotiationRequest) => api.market.negotiate(body) });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const amount = parseAmount(offer);
    setInvalid(amount === null);
    if (amount) plan.mutate({ commodity, quantity: quantity.trim(), offer_price: { amount, currency: "BDT" }, payment_days: days });
  };
  return (
    <section aria-labelledby="h-negotiate" className={card}>
      <h3 id="h-negotiate" className="text-lg font-semibold">{t("market.negotiateTitle")}</h3>
      <SampleLabel />
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("market.negotiateHelp")}</p>
      <form onSubmit={submit} noValidate className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.commodity} className="mb-1 block text-sm font-medium">{t("market.commodity")}</label>
          <select id={ids.commodity} value={commodity} onChange={(e) => setCommodity(e.target.value)} className={field}>
            {commodities.map((name) => <option key={name} value={name}>{text(`commodity.${name}`)}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.quantity} className="mb-1 block text-sm font-medium">{t("market.quantity")}</label>
          <input id={ids.quantity} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={field} />
        </div>
        <div>
          <label htmlFor={ids.price} className="mb-1 block text-sm font-medium">{t("market.offer")}</label>
          <input id={ids.price} inputMode="decimal" value={offer} onChange={(e) => setOffer(e.target.value)} aria-invalid={invalid || undefined} aria-describedby={invalid ? ids.error : undefined} className={field} />
        </div>
        <div>
          <label htmlFor={ids.days} className="mb-1 block text-sm font-medium">{t("market.paymentDays")}</label>
          <select id={ids.days} value={days} onChange={(e) => setDays(Number(e.target.value))} className={field}>
            {[0, 7, 15, 30, 45].map((d) => <option key={d} value={d}>{t("unit.days", { count: d, value: String(d) })}</option>)}
          </select>
        </div>
        {invalid && <p id={ids.error} role="alert" className="text-sm text-red-700 dark:text-red-300 sm:col-span-2">{t("financing.amountInvalid")}</p>}
        <button type="submit" disabled={plan.isPending} className="rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60 sm:col-span-2 sm:w-auto">
          {t("market.makePlan")}
        </button>
      </form>
      {plan.isError && <div className="mt-3"><ErrorState error={plan.error} /></div>}
      {plan.data && (
        <div className="mt-4 space-y-3">
          <dl className="flex flex-wrap gap-x-8 gap-y-2">
            <div>
              <dt className="text-sm text-slate-600 dark:text-slate-400">{t("market.walkAway")}</dt>
              <dd className="text-xl font-semibold"><FigureValue figure={plan.data.walk_away} /></dd>
            </div>
            <div>
              <dt className="text-sm text-slate-600 dark:text-slate-400">{t("market.target")}</dt>
              <dd className="text-xl font-semibold"><FigureValue figure={plan.data.target} /></dd>
            </div>
          </dl>
          {compareDecimal(plan.data.target.value, plan.data.walk_away.value) < 0 && (
            <p role="alert" className="text-sm font-medium text-red-700 dark:text-red-300">{t("market.belowWalkAway")}</p>
          )}
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            {plan.data.steps.map((step) => (
              <li key={step.text_key}>
                <p>{text(step.text_key)}</p>
                <p className="mt-0.5 flex flex-wrap gap-x-4 text-slate-600 dark:text-slate-400">
                  {step.figures.map((fig) => (
                    <span key={fig.id}>{text(fig.label_key)}: <FigureValue figure={fig} className="font-semibold text-slate-900 dark:text-slate-100" /></span>
                  ))}
                </p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

export function MarketScreen() {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  useDocumentTitle(t("nav.market"));
  const prices = useQuery({ queryKey: ["market", "prices"], queryFn: api.market.prices });
  const alerts = useQuery({ queryKey: ["market", "alerts"], queryFn: api.market.alerts });
  const commodities = prices.data?.map((item) => item.commodity) ?? [];
  const live = livePrices(prices.data);
  const published = live ? prices.data?.[0]?.published_on : undefined;
  const sourceUrl = live ? prices.data?.[0]?.latest.source_url : undefined;
  return (
    <section aria-labelledby="h-market" className="space-y-6">
      <h2 id="h-market" className="text-xl font-semibold">{t("nav.market")}</h2>
      {prices.data && (live && published ? (
        <p role="note" className="rounded-xl bg-teal-50 p-3 text-sm text-teal-900 dark:bg-teal-900/30 dark:text-teal-100">
          {t("market.sourceNote", { date: format.date(published, "long") })}{" "}
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="font-semibold underline">
              {t("market.sourceLink")}
            </a>
          )}
        </p>
      ) : (
        <p role="note" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-900/30 dark:text-amber-100">{t("market.sampleNote")}</p>
      ))}

      <section aria-labelledby="h-price-alerts" className="space-y-2">
        <h3 id="h-price-alerts" className="text-lg font-semibold">{t("market.alertsTitle")}</h3>
        {prices.data && !live && <SampleLabel />}
        <QueryView query={alerts} isEmpty={(list) => list.length === 0} empty={t("market.noAlerts")}>
          {(list) => (
            <ul className="space-y-2">
              {list.map((alert) => (
                <li key={alert.id} className={`rounded-xl p-3 text-sm ${alert.direction === "drop" ? "bg-emerald-50 dark:bg-emerald-950/50" : "bg-amber-50 dark:bg-amber-950/50"}`}>
                  <p className="font-semibold">
                    {t(alert.direction === "drop" ? "market.dropped" : "market.rose", { commodity: text(`commodity.${alert.commodity}`) })}{" "}
                    <FigureValue figure={alert.change} />
                  </p>
                  <p className="text-slate-600 dark:text-slate-400">
                    {t(alert.direction === "drop" ? "market.dropAdvice" : "market.riseAdvice")} · {t("market.published", { source: t(`market.source.${alert.source}`), date: format.date(alert.observed_on, "long") })}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-watchlist" className={card}>
        <h3 id="h-watchlist" className="text-lg font-semibold">{t("market.watchTitle")}</h3>
        {prices.data && !live && <SampleLabel />}
        <QueryView query={prices} isEmpty={(list) => list.length === 0} empty={t("market.noWatch")}>
          {(list) => (
            <table className="mt-2 w-full text-sm">
              <caption className="sr-only">{t("market.watchTitle")}</caption>
              <thead className="text-slate-500 dark:text-slate-400">
                <tr>
                  <th scope="col" className="text-left font-medium">{t("market.commodity")}</th>
                  <th scope="col" className="text-right font-medium">{t("market.today")}</th>
                  <th scope="col" className="text-right font-medium">{t("market.median")}</th>
                  <th scope="col" className="text-right font-medium">{t("market.change")}</th>
                </tr>
              </thead>
              <tbody>
                {list.map((item) => {
                  const direction = compareDecimal(item.change_pct, "0");
                  return (
                    <tr key={item.commodity} className="border-t border-slate-100 dark:border-slate-800">
                      <th scope="row" className="py-1.5 text-left font-normal">
                        {text(`commodity.${item.commodity}`)}
                        <span className="block text-xs text-slate-500 dark:text-slate-400">
                          {t("market.published", { source: t(`market.source.${item.latest.source}`), date: format.date(item.latest.observed_on) })}
                        </span>
                      </th>
                      <td className="text-right tabular-nums">{format.money(item.latest.price)} / {text(`unit.${item.unit}`)}</td>
                      <td className="text-right tabular-nums">{format.money(item.median_4w)}</td>
                      <td className={`text-right tabular-nums ${direction > 0 ? "text-amber-700 dark:text-amber-300" : direction < 0 ? "text-emerald-700 dark:text-emerald-300" : ""}`}>
                        {format.percent(item.change_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </QueryView>
      </section>

      {commodities.length > 0 && <VendorRanking commodities={commodities} />}
      {commodities.length > 0 && <Negotiation commodities={commodities} />}
    </section>
  );
}
