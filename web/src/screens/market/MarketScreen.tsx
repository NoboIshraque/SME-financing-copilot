// Market (N3, N19): watched input prices with honest publication dates, price alerts, vendors
// ranked by landed cost, and a step-by-step negotiation script with the numbers behind it.
// Prices come from TCB's published daily lists (WP-09); a part the server does not serve yet falls
// back to the bundled sample (`orSample`) and carries a "Sample data" label on its own card.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiRequestError } from "../../api/client";
import { compareDecimal } from "../../api/decimal";
import { api } from "../../api/endpoints";
import type { MarketLocation, NegotiationRequest, WatchItem } from "../../api/types";
import { useSession } from "../../auth/session";
import { FigureValue } from "../../components/FigureValue";
import { EmptyState, ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";
import { parseAmount } from "../financing/amount";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";
const LOCATION_KEY = "decisionguard.market.location";
const DISTANCES = [0, 25, 50, 100, 250];

function savedLocation(): string | null {
  try {
    return localStorage.getItem(LOCATION_KEY);
  } catch {
    return null;
  }
}

function saveLocation(id: string) {
  try {
    localStorage.setItem(LOCATION_KEY, id);
  } catch {
    // a private window: the choice lasts for this visit only
  }
}

/** The server's answer when the chosen place has no data for this (yuan prices, no quotes). */
function missing(error: unknown): string | undefined {
  return error instanceof ApiRequestError ? (error.body?.detail?.missing as string | undefined) : undefined;
}

/** Locations grouped for the picker: Bangladesh by division, then China. */
function LocationPicker({ places, value, onChange }: { places: MarketLocation[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  const pickerId = useId();
  const groups = new Map<string, MarketLocation[]>();
  for (const place of places) {
    const group = place.country === "CN" ? t("market.countryCN") : `${t("market.countryBD")} · ${place.division}`;
    groups.set(group, [...(groups.get(group) ?? []), place]);
  }
  return (
    <div>
      <label htmlFor={pickerId} className="mb-1 block text-sm font-medium">{t("market.location")}</label>
      <select id={pickerId} value={value} onChange={(e) => onChange(e.target.value)} className={field}>
        {[...groups.entries()].map(([group, list]) => (
          <optgroup key={group} label={group}>
            {list.map((place) => (
              <option key={place.id} value={place.id}>
                {place.name} ({t(`market.cadence.${place.cadence}`)})
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t("market.locationHelp")}</p>
    </div>
  );
}

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

/** The server has no supplier quote on record for this shop (a self-service shop). */
function noQuotes(error: unknown): boolean {
  return missing(error) === "supplier_quote";
}

function VendorRanking({ commodities, live, location }: { commodities: string[]; live: boolean; location?: string }) {
  const { t } = useTranslation();
  // A self-service shop's own data is live: sample vendors are never shown to it as its own.
  const ownShop = useSession().data?.data_mode === "live";
  const text = useServerText();
  const format = useFormat();
  const ids = { commodity: useId(), quantity: useId(), distance: useId() };
  const [commodity, setCommodity] = useState(commodities.includes("rice_coarse") ? "rice_coarse" : (commodities[0] ?? ""));
  const [quantity, setQuantity] = useState("500");
  const [maxKm, setMaxKm] = useState(0);
  const rank = useMutation({ mutationFn: () => api.market.rankVendors(commodity, quantity.trim(), location, maxKm || undefined) });
  return (
    <section aria-labelledby="h-vendors" className={card}>
      <h3 id="h-vendors" className="text-lg font-semibold">{t("market.vendorsTitle")}</h3>
      {(rank.data ? rank.data.length > 0 && !rank.data.every((v) => v.source) : !live) && <SampleLabel />}
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
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
          <label htmlFor={ids.distance} className="mb-1 block text-sm font-medium">{t("market.maxDistance")}</label>
          <select id={ids.distance} value={maxKm} onChange={(e) => setMaxKm(Number(e.target.value))} className={field}>
            {DISTANCES.map((km) => (
              <option key={km} value={km}>{km === 0 ? t("market.anyDistance") : t("market.withinKm", { km: format.number(String(km), 0) })}</option>
            ))}
          </select>
        </div>
        <div className="flex items-end">
          <button type="button" onClick={() => rank.mutate()} disabled={rank.isPending} className="w-full rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
            {t("market.rank")}
          </button>
        </div>
      </div>
      {rank.isError && (noQuotes(rank.error) ? (
        <div className="mt-3"><EmptyState>{t("market.addQuote")}</EmptyState></div>
      ) : (
        <div className="mt-3"><ErrorState error={rank.error} /></div>
      ))}
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
                {vendor.vendor_location && vendor.distance_km !== undefined && (
                  <> · {t("market.vendorPlace", { place: vendor.vendor_location.name, division: vendor.vendor_location.division, km: format.number(vendor.distance_km, 0) })}</>
                )}
              </p>
            </li>
          ))}
        </ol>
      ))}
    </section>
  );
}

function Negotiation({ commodities, live, location }: { commodities: string[]; live: boolean; location?: string }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
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
    if (amount) plan.mutate({ commodity, quantity: quantity.trim(), offer_price: { amount, currency: "BDT" }, payment_days: days, ...(location ? { location } : {}) });
  };
  return (
    <section aria-labelledby="h-negotiate" className={card}>
      <h3 id="h-negotiate" className="text-lg font-semibold">{t("market.negotiateTitle")}</h3>
      {(plan.data ? !plan.data.cost_of_money : !live) && <SampleLabel />}
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
      {plan.isError && (missing(plan.error) === "financing_catalogue" ? (
        <div className="mt-3"><EmptyState>{t("market.noFinancingHere")}</EmptyState></div>
      ) : (
        <div className="mt-3"><ErrorState error={plan.error} /></div>
      ))}
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
          {plan.data.cost_of_money && plan.data.market_price && (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {t("market.priceUsed", {
                price: format.money(plan.data.market_price.price),
                unit: text(`unit.${plan.data.market_price.unit}`),
                date: format.date(plan.data.market_price.observed_on),
              })}
              {" · "}
              {t("market.cost_of_money")}: <FigureValue figure={plan.data.cost_of_money} className="font-semibold" />
            </p>
          )}
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
  const places = useQuery({ queryKey: ["market", "locations"], queryFn: api.market.locations });
  const [chosen, setChosen] = useState<string | null>(savedLocation);
  const known = places.data ?? [];
  const location = (known.find((place) => place.id === chosen) ?? known[0])?.id;
  const choose = (id: string) => {
    setChosen(id);
    saveLocation(id);
  };
  const prices = useQuery({ queryKey: ["market", "prices", location], queryFn: () => api.market.prices(location), enabled: places.isFetched });
  const alerts = useQuery({ queryKey: ["market", "alerts", location], queryFn: () => api.market.alerts(location), enabled: places.isFetched });
  const commodities = prices.data?.map((item) => item.commodity) ?? [];
  const live = livePrices(prices.data);
  const first = live ? prices.data?.[0] : undefined;
  const published = first?.published_on;
  const sourceUrl = first?.latest.source_url;
  return (
    <section aria-labelledby="h-market" className="space-y-6">
      <h2 id="h-market" className="text-xl font-semibold">{t("nav.market")}</h2>
      {known.length > 0 && location && <LocationPicker places={known} value={location} onChange={choose} />}
      {prices.data && (live && published ? (
        <p role="note" className="rounded-xl bg-teal-50 p-3 text-sm text-teal-900 dark:bg-teal-900/30 dark:text-teal-100">
          {t("market.sourceNoteAt", {
            source: t(`market.sourceName.${first?.latest.source ?? "tcb"}`),
            place: first?.latest.market ?? "",
            date: format.date(published, "long"),
          })}{" "}
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

      {commodities.length > 0 && <VendorRanking key={`v-${location}`} commodities={commodities} live={live} location={location} />}
      {commodities.length > 0 && <Negotiation key={`n-${location}`} commodities={commodities} live={live} location={location} />}
    </section>
  );
}
