// One copilot answer, shown as a decision card: narration, checked claims, figures, up to three
// action cards, the critic's case against, model agreement and stability, or a clear abstention.
import { useTranslation } from "react-i18next";

import type { CheckStatus, Recommendation } from "../api/contracts";
import { ActionCardView } from "../components/ActionCardView";
import { FigureValue } from "../components/FigureValue";
import { StabilityBar } from "../components/StabilityBar";
import { useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";
import { HELP_TOPICS } from "./suggestions";

const CHECK_STYLE: Record<CheckStatus, string> = {
  verified: "text-emerald-700 dark:text-emerald-300",
  rejected: "text-red-700 line-through dark:text-red-300",
  unverifiable: "text-amber-700 dark:text-amber-300",
};

const HELP_KEY = "copilot.help.intro";
const MAX_RETRY_SUGGESTIONS = 3;

interface Props {
  recommendation: Recommendation;
  /** The signed-in role's suggested questions (i18n keys), offered when a question is not understood. */
  suggestions?: readonly string[];
  onAsk?: (question: string) => void;
}

function Suggestions({ keys, onAsk }: { keys: readonly string[]; onAsk?: (question: string) => void }) {
  const { t } = useTranslation();
  if (!onAsk || keys.length === 0) return null;
  return (
    <>
      <p className="mt-3 text-sm font-medium">{t("copilot.tryInstead")}</p>
      <ul className="mt-1 flex flex-wrap gap-2">
        {keys.map((key) => (
          <li key={key}>
            <button type="button" onClick={() => onAsk(t(key))} className="rounded-full bg-white px-3 py-1.5 text-sm text-teal-900 hover:bg-teal-50 dark:bg-slate-900 dark:text-teal-100">
              {t(key)}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export function RecommendationCard({ recommendation, suggestions = [], onAsk }: Props) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const { abstention, agreement } = recommendation;
  const retry = suggestions.slice(0, MAX_RETRY_SUGGESTIONS);

  if (abstention?.message_key === HELP_KEY) {
    return (
      <div role="note" className="rounded-2xl border border-teal-200 bg-teal-50 p-4 dark:border-teal-900 dark:bg-teal-950/50">
        <p className="font-semibold">{t("copilot.help.title")}</p>
        <p className="mt-1">{t("copilot.help.intro")}</p>
        <ul className="mt-2 list-disc pl-5 text-sm">
          {HELP_TOPICS.map((topic) => <li key={topic}>{t(`copilot.help.can.${topic}`)}</li>)}
        </ul>
        <Suggestions keys={retry} onAsk={onAsk} />
      </div>
    );
  }

  if (abstention?.reason === "out_of_scope") {
    // Not understood, or a part cut from this version: say so kindly and offer what works.
    return (
      <div role="note" className="rounded-2xl border border-slate-300 bg-slate-100 p-4 dark:border-slate-700 dark:bg-slate-800">
        <p className="font-semibold">{t("copilot.notYet")}</p>
        <p className="mt-1">{text(abstention.message_key)}</p>
        <Suggestions keys={retry} onAsk={onAsk} />
      </div>
    );
  }

  if (abstention) {
    return (
      <div role="note" className="rounded-2xl border border-slate-300 bg-slate-100 p-4 dark:border-slate-700 dark:bg-slate-800">
        <p className="font-semibold">{t("copilot.abstained")}</p>
        <p className="mt-1">{text(abstention.message_key)}</p>
        {abstention.missing && abstention.missing.length > 0 && (
          <>
            <p className="mt-2 text-sm font-medium">{t("today.missing")}</p>
            <ul className="mt-1 list-disc pl-5 text-sm">{abstention.missing.map((item) => <li key={item}>{item}</li>)}</ul>
          </>
        )}
      </div>
    );
  }

  const checks = new Map((recommendation.checks ?? []).map((check) => [check.claim_id, check]));
  const agreeing = agreement ? agreement.votes.filter((vote) => vote.choice === agreement.winning_choice).length : 0;
  return (
    <div className="space-y-3">
      {recommendation.answer_text && <p>{recommendation.answer_text}</p>}
      {recommendation.figures && recommendation.figures.length > 0 && (
        <p className="flex flex-wrap gap-x-4 text-sm">
          {recommendation.figures.map((fig) => (
            <span key={fig.id}>{text(fig.label_key)}: <FigureValue figure={fig} className="font-semibold" /></span>
          ))}
        </p>
      )}
      {recommendation.claims && recommendation.claims.length > 0 && (
        <div>
          <p className="text-sm font-medium">{t("copilot.claims")}</p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {recommendation.claims.map((claim) => {
              const status = checks.get(claim.id)?.status ?? "unverifiable";
              return (
                <li key={claim.id} className={CHECK_STYLE[status]}>
                  <span aria-hidden="true">{status === "verified" ? "✓ " : status === "rejected" ? "✗ " : "? "}</span>
                  {claim.text} <span className="text-xs">({t(`copilot.check.${status}`)})</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {recommendation.action_cards && recommendation.action_cards.length > 0 && (
        <ol className="space-y-2">
          {recommendation.action_cards.map((card, index) => (
            <li key={card.id}><ActionCardView card={card} primary={index === 0} /></li>
          ))}
        </ol>
      )}
      {recommendation.critic_objection && (
        <aside className="rounded-xl border-l-4 border-amber-500 bg-amber-50 p-3 text-sm dark:bg-amber-950/50">
          <p className="font-semibold">{t("today.caseAgainst")}</p>
          <p className="mt-0.5">{recommendation.critic_objection}</p>
        </aside>
      )}
      {agreement && (
        <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
          <p className="font-medium">
            {t("copilot.agreement", { agree: agreeing, total: agreement.votes.length, rate: format.probability(agreement.agreement_rate) })}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t("copilot.threshold", { threshold: format.probability(agreement.threshold), stakes: t(`copilot.stakes.${agreement.stakes}`, { defaultValue: agreement.stakes }) })}
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-teal-800 dark:text-teal-300">{t("copilot.votes")}</summary>
            <ul className="mt-1 text-xs">
              {agreement.votes.map((vote) => <li key={vote.model} className="font-mono">{vote.model} → {vote.choice}</li>)}
            </ul>
          </details>
        </div>
      )}
      {recommendation.stability && <StabilityBar report={recommendation.stability} />}
    </div>
  );
}
