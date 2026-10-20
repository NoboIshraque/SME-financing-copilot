// Messages & approvals inbox (N2, P2): everything waiting for a decision, and message drafts that
// go out only after approval (copy, email or in-app; no Telegram/WhatsApp, P10 was cut).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { newIdempotencyKey } from "../../actions/useApproveAction";
import type { MessageDraft } from "../../api/contracts";
import { api } from "../../api/endpoints";
import { useRequiredSession } from "../../auth/session";
import { StepUpDialog } from "../../auth/StepUpDialog";
import { ActionCardView } from "../../components/ActionCardView";
import { Icon } from "../../components/Icon";
import { ErrorState, QueryView } from "../../components/States";
import { TierBadge } from "../../components/TierBadge";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useFormat } from "../../i18n/useFormat";

function DraftCard({ draft }: { draft: MessageDraft }) {
  const { t } = useTranslation();
  const session = useRequiredSession();
  const queryClient = useQueryClient();
  const key = useRef<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const recipient = draft.variables?.recipient_label ?? draft.recipient_token;
  const update = (next: MessageDraft) =>
    queryClient.setQueryData<MessageDraft[]>(["messages", "drafts"], (list) => list?.map((d) => (d.id === next.id ? next : d)));
  // A message leaves DecisionGuard (EXECUTE): the owner approves it with a fresh code.
  const approve = useMutation({
    mutationFn: (stepUpCode: string) =>
      api.messages.approve(draft.id, { idempotencyKey: (key.current ??= newIdempotencyKey()), stepUpCode }),
    onSuccess: update,
  });
  const send = useMutation({
    mutationFn: () => api.messages.send(draft.id, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: update,
  });
  const canApprove = session.principal.role === "owner";
  const copy = async () => {
    await navigator.clipboard.writeText(draft.body);
    setCopied(true);
  };
  const error = approve.error ?? send.error;
  const titleId = useId();

  return (
    <article aria-labelledby={titleId} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TierBadge tier={draft.tier} />
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {t(`messages.channel.${draft.channel}`)} · {t(`language.${draft.language}`)} · {t(`messages.status.${draft.status ?? "draft"}`)}
        </span>
      </div>
      <h4 id={titleId} className="mt-2 font-semibold">
        {t(`messages.purpose.${draft.purpose}`)} · {recipient}
      </h4>
      <blockquote lang={draft.language} className="mt-2 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
        {draft.body}
      </blockquote>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {draft.status === "draft" &&
          (canApprove ? (
            <button type="button" onClick={() => setStepUpOpen(true)} disabled={approve.isPending} className="rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
              {t("messages.approve")}
            </button>
          ) : (
            <p className="text-sm">{t("actionCard.roleCannot")}</p>
          ))}
        {draft.status === "approved" && draft.channel === "copy" && (
          <button type="button" onClick={() => void copy()} className="rounded-xl border border-teal-700 px-4 py-2.5 font-semibold text-teal-800 dark:border-teal-400 dark:text-teal-200">
            {copied ? t("messages.copied") : t("messages.copy")}
          </button>
        )}
        {draft.status === "approved" && draft.channel !== "copy" && (
          <button type="button" onClick={() => send.mutate()} disabled={send.isPending} className="rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
            {t("messages.send")}
          </button>
        )}
        {draft.status === "sent" && (
          <p className="flex items-center gap-1 font-medium text-emerald-800 dark:text-emerald-300">
            <Icon name="check" /> {t("messages.sent")}
          </p>
        )}
      </div>
      {error && <div className="mt-2"><ErrorState error={error} /></div>}
      <StepUpDialog
        open={stepUpOpen}
        summary={<p className="font-semibold">{t(`messages.purpose.${draft.purpose}`)} · {recipient}</p>}
        onConfirm={(code) => approve.mutateAsync(code)}
        onClose={() => setStepUpOpen(false)}
      />
    </article>
  );
}

export function MessagesScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("nav.messages"));
  const pending = useQuery({ queryKey: ["approvals", "pending"], queryFn: api.approvals.pending });
  const drafts = useQuery({ queryKey: ["messages", "drafts"], queryFn: api.messages.drafts });
  return (
    <section aria-labelledby="h-messages" className="space-y-6">
      <h2 id="h-messages" className="text-xl font-semibold">{t("nav.messages")}</h2>
      <section aria-labelledby="h-pending" className="space-y-3">
        <h3 id="h-pending" className="text-lg font-semibold">{t("messages.pendingTitle")}</h3>
        <QueryView query={pending} isEmpty={(list) => list.length === 0} empty={t("messages.nothingPending")}>
          {(list) => (
            <ul className="space-y-3">
              {list.map(({ approval, card }) => (
                <li key={approval.id}>
                  <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">
                    {t("messages.requestedBy", { who: approval.requested_by, when: format.dateTime(approval.created_at) })}
                  </p>
                  <ActionCardView card={card} approvalId={approval.id} />
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
      <section aria-labelledby="h-drafts" className="space-y-3">
        <h3 id="h-drafts" className="text-lg font-semibold">{t("messages.draftsTitle")}</h3>
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("messages.draftsHelp")}</p>
        <QueryView query={drafts} isEmpty={(list) => list.length === 0} empty={t("messages.noDrafts")}>
          {(list) => (
            <ul className="space-y-3">
              {list.map((draft) => (
                <li key={draft.id}><DraftCard draft={draft} /></li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>
    </section>
  );
}
