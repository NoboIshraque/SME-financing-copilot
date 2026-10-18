// Public verify page (WP-13 milestone 4): anyone with a passport ID recomputes its digest and
// compares it with the hash anchored on chain. No sign-in needed.
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { api } from "../../api/endpoints";
import { PublicLayout } from "../../components/PublicLayout";
import { ErrorState } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useFormat } from "../../i18n/useFormat";

export function VerifyScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("verify.title"));
  const params = useParams();
  const inputId = useId();
  const [passportId, setPassportId] = useState(params.passportId ?? "");
  const verify = useMutation({ mutationFn: (id: string) => api.reports.verify(id) });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (passportId.trim()) verify.mutate(passportId.trim());
  };
  const result = verify.data;
  return (
    <PublicLayout>
      <section aria-labelledby="h-verify" className="w-full max-w-lg space-y-4">
        <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
          <h2 id="h-verify" className="text-xl font-semibold">{t("verify.title")}</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t("verify.help")}</p>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <label htmlFor={inputId} className="block text-sm font-medium">{t("verify.passportId")}</label>
            <input id={inputId} value={passportId} onChange={(e) => setPassportId(e.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 font-mono dark:border-slate-600 dark:bg-slate-800" />
            <button type="submit" disabled={!passportId.trim() || verify.isPending} className="w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white disabled:opacity-60">
              {t("verify.check")}
            </button>
          </form>
        </div>
        {verify.isError && <ErrorState error={verify.error} />}
        {result && (
          <div className={`rounded-2xl border p-4 ${result.valid ? "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/50" : "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/50"}`}>
            <p className="text-lg font-semibold">{result.valid ? t("verify.valid") : t("verify.invalid")}</p>
            <dl className="mt-2 space-y-1 break-all text-xs">
              <dt className="font-medium">{t("verify.recomputed")}</dt>
              <dd className="font-mono">{result.recomputed_digest}</dd>
              <dt className="font-medium">{t("verify.anchored")}</dt>
              <dd className="font-mono">{result.anchored_digest ?? t("verify.noAnchor")}</dd>
            </dl>
            <p className="mt-2 text-xs">{t("verify.checkedOn", { date: format.date(result.checked_on, "long") })}</p>
          </div>
        )}
      </section>
    </PublicLayout>
  );
}
