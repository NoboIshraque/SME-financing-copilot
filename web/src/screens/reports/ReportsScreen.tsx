// Reports & Trust Passport (N4, Q4): the SME's own verifiable evidence, versioned and anchored,
// shared with one lender at a time for a limited scope and time.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { newIdempotencyKey } from "../../actions/useApproveAction";
import type { PassportVersion, ShareGrant } from "../../api/contracts";
import { api } from "../../api/endpoints";
import { StepUpDialog } from "../../auth/StepUpDialog";
import { useRequiredSession } from "../../auth/session";
import { ErrorState, QueryView } from "../../components/States";
import { useDocumentTitle } from "../../components/useDocumentTitle";
import { useFormat } from "../../i18n/useFormat";

const SCOPES = ["passport:read", "report:read", "statements:read"] as const;
const card = "rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800";

function short(hash: string): string {
  return hash.length > 16 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash;
}

function PassportCard({ passport }: { passport: PassportVersion }) {
  const { t } = useTranslation();
  const format = useFormat();
  return (
    <article aria-labelledby="h-passport-latest" className={card}>
      <h4 id="h-passport-latest" className="font-semibold">
        {t("reports.version", { version: passport.version })} · {format.date(passport.issued_at, "long")}
      </h4>
      <p className="mt-1 font-mono text-xs text-slate-600 dark:text-slate-400" title={passport.digest}>
        {t("reports.digest", { hash: short(passport.digest) })}
      </p>
      <p className="mt-1 text-sm">{passport.anchor ? t(`mesh.chain.${passport.anchor.chain}`) : t("reports.notAnchored")}</p>
      <ul className="mt-3 space-y-1 text-sm">
        {passport.evidence.map((item) => (
          <li key={`${item.kind}-${item.digest}`} className="flex justify-between gap-2">
            <span>{t(`reports.evidence.${item.kind}`)}</span>
            <span className={item.verified ? "text-emerald-700 dark:text-emerald-300" : "text-slate-500 dark:text-slate-400"}>
              {item.verified ? t("reports.verified") : t("reports.selfDeclared")}
            </span>
          </li>
        ))}
      </ul>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-600 dark:text-slate-400">{t("reports.attestations")}</dt>
        <dd>{t("reports.attestationCounts", { confirmed: passport.attestations_confirmed, disputed: passport.attestations_disputed })}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("reports.abstentionRate")}</dt>
        <dd>{passport.abstention_rate ? format.probability(passport.abstention_rate) : "—"}</dd>
        <dt className="text-slate-600 dark:text-slate-400">{t("reports.drillRate")}</dt>
        <dd>{passport.audit_drill_catch_rate ? format.probability(passport.audit_drill_catch_rate) : "—"}</dd>
      </dl>
      <Link to={`/verify/${encodeURIComponent(passport.id)}`} className="mt-3 inline-block text-sm font-medium text-teal-800 underline dark:text-teal-300">
        {t("reports.openVerify")}
      </Link>
    </article>
  );
}

