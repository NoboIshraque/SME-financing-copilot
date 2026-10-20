// Set-up for a self-service shop: the opening cash balance and the facts lenders check (typed by
// the owner, stored as facts whose source is the owner's entry), an example ledger to start from,
// the upload, and the authenticator code that approvals need.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/endpoints";
import type { ShopProfile, TotpEnrolment } from "../../api/types";
import { normalizeCode } from "../../auth/code";
import { CodeField } from "../../auth/CodeField";
import { SESSION_KEY, useRequiredSession } from "../../auth/session";
import { UploadDialog } from "../../copilot/UploadDialog";
import { describeError, useServerText } from "../../i18n/serverText";

const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";
const INPUT = "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-800";
const BUTTON = "rounded-xl bg-teal-700 px-4 py-2 font-semibold text-white hover:bg-teal-800 disabled:opacity-60";
const LINK_BUTTON = "rounded-xl px-4 py-2 font-semibold text-teal-800 ring-1 ring-teal-700 hover:bg-teal-50 dark:text-teal-300 dark:hover:bg-slate-800";

type ErrorText = { key: string; values: Record<string, string> };

function ProfileForm({ initial }: { initial: ShopProfile }) {
  const { t } = useTranslation();
  const text = useServerText();
  const queryClient = useQueryClient();
  const ids = { balance: useId(), date: useId(), age: useId(), staff: useId(), status: useId() };
  const [draft, setDraft] = useState<ShopProfile>(initial);
  const [error, setError] = useState<ErrorText | null>(null);
  useEffect(() => setDraft(initial), [initial]);
  const save = useMutation({
    mutationFn: (body: ShopProfile) => api.onboarding.saveProfile(body),
    onSuccess: (saved) => {
      setError(null);
      queryClient.setQueryData(["shop-profile"], saved);
      void queryClient.invalidateQueries({ predicate: (q) => !["session", "health", "shop-profile"].includes(String(q.queryKey[0])) });
    },
    onError: (failure) => setError(describeError(failure)),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate({
      opening_balance: draft.opening_balance || null,
      opening_date: draft.opening_date || null,
      business_age_months: draft.business_age_months ?? null,
      trade_licence: draft.trade_licence ?? null,
      etin_registered: draft.etin_registered ?? null,
      staff_count: draft.staff_count ?? null,
    });
  };
  const numberOrNull = (value: string) => (value === "" ? null : Number(value));
  return (
    <form onSubmit={submit} className="mt-3 grid gap-3 sm:grid-cols-2" noValidate>
      <div>
        <label htmlFor={ids.balance} className="mb-1 block text-sm font-medium">{t("setup.openingBalance")}</label>
        <input id={ids.balance} inputMode="decimal" value={draft.opening_balance ?? ""} onChange={(e) => setDraft({ ...draft, opening_balance: e.target.value })} className={INPUT} />
      </div>
      <div>
        <label htmlFor={ids.date} className="mb-1 block text-sm font-medium">{t("setup.openingDate")}</label>
        <input id={ids.date} type="date" value={draft.opening_date ?? ""} onChange={(e) => setDraft({ ...draft, opening_date: e.target.value })} className={INPUT} />
      </div>
      <div>
        <label htmlFor={ids.age} className="mb-1 block text-sm font-medium">{t("setup.businessAge")}</label>
        <input id={ids.age} type="number" min={0} value={draft.business_age_months ?? ""} onChange={(e) => setDraft({ ...draft, business_age_months: numberOrNull(e.target.value) })} className={INPUT} />
      </div>
      <div>
        <label htmlFor={ids.staff} className="mb-1 block text-sm font-medium">{t("setup.staff")}</label>
        <input id={ids.staff} type="number" min={0} value={draft.staff_count ?? ""} onChange={(e) => setDraft({ ...draft, staff_count: numberOrNull(e.target.value) })} className={INPUT} />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={Boolean(draft.trade_licence)} onChange={(e) => setDraft({ ...draft, trade_licence: e.target.checked })} className="accent-teal-700" />
        {t("setup.tradeLicence")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={Boolean(draft.etin_registered)} onChange={(e) => setDraft({ ...draft, etin_registered: e.target.checked })} className="accent-teal-700" />
        {t("setup.etin")}
      </label>
      <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={save.isPending} className={BUTTON}>{save.isPending ? t("setup.saving") : t("setup.save")}</button>
        <p id={ids.status} role="status" className="text-sm">
          {error ? <span className="text-red-700 dark:text-red-300">{text(error.key, error.values)}</span> : save.isSuccess ? t("setup.saved") : null}
        </p>
      </div>
    </form>
  );
}

function ApprovalCode() {
  const { t } = useTranslation();
  const text = useServerText();
  const queryClient = useQueryClient();
  const session = useRequiredSession();
  const codeId = useId();
  const [enrolment, setEnrolment] = useState<TotpEnrolment | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<ErrorText | null>(null);
  const start = useMutation({ mutationFn: api.auth.totpEnrol, onSuccess: setEnrolment, onError: (f) => setError(describeError(f)) });
  const confirm = useMutation({
    mutationFn: (digits: string) => api.auth.totpConfirm(digits),
    onSuccess: (updated) => {
      queryClient.setQueryData(SESSION_KEY, updated);
      setEnrolment(null);
    },
    onError: (f) => setError(describeError(f)),
  });
  if (session.totp_enrolled) return <p className="mt-2 text-sm">{t("setup.codeOn")}</p>;
  if (!enrolment) {
    return (
      <div className="mt-2 space-y-2">
        <p className="text-sm">{t("setup.codeHelp")}</p>
        <button type="button" onClick={() => start.mutate()} disabled={start.isPending} className={BUTTON}>{t("setup.codeStart")}</button>
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{text(error.key, error.values)}</p>}
      </div>
    );
  }
  return (
    <form
      className="mt-2 space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        const digits = normalizeCode(code);
        if (!digits) {
          setError({ key: "auth.codeFormat", values: {} });
          return;
        }
        setError(null);
        confirm.mutate(digits);
      }}
    >
      <p className="text-sm">{t("setup.codeAdd")}</p>
      <p className="break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-sm dark:bg-slate-800">{enrolment.secret}</p>
      <a href={enrolment.otpauth_uri} className="text-sm text-teal-800 underline dark:text-teal-300">{t("setup.codeOpenApp")}</a>
      <CodeField id={codeId} label={t("auth.code")} value={code} onChange={setCode} invalid={Boolean(error)} />
      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{text(error.key, error.values)}</p>}
      <button type="submit" disabled={confirm.isPending} className={BUTTON}>{t("setup.codeConfirm")}</button>
    </form>
  );
}

