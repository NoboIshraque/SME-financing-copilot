// Copilot panel: ask in any of the three languages; every answer comes back as a decision card,
// never as free numbers. Also the entry point for uploading statements and ledger photos.
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Recommendation } from "../api/contracts";
import { api } from "../api/endpoints";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { ErrorState } from "../components/States";
import { describeError } from "../i18n/serverText";
import { RecommendationCard } from "./RecommendationCard";
import { UploadDialog } from "./UploadDialog";

interface Turn {
  id: number;
  question: string;
  answer?: Recommendation;
  error?: unknown;
}

const SUGGESTIONS = ["copilot.suggest.salary", "copilot.suggest.chase", "copilot.suggest.loan"] as const;

export function CopilotPanel() {
  const { t } = useTranslation();
  const titleId = useId();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = useMutation({ mutationFn: (q: string) => api.copilot.ask(q) });

  const send = (text: string) => {
    const q = text.trim();
    if (!q || ask.isPending) return;
    const id = turns.length + 1;
    setTurns((list) => [...list, { id, question: q }]);
    setQuestion("");
    ask.mutate(q, {
      onSuccess: (answer) => setTurns((list) => list.map((turn) => (turn.id === id ? { ...turn, answer } : turn))),
      onError: (error) => setTurns((list) => list.map((turn) => (turn.id === id ? { ...turn, error } : turn))),
    });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(question);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-20 right-4 z-30 flex items-center gap-2 rounded-full bg-teal-700 px-4 py-3 font-semibold text-white shadow-lg hover:bg-teal-800 md:bottom-6"
      >
        <Icon name="sparkle" />
        {t("copilot.open")}
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} labelledBy={titleId} placement="right" panelClassName="flex h-dvh w-full max-w-lg flex-col">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 id={titleId} className="text-lg font-semibold">{t("copilot.title")}</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">{t("copilot.subtitle")}</p>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label={t("provenance.close")} className="rounded-lg p-2 hover:bg-slate-100 dark:hover:bg-slate-800">
            <Icon name="close" />
          </button>
        </div>
        <button type="button" onClick={() => {
            setOpen(false);
            setUploading(true);
          }} className="mt-3 flex items-center gap-2 self-start rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium dark:border-slate-600">
          <Icon name="upload" className="h-4 w-4" />
          {t("upload.open")}
        </button>

        <div className="mt-4 flex-1 space-y-5 overflow-y-auto" aria-live="polite">
          {turns.length === 0 && (
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">{t("copilot.tryAsking")}</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {SUGGESTIONS.map((key) => (
                  <li key={key}>
                    <button type="button" onClick={() => send(t(key))} className="rounded-full bg-teal-50 px-3 py-1.5 text-sm text-teal-900 hover:bg-teal-100 dark:bg-teal-950 dark:text-teal-100">
                      {t(key)}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {turns.map((turn) => (
            <div key={turn.id} className="space-y-2">
              <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-teal-700 px-3 py-2 text-white">{turn.question}</p>
              {turn.answer ? (
                <RecommendationCard recommendation={turn.answer} />
              ) : turn.error ? (
                describeError(turn.error).key === "error.input_quarantined" ? (
                  <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm font-medium text-red-900 dark:bg-red-950 dark:text-red-100">
                    {t("error.input_quarantined")}
                  </p>
                ) : (
                  <ErrorState error={turn.error} />
                )
              ) : (
                <p aria-busy="true" className="text-sm text-slate-500">{t("copilot.thinking")}</p>
              )}
            </div>
          ))}
        </div>

        <form onSubmit={submit} className="mt-3 flex gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
          <label htmlFor={inputId} className="sr-only">{t("copilot.ask")}</label>
          <input
            id={inputId}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={t("copilot.placeholder")}
            maxLength={500}
            className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-600 dark:bg-slate-800"
          />
          <button type="submit" disabled={!question.trim() || ask.isPending} className="rounded-xl bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-60">
            {t("copilot.send")}
          </button>
        </form>
      </Dialog>
      <UploadDialog open={uploading} onClose={() => setUploading(false)} />
    </>
  );
}
