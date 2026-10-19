// Upload flow (WP-02, P4): a bKash/Nagad/bank statement or a baki-khata photo is previewed first;
// the owner confirms rows (OCR rows with low confidence start unticked) and only then commits.
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { IngestPreview } from "../api/contracts";
import { api } from "../api/endpoints";
import { Dialog } from "../components/Dialog";
import { ErrorState } from "../components/States";
import { useServerText } from "../i18n/serverText";
import { useFormat } from "../i18n/useFormat";

function initialRows(preview: IngestPreview): Set<string> {
  const rows = new Set<string>((preview.transactions ?? []).map((tx) => tx.source_ref));
  for (const draft of preview.drafts ?? []) if (!draft.flagged) rows.add(draft.row_ref);
  return rows;
}

export function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const text = useServerText();
  const format = useFormat();
  const titleId = useId();
  const fileId = useId();
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const preview = useMutation({
    mutationFn: (file: File) => api.ingest.preview(file),
    onSuccess: (result) => setConfirmed(initialRows(result)),
  });
  const commit = useMutation({
    mutationFn: (data: IngestPreview) => api.ingest.commit({ preview_id: data.preview_id, file_digest: data.file_digest, confirmed_rows: [...confirmed] }),
  });
  const data = preview.data;
  const toggle = (row: string) =>
    setConfirmed((current) => {
      const next = new Set(current);
      if (next.has(row)) next.delete(row);
      else next.add(row);
      return next;
    });

  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId}>
      <h2 id={titleId} className="text-lg font-semibold">{t("upload.title")}</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t("upload.help")}</p>
      <label htmlFor={fileId} className="mt-4 block text-sm font-medium">{t("upload.choose")}</label>
      <input
        id={fileId}
        type="file"
        accept=".csv,.xlsx,.xls,image/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          commit.reset();
          if (file) preview.mutate(file);
        }}
        className="mt-1 block w-full text-sm"
      />
      {preview.isPending && <p aria-busy="true" className="mt-3 text-sm">{t("upload.reading")}</p>}
      {preview.isError && <div className="mt-3"><ErrorState error={preview.error} /></div>}

      {data && !commit.isSuccess && (
        <div className="mt-4 space-y-3 text-sm">
          <p className="font-medium">{t(`upload.format.${data.source_format}`)}</p>
          {data.transactions && data.transactions.length > 0 && (
            <p>{t("upload.transactions", { count: data.transactions.length })}</p>
          )}
          {data.duplicates_skipped ? <p>{t("upload.duplicates", { count: data.duplicates_skipped })}</p> : null}
          {data.unparsed && data.unparsed.length > 0 && (
            <div>
              <p className="font-medium">{t("upload.unparsed")}</p>
              <ul className="list-disc pl-5">
                {data.unparsed.map((row) => <li key={row.row_ref}>{row.row_ref}: {text(row.reason_key)}</li>)}
              </ul>
            </div>
          )}
          {data.drafts && data.drafts.length > 0 && (
            <fieldset>
              <legend className="font-medium">{t("upload.confirmRows")}</legend>
              {data.drafts.map((draft) => (
                <label key={draft.row_ref} className={`mt-1 flex items-center gap-2 rounded-lg p-2 ${draft.flagged ? "bg-amber-50 dark:bg-amber-950/50" : ""}`}>
                  <input type="checkbox" checked={confirmed.has(draft.row_ref)} onChange={() => toggle(draft.row_ref)} className="accent-teal-700" />
                  <span>
                    {draft.row_ref} · {draft.invoice ? format.money(draft.invoice.amount) : "—"} · {t("upload.confidence", { value: format.probability(draft.confidence) })}
                    {draft.flagged && <span className="ml-1 font-medium">({t("upload.checkThis")})</span>}
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <button
            type="button"
            onClick={() => commit.mutate(data)}
            disabled={commit.isPending || confirmed.size === 0}
            className="w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white disabled:opacity-60"
          >
            {t("upload.commit", { count: confirmed.size })}
          </button>
          {commit.isError && <ErrorState error={commit.error} />}
        </div>
      )}
      {commit.isSuccess && (
        <p className="mt-4 rounded-xl bg-emerald-50 p-3 font-medium text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100">
          {t("upload.done", { count: commit.data.committed })}
        </p>
      )}
      <button type="button" onClick={onClose} className="mt-4 w-full rounded-xl border border-slate-300 px-4 py-2.5 font-medium dark:border-slate-600">
        {t("provenance.close")}
      </button>
    </Dialog>
  );
}
