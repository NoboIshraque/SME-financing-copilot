// Step-up check for EXECUTE-tier actions: the owner re-enters a fresh TOTP code (CLAUDE.md rule 4).
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { describeError, useServerText } from "../i18n/serverText";
import { CodeField, normalizeCode } from "./CodeField";

interface StepUpDialogProps {
  open: boolean;
  /** What is being approved, shown above the code field. */
  summary?: ReactNode;
  /** Runs the action with the code; a rejection keeps the dialog open and shows the error. */
  onConfirm: (code: string) => Promise<unknown>;
  onClose: () => void;
}

export function StepUpDialog({ open, summary, onConfirm, onClose }: StepUpDialogProps) {
  const titleId = useId();
  const helpId = useId();
  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId} describedBy={helpId}>
      <StepUpForm titleId={titleId} helpId={helpId} summary={summary} onConfirm={onConfirm} onClose={onClose} />
    </Dialog>
  );
}

function StepUpForm({
  titleId,
  helpId,
  summary,
  onConfirm,
  onClose,
}: Omit<StepUpDialogProps, "open"> & { titleId: string; helpId: string }) {
  const { t } = useTranslation();
  const text = useServerText();
  const codeId = useId();
  const errorId = useId();
  const [code, setCode] = useState("");
  const [error, setError] = useState<{ key: string; values: Record<string, string> } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const normalized = normalizeCode(code);
    if (!normalized) {
      setError({ key: "auth.codeFormat", values: {} });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(normalized);
      onClose();
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold">
        <Icon name="lock" />
        {t("stepUp.title")}
      </h2>
      {summary && <div className="mt-3 rounded-xl bg-slate-100 p-3 text-sm dark:bg-slate-800">{summary}</div>}
      <p id={helpId} className="mt-3 text-sm text-slate-600 dark:text-slate-400">
        {t("stepUp.help")}
      </p>
      <div className="mt-4">
        <CodeField
          id={codeId}
          label={t("auth.code")}
          value={code}
          onChange={setCode}
          describedBy={error ? errorId : undefined}
          invalid={Boolean(error)}
        />
      </div>
      {error && (
        <p id={errorId} role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
          {text(error.key, error.values)}
        </p>
      )}
      <div className="mt-5 flex gap-3">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 rounded-xl border border-slate-300 px-4 py-3 font-medium dark:border-slate-600"
        >
          {t("common.cancel")}
        </button>
        <button
          type="submit"
          disabled={busy}
          className="flex-1 rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {busy ? t("stepUp.confirming") : t("stepUp.confirm")}
        </button>
      </div>
    </form>
  );
}
