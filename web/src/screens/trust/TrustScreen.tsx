// Trust & audit (P2, P8, N17): the hash-chained audit log and its verification, recent events,
// every abstention with what was missing, and the nightly audit drill score.
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../api/endpoints";
import { FigureValue } from "../../components/FigureValue";
import { QueryView } from "../../components/States";
import { TierBadge } from "../../components/TierBadge";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";

export function TrustScreen() {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  useDocumentTitle(t("nav.trust"));
  const chain = useQuery({ queryKey: ["trust", "audit"], queryFn: api.trust.auditVerify });
  const events = useQuery({ queryKey: ["trust", "events"], queryFn: api.trust.auditEvents });
  const abstentions = useQuery({ queryKey: ["trust", "abstentions"], queryFn: api.copilot.abstentions });
  const drill = useQuery({ queryKey: ["trust", "drill"], queryFn: api.trust.drill });
  return (
    <section aria-labelledby="h-trust" className="space-y-6">
      <h2 id="h-trust" className="text-xl font-semibold">{t("nav.trust")}</h2>

      <section aria-labelledby="h-chain" className={card}>
        <h3 id="h-chain" className="text-lg font-semibold">{t("trust.chainTitle")}</h3>
        <QueryView query={chain}>
          {(data) => (
            <>
              <p className={`mt-2 text-lg font-semibold ${data.valid ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}`}>
                {data.valid ? t("trust.chainValid", { count: data.length }) : t("trust.chainBroken", { seq: data.broken_at_seq ?? "?" })}
              </p>
              <p className="mt-1 break-all font-mono text-xs text-slate-600 dark:text-slate-400">{t("trust.head", { hash: data.head_hash })}</p>
              {data.anchor && <p className="mt-1 text-sm">{t(`mesh.chain.${data.anchor.chain}`)} · {format.dateTime(data.anchor.anchored_at)}</p>}
              <button type="button" onClick={() => void chain.refetch()} className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium dark:border-slate-600">
                {t("trust.verifyAgain")}
              </button>
            </>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-drill" className={card}>
        <h3 id="h-drill" className="text-lg font-semibold">{t("trust.drillTitle")}</h3>
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("trust.drillHelp")}</p>
        <QueryView query={drill}>
          {(data) => (
            <p className="mt-2">
              <FigureValue figure={data.catch_rate} className="text-3xl font-bold" />{" "}
              <span>{t("trust.drillCaught", { caught: data.caught, planted: data.planted })}</span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">{t("trust.drillRun", { when: format.dateTime(data.run_at) })}</span>
            </p>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-events" className={card}>
        <h3 id="h-events" className="text-lg font-semibold">{t("trust.eventsTitle")}</h3>
        <QueryView query={events} isEmpty={(list) => list.length === 0} empty={t("trust.noEvents")}>
          {(list) => (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[30rem] text-sm">
                <caption className="sr-only">{t("trust.eventsTitle")}</caption>
                <thead className="text-left text-slate-500 dark:text-slate-400">
                  <tr>
                    <th scope="col" className="font-medium">#</th>
                    <th scope="col" className="font-medium">{t("trust.when")}</th>
                    <th scope="col" className="font-medium">{t("trust.who")}</th>
                    <th scope="col" className="font-medium">{t("trust.what")}</th>
                    <th scope="col" className="font-medium">{t("trust.tier")}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((event) => (
                    <tr key={event.seq} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1 tabular-nums">{format.number(String(event.seq), 0)}</td>
                      <td>{format.dateTime(event.at)}</td>
                      <td>{event.actor}</td>
                      <td>{text(`audit.${event.action}`)}{event.target ? ` · ${event.target}` : ""}</td>
                      <td>{event.tier ? <TierBadge tier={event.tier} /> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryView>
      </section>

      <section aria-labelledby="h-abstentions" className="space-y-2">
        <h3 id="h-abstentions" className="text-lg font-semibold">{t("trust.abstentionsTitle")}</h3>
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("trust.abstentionsHelp")}</p>
        <QueryView query={abstentions} isEmpty={(list) => list.length === 0} empty={t("trust.noAbstentions")}>
          {(list) => (
            <ul className="space-y-2">
              {list.map((entry) => (
                <li key={entry.id} className={card}>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{format.dateTime(entry.at)}</p>
                  <p className="font-medium">“{entry.question}”</p>
                  <p className="mt-1 text-sm">{text(entry.abstention.message_key)}</p>
                  {entry.abstention.missing && entry.abstention.missing.length > 0 && (
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t("trust.missing", { items: entry.abstention.missing.join("; ") })}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
    </section>
  );
}
