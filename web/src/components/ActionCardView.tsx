// One pre-checked action (P9 "rails, not chat"): what it does, its effect and cost, its permission
// tier, and a single button. EXECUTE asks for a fresh TOTP code; DENY never shows a button.
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { abilityFor } from "../actions/permissions";
import { useApproveAction } from "../actions/useApproveAction";
import type { ActionCard } from "../api/contracts";
import { StepUpDialog } from "../auth/StepUpDialog";
import { useRequiredSession } from "../auth/session";
import { describeError, useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";
import { SCREENS, screenPath, type Screen } from "../navigation";
import { FigureValue } from "./FigureValue";
import { Icon } from "./Icon";
import { TierBadge } from "./TierBadge";

function payloadText(card: ActionCard, key: string): string | null {
  const value = card.payload?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function targetScreen(card: ActionCard): Screen {
  const screen = payloadText(card, "screen");
  return (SCREENS as readonly string[]).includes(screen ?? "") ? (screen as Screen) : "today";
}

export function ActionCardView({ card, primary = false }: { card: ActionCard; primary?: boolean }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const navigate = useNavigate();
  const session = useRequiredSession();
  const approve = useApproveAction(card);
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const ability = abilityFor(card.tier, session.principal.role);
  const title = text(card.title_key);
  const titleId = useId();

  const counterparty = payloadText(card, "counterparty_label");
  const dueDate = payloadText(card, "due_date");
  const newDate = payloadText(card, "new_date");
  const invoiceCount = payloadText(card, "invoice_count");
  const details = [
    counterparty,
    invoiceCount && t("actionCard.invoices", { count: Number(invoiceCount) }),
    dueDate && t("actionCard.dueDate", { date: format.date(dueDate) }),
    newDate && t("actionCard.newDate", { date: format.date(newDate) }),
  ].filter(Boolean);

  const buttonLabel =
    card.tier === "READ"
      ? t("actionCard.open")
      : card.tier === "EXECUTE"
        ? t("actionCard.approveWithCode")
        : card.tier === "DRAFT"
          ? t("actionCard.approveDraft")
          : t("actionCard.markDone");

  const onPress = () => {
    if (card.tier === "READ") navigate(screenPath(targetScreen(card)));
    else if (card.tier === "EXECUTE") setStepUpOpen(true);
    else approve.mutate(undefined);
  };

  const error = approve.isError && card.tier !== "EXECUTE" ? describeError(approve.error) : null;
  const buttonStyle = primary
    ? "bg-teal-700 text-white hover:bg-teal-800"
    : "border border-teal-700 text-teal-800 hover:bg-teal-50 dark:border-teal-400 dark:text-teal-200 dark:hover:bg-teal-950";

  return (
    <article
      aria-labelledby={titleId}
      className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TierBadge tier={card.tier} />
        {card.expires_at && !approve.isSuccess && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {t("actionCard.expires", { when: format.dateTime(card.expires_at) })}
          </span>
        )}
      </div>
      <h4 id={titleId} className="mt-2 font-semibold">
        {title}
      </h4>
      {details.length > 0 && <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-400">{details.join(" · ")}</p>}

      {(card.impact || card.cost) && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {card.impact && (
            <div>
              <dt className="text-slate-500 dark:text-slate-400">{text(card.impact.label_key)}</dt>
              <dd className="text-lg font-semibold">
                <FigureValue figure={card.impact} />
              </dd>
            </div>
          )}
          {card.cost && (
            <div>
              <dt className="text-slate-500 dark:text-slate-400">{t("actionCard.cost")}</dt>
              <dd className="text-lg font-semibold">
                <FigureValue figure={card.cost} />
              </dd>
            </div>
          )}
        </dl>
      )}

      <div className="mt-4">
        {approve.isSuccess ? (
          <p className="flex items-center gap-2 font-medium text-emerald-800 dark:text-emerald-300">
            <Icon name="check" />
            {t("actionCard.approved")}
          </p>
        ) : ability === "never" ? (
          <p className="text-sm font-medium text-red-800 dark:text-red-300">{t("actionCard.never")}</p>
        ) : ability === "owner_only" || ability === "role_cannot" ? (
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {ability === "owner_only" ? t("actionCard.ownerOnly") : t("actionCard.roleCannot")}
          </p>
        ) : (
          <button
            type="button"
            onClick={onPress}
            disabled={approve.isPending}
            aria-describedby={titleId}
            className={`w-full rounded-xl px-4 py-3 font-semibold disabled:opacity-60 sm:w-auto ${buttonStyle}`}
          >
            {buttonLabel}
          </button>
        )}
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
            {text(error.key, error.values)}
          </p>
        )}
      </div>

      <StepUpDialog
        open={stepUpOpen}
        summary={
          <>
            <p className="font-semibold">{title}</p>
            {details.length > 0 && <p>{details.join(" · ")}</p>}
          </>
        }
        onConfirm={(code) => approve.mutateAsync(code)}
        onClose={() => setStepUpOpen(false)}
      />
    </article>
  );
}
