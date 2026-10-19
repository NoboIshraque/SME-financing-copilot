// Today: critical alerts pinned on top, cash and runway, today's top 3 actions (P9) with one-tap
// approve, then the other alerts by tier.
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiRequestError } from "../../api/client";
import type { ActionCard, Alert, Recommendation } from "../../api/contracts";
import { api } from "../../api/endpoints";
import { ActionCardView } from "../../components/ActionCardView";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useServerText } from "../../i18n/serverText";
import { useFormat } from "../../i18n/useFormat";
import { AlertCard } from "./AlertCard";
import { ALERT_TIER_ORDER, sortAlerts } from "./alerts";
import { CashNowCard } from "./CashNowCard";

function TopActions({ today, alerts }: { today: UseQueryResult<Recommendation>; alerts: readonly Alert[] }) {
  const { t } = useTranslation();
  const text = useServerText();
  if (today.isPending) return <LoadingState />;

  // Without the copilot router (404), fall back to the alerts' ranked fixes: the cards still come
  // from the cash engine, only the narration is missing.
  const routeMissing = today.isError && today.error instanceof ApiRequestError && today.error.status === 404;
  if (today.isError && !routeMissing) return <ErrorState error={today.error} onRetry={() => void today.refetch()} />;

  const recommendation = today.data;
  if (recommendation?.abstention) {
    const { abstention } = recommendation;
    return (
      <div role="note" className="rounded-2xl border border-slate-300 bg-slate-100 p-4 dark:border-slate-700 dark:bg-slate-800">
        <h4 className="font-semibold">{t("today.abstainTitle")}</h4>
        <p className="mt-1">{text(abstention.message_key)}</p>
        {abstention.missing && abstention.missing.length > 0 && (
          <>
            <p className="mt-2 text-sm font-medium">{t("today.missing")}</p>
            <ul className="mt-1 list-disc pl-5 text-sm">
              {abstention.missing.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    );
  }

  const fallback: ActionCard[] = alerts.flatMap((alert) => alert.fixes ?? []);
  const cards = (recommendation?.action_cards ?? fallback).slice(0, 3);
  if (cards.length === 0) return <EmptyState>{t("today.noActions")}</EmptyState>;
  return (
    <div className="space-y-3">
      {recommendation?.answer_text && <p className="text-slate-700 dark:text-slate-300">{recommendation.answer_text}</p>}
      <ol className="space-y-3">
        {cards.map((card, index) => (
          <li key={card.id}>
            <ActionCardView card={card} primary={index === 0} />
          </li>
        ))}
      </ol>
      {recommendation?.critic_objection && (
        <aside className="rounded-xl border-l-4 border-amber-500 bg-amber-50 p-3 text-sm dark:bg-amber-950/50">
          <p className="font-semibold">{t("today.caseAgainst")}</p>
          <p className="mt-0.5">{recommendation.critic_objection}</p>
        </aside>
      )}
    </div>
  );
}

export function TodayScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("nav.today"));
  const forecast = useQuery({ queryKey: ["cash", "forecast"], queryFn: api.cash.forecast });
  const alerts = useQuery({ queryKey: ["cash", "alerts"], queryFn: api.cash.alerts });
  const today = useQuery({ queryKey: ["copilot", "today"], queryFn: api.copilot.today });

  const sorted = sortAlerts(alerts.data ?? []);
  const pinned = sorted.filter((alert) => alert.tier === "critical");
  const others = sorted.filter((alert) => alert.tier !== "critical");

  return (
    <section aria-labelledby="h-today" className="space-y-6">
      <div>
        <h2 id="h-today" className="text-xl font-semibold">
          {t("nav.today")}
        </h2>
        {forecast.data && (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("today.asOf", { date: format.date(forecast.data.band.as_of, "long") })}
          </p>
        )}
      </div>

      {pinned.length > 0 && (
        <div aria-label={t("alertTier.critical")} className="space-y-3">
          {pinned.map((alert) => (
            <AlertCard key={alert.id} alert={alert} level={3} />
          ))}
        </div>
      )}

      <CashNowCard query={forecast} />

      <section aria-labelledby="h-actions" className="space-y-3">
        <h3 id="h-actions" className="text-lg font-semibold">
          {t("today.actionsTitle")}
        </h3>
        <TopActions today={today} alerts={sorted} />
      </section>

      <section aria-labelledby="h-alerts" className="space-y-3">
        <h3 id="h-alerts" className="text-lg font-semibold">
          {t("today.alertsTitle")}
        </h3>
        {alerts.isPending ? (
          <LoadingState />
        ) : alerts.isError ? (
          <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
        ) : sorted.length === 0 ? (
          <EmptyState>{t("today.noAlerts")}</EmptyState>
        ) : others.length === 0 ? (
          <p className="text-sm text-slate-600 dark:text-slate-400">{t("today.onlyCritical")}</p>
        ) : (
          ALERT_TIER_ORDER.filter((tier) => tier !== "critical").map((tier) => {
            const group = others.filter((alert) => alert.tier === tier);
            if (group.length === 0) return null;
            return (
              <div key={tier} className="space-y-2">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {t(`alertTier.${tier}`)} ({format.number(String(group.length), 0)})
                </h4>
                {group.map((alert) => (
                  <AlertCard key={alert.id} alert={alert} level={5} />
                ))}
              </div>
            );
          })
        )}
      </section>
    </section>
  );
}