/** Shown in Settings for shops whose data is the owner's own (not the synthetic demo shops). */
export function ShopSetup() {
  const { t } = useTranslation();
  const profile = useQuery({ queryKey: ["shop-profile"], queryFn: api.onboarding.profile });
  const [uploading, setUploading] = useState(false);
  return (
    <section id="shop-setup" aria-labelledby="h-shop-setup" className={card}>
      <h3 id="h-shop-setup" className="text-lg font-semibold">{t("setup.title")}</h3>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
        <li>{t("setup.step1")}</li>
        <li>{t("setup.step2")}</li>
        <li>{t("setup.step3")}</li>
      </ol>
      <h4 className="mt-4 font-semibold">{t("setup.numbersTitle")}</h4>
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("setup.numbersHelp")}</p>
      {profile.data && <ProfileForm initial={profile.data} />}
      <h4 className="mt-5 font-semibold">{t("setup.recordsTitle")}</h4>
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("setup.recordsHelp")}</p>
      <div className="mt-2 flex flex-wrap gap-3">
        <a href="/api/onboarding/template.csv" download className={LINK_BUTTON}>{t("setup.template")}</a>
        <button type="button" onClick={() => setUploading(true)} className={BUTTON}>{t("setup.upload")}</button>
      </div>
      <UploadDialog open={uploading} onClose={() => setUploading(false)} />
      <h4 className="mt-5 font-semibold">{t("setup.codeTitle")}</h4>
      <ApprovalCode />
    </section>
  );
}
