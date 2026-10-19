// Trust & audit (P2, P8, N17): the hash-chained audit log and its verification, recent events,
// every abstention with what was missing.
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../api/endpoints";
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
  const anchors = useQuery({ queryKey: ["trust", "anchors"], queryFn: api.trust.auditAnchors });
  const latestAnchor = anchors.data?.[0];
  const events = useQuery({ queryKey: ["trust", "events"], queryFn: api.trust.auditEvents });
  const abstentions = useQuery({ queryKey: ["trust", "abstentions"], queryFn: api.copilot.abstentions });
  return (
    <section aria-labelledby="h-trust" className="space-y-6">
      <h2 id="h-trust" className="text-xl font-semibold">{t("nav.trust")}</h2>

      <section aria-labelledby="h-chain" className={card}>
        <h3 id="h-chain" className="text-lg font-semibold">{t("trust.chainTitle")}</h3>
        <QueryView query={chain}>
          {(data) => (
            <>
              <p className={`mt-2 text-lg font-semibold ${data.valid ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}`}>
                {data.valid ? t("trust.chainValid", { count: data.length, value: format.number(String(data.length), 0) }) : t("trust.chainBroken", { seq: data.first_bad_seq ?? "?" })}
              </p>
              <p className="mt-1 break-all font-mono text-xs text-slate-600 dark:text-slate-400">{t("trust.head", { hash: data.head_hash })}</p>
              {!data.valid && data.reason && <p className="mt-1 text-sm">{data.reason}</p>}
              {latestAnchor && (
                <p className="mt-1 text-sm">
                  {t(`mesh.chain.${latestAnchor.chain}`)} · {format.dateTime(latestAnchor.anchored_at)}
                  {latestAnchor.tx_hash && <span className="block break-all font-mono text-xs">{t("mesh.tx", { hash: latestAnchor.tx_hash })}</span>}
                </p>
              )}
              <button type="button" onClick={() => void chain.refetch()} className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium dark:border-slate-600">
                {t("trust.verifyAgain")}
              </button>
            </>
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
                  <p className="font-medium"><q>{entry.question}</q></p>
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