function ShareForm({ passport }: { passport: PassportVersion }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const ids = { lender: useId(), days: useId() };
  const [lender, setLender] = useState("");
  const [scopes, setScopes] = useState<string[]>(["passport:read"]);
  const [days, setDays] = useState(7);
  const [stepUp, setStepUp] = useState(false);
  const key = useRef<string | null>(null);
  const share = useMutation({
    mutationFn: (code: string) =>
      api.reports.share(passport.id, { lender_label: lender.trim(), scopes, days }, { idempotencyKey: (key.current ??= newIdempotencyKey()), stepUpCode: code }),
    onSuccess: (grant) => {
      queryClient.setQueryData<ShareGrant[]>(["reports", "shares"], (list) => [...(list ?? []), grant]);
      setLender("");
      key.current = null;
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (lender.trim() && scopes.length > 0) setStepUp(true);
  };
  return (
    <form onSubmit={submit} aria-labelledby="h-share" className={card}>
      <h4 id="h-share" className="font-semibold">{t("reports.shareTitle")}</h4>
      <p className="text-sm text-slate-600 dark:text-slate-400">{t("reports.shareHelp")}</p>
      <label htmlFor={ids.lender} className="mt-3 block text-sm font-medium">{t("reports.lender")}</label>
      <input id={ids.lender} value={lender} onChange={(e) => setLender(e.target.value)} required className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-600 dark:bg-slate-800" />
      <fieldset className="mt-3">
        <legend className="text-sm font-medium">{t("reports.scopes")}</legend>
        {SCOPES.map((scope) => (
          <label key={scope} className="mt-1 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={scopes.includes(scope)} onChange={(e) => setScopes(e.target.checked ? [...scopes, scope] : scopes.filter((s) => s !== scope))} className="accent-teal-700" />
            {t(`reports.scope.${scope.replace(":", "_")}`)}
          </label>
        ))}
      </fieldset>
      <label htmlFor={ids.days} className="mt-3 block text-sm font-medium">{t("reports.expiresIn")}</label>
      <select id={ids.days} value={days} onChange={(e) => setDays(Number(e.target.value))} className="mt-1 rounded-xl border border-slate-300 bg-white px-3 py-2.5 dark:border-slate-600 dark:bg-slate-800">
        {[7, 14, 30].map((d) => <option key={d} value={d}>{t("unit.days", { count: d, value: String(d) })}</option>)}
      </select>
      <button type="submit" disabled={!lender.trim() || scopes.length === 0} className="mt-4 block w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white disabled:opacity-60 sm:w-auto">
        {t("reports.shareWithCode")}
      </button>
      {share.isError && <div className="mt-2"><ErrorState error={share.error} /></div>}
      <StepUpDialog
        open={stepUp}
        summary={<p>{t("reports.shareSummary", { lender: lender.trim(), days })}</p>}
        onConfirm={(code) => share.mutateAsync(code)}
        onClose={() => setStepUp(false)}
      />
    </form>
  );
}

export function ReportsScreen() {
  const { t } = useTranslation();
  const format = useFormat();
  useDocumentTitle(t("nav.reports"));
  const session = useRequiredSession();
  const owner = session.principal.role === "owner";
  const queryClient = useQueryClient();
  const passports = useQuery({ queryKey: ["reports", "passports"], queryFn: api.reports.passports });
  const shares = useQuery({ queryKey: ["reports", "shares"], queryFn: api.reports.shares, enabled: session.principal.role !== "lender_viewer" });
  const issue = useMutation({
    mutationFn: api.reports.issuePassport,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["reports", "passports"] }),
  });
  const revoke = useMutation({
    mutationFn: (grantId: string) => api.reports.revoke(grantId),
    onSuccess: (grant) => queryClient.setQueryData<ShareGrant[]>(["reports", "shares"], (list) => list?.map((g) => (g.id === grant.id ? grant : g))),
  });

  return (
    <section aria-labelledby="h-reports" className="space-y-6">
      <h2 id="h-reports" className="text-xl font-semibold">{t("nav.reports")}</h2>
      {session.principal.role === "lender_viewer" && session.principal.expires_at && (
        <p role="note" className="rounded-xl bg-sky-50 p-3 text-sm dark:bg-sky-950/50">
          {t("reports.lenderAccess", { date: format.date(session.principal.expires_at, "long") })}
        </p>
      )}
      <section aria-labelledby="h-passport" className="space-y-3">
        <h3 id="h-passport" className="text-lg font-semibold">{t("reports.passportTitle")}</h3>
        <p className="text-sm text-slate-600 dark:text-slate-400">{t("reports.passportHelp")}</p>
        <QueryView query={passports} isEmpty={(list) => list.length === 0} empty={t("reports.noPassport")}>
          {(list) => (
            <>
              <PassportCard passport={list[0] as PassportVersion} />
              {owner && (
                <button type="button" onClick={() => issue.mutate()} disabled={issue.isPending} className="rounded-xl border border-teal-700 px-4 py-2.5 font-semibold text-teal-800 dark:border-teal-400 dark:text-teal-200">
                  {t("reports.issue")}
                </button>
              )}
              {list.length > 1 && (
                <details className="text-sm">
                  <summary className="cursor-pointer">{t("reports.history", { count: list.length - 1 })}</summary>
                  <ul className="mt-1 space-y-0.5">
                    {list.slice(1).map((older) => (
                      <li key={older.id}>{t("reports.version", { version: older.version })} · {format.date(older.issued_at, "long")} · <span className="font-mono text-xs">{short(older.digest)}</span></li>
                    ))}
                  </ul>
                </details>
              )}
              {owner && <ShareForm passport={list[0] as PassportVersion} />}
            </>
          )}
        </QueryView>
      </section>
      {session.principal.role !== "lender_viewer" && (
        <section aria-labelledby="h-shares" className="space-y-2">
          <h3 id="h-shares" className="text-lg font-semibold">{t("reports.sharesTitle")}</h3>
          <QueryView query={shares} isEmpty={(list) => list.length === 0} empty={t("reports.noShares")}>
            {(list) => (
              <ul className="divide-y divide-slate-200 rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
                {list.map((grant) => (
                  <li key={grant.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm" aria-label={grant.lender_label}>
                    <span className="font-medium">{grant.lender_label}</span>
                    <span className="text-slate-600 dark:text-slate-400">
                      {grant.scopes.map((scope) => t(`reports.scope.${scope.replace(":", "_")}`)).join(", ")} ·{" "}
                      {grant.revoked ? t("reports.revoked") : t("reports.until", { date: format.date(grant.expires_at, "long") })}
                    </span>
                    {owner && !grant.revoked && (
                      <button type="button" onClick={() => revoke.mutate(grant.id)} className="rounded-lg border border-red-300 px-3 py-1 font-medium text-red-800 dark:border-red-800 dark:text-red-200">
                        {t("reports.revoke")}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </QueryView>
        </section>
      )}
    </section>
  );
}
