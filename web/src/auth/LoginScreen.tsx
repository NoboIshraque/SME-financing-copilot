// Sign-in (WP-11): email + password, then a TOTP code when the account has one. In demo mode the
// server lists public demo accounts, signed in with one tap.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { ApiRequestError } from "../api/client";
import { api } from "../api/endpoints";
import type { DemoAccount, LoginRequest, Session } from "../api/types";
import { PublicLayout } from "../components/PublicLayout";
import { useDocumentTitle } from "../components/useDocumentTitle";
import { describeError, useServerText } from "../i18n/serverText";
import { homePath } from "../navigation";
import { normalizeCode } from "./code";
import { CodeField } from "./CodeField";
import { SESSION_KEY, safeNext, useSession } from "./session";

type ErrorText = { key: string; values: Record<string, string> };

const PUBLIC_QUERIES = new Set(["session", "health", "demo-accounts"]);

// A TOTP code lives 30 seconds (one step of drift either way), so the demo code is fetched again
// when the owner reaches the code step and refreshed while that step is open.
const DEMO_CODE_REFRESH_MS = 20_000;
// After this long without an answer the free server is probably waking up from sleep.
const SLOW_SIGN_IN_MS = 6_000;
const LOCKOUT_KEYS = new Set(["error.invalid_credentials", "error.invalid_totp"]);

/** Sign-in errors, with a cold start of the free server told apart from a real failure. */
function describeSignInError(failure: unknown): ErrorText {
  const waking =
    !(failure instanceof ApiRequestError) || (failure.body === null && [502, 503, 504].includes(failure.status));
  return waking ? { key: "auth.serverWaking", values: {} } : describeError(failure);
}

const INPUT =
  "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 dark:border-slate-600 dark:bg-slate-800";
const PRIMARY =
  "w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60";

export function LoginScreen() {
  const { t } = useTranslation();
  const text = useServerText();
  useDocumentTitle(t("auth.title"));
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const session = useSession();
  const ids = { title: useId(), email: useId(), password: useId(), code: useId(), error: useId(), hint: useId() };

  const [step, setStep] = useState<"password" | "totp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [demoEmail, setDemoEmail] = useState<string | null>(null);
  const [error, setError] = useState<ErrorText | null>(null);
  const [slow, setSlow] = useState(false);
  const [codeStepSince, setCodeStepSince] = useState(0);

  const onDemoCodeStep = step === "totp" && demoEmail !== null;
  const demo = useQuery({
    queryKey: ["demo-accounts"],
    queryFn: api.auth.demoAccounts,
    retry: false,
    refetchInterval: onDemoCodeStep ? DEMO_CODE_REFRESH_MS : false,
  });
  // Only a listing fetched after reaching the code step is shown, never the one from page load.
  const freshListing = onDemoCodeStep && demo.dataUpdatedAt >= codeStepSince;
  const totpHint = freshListing ? demo.data?.find((account) => account.email === demoEmail)?.totp_hint ?? null : null;
  const { refetch: refetchDemo } = demo;

  // Whatever ended the last session (sign-out, expiry, a 401), no business data from it stays in
  // memory once the sign-in screen is up.
  useEffect(() => {
    queryClient.removeQueries({ predicate: (query) => !PUBLIC_QUERIES.has(String(query.queryKey[0])) });
  }, [queryClient]);

  const finish = (signedIn: Session) => {
    queryClient.setQueryData(SESSION_KEY, signedIn);
    const next = params.get("next");
    navigate(next ? safeNext(next) : homePath(signedIn.principal.role), { replace: true });
  };

  const login = useMutation({
    mutationFn: (body: LoginRequest) => api.auth.login(body),
    onSuccess: (result) => {
      if (result.status === "ok") {
        finish(result.session);
      } else {
        setCodeStepSince(Date.now());
        setStep("totp");
      }
    },
    onError: (failure) => setError(describeSignInError(failure)),
  });

  const verify = useMutation({
    mutationFn: (digits: string) => api.auth.verifyTotp(digits),
    onSuccess: finish,
    onError: (failure) => {
      setError(describeSignInError(failure));
      if (demoEmail !== null) void refetchDemo();
    },
  });

  // The code shown when the page opened may be minutes old: fetch the current one on entering
  // the code step.
  useEffect(() => {
    if (onDemoCodeStep) void refetchDemo();
  }, [onDemoCodeStep, refetchDemo]);

  const pending = login.isPending || verify.isPending;
  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), SLOW_SIGN_IN_MS);
    return () => clearTimeout(timer);
  }, [pending]);

  if (session.data && !login.isPending && !verify.isPending) {
    const next = params.get("next");
    return <Navigate to={next ? safeNext(next) : homePath(session.data.principal.role)} replace />;
  }

  const submitPassword = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setDemoEmail(null);
    login.mutate({ email: email.trim(), password });
  };

  const submitCode = (event: FormEvent) => {
    event.preventDefault();
    const digits = normalizeCode(code);
    if (!digits) {
      setError({ key: "auth.codeFormat", values: {} });
      return;
    }
    setError(null);
    verify.mutate(digits);
  };

  const signInWithDemo = (account: DemoAccount) => {
    setEmail(account.email);
    setPassword(account.password);
    setDemoEmail(account.totp_hint ? account.email : null);
    setError(null);
    login.mutate({ email: account.email, password: account.password });
  };

  const errorLine = (
    <>
      {error && (
        <p id={ids.error} role="alert" className="text-sm text-red-700 dark:text-red-300">
          {text(error.key, error.values)}
          {LOCKOUT_KEYS.has(error.key) && <> {t("auth.lockoutNote")}</>}
        </p>
      )}
      {slow && (
        <p role="status" className="text-sm text-slate-600 dark:text-slate-400">
          {t("auth.slowServer")}
        </p>
      )}
    </>
  );

  return (
    <PublicLayout>
      <section aria-labelledby={ids.title} className="w-full max-w-sm space-y-6">
        <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
          {step === "password" ? (
            <form onSubmit={submitPassword} className="space-y-4" noValidate>
              <div>
                <h2 id={ids.title} className="text-xl font-semibold">
                  {t("auth.title")}
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t("auth.subtitle")}</p>
              </div>
              <div>
                <label htmlFor={ids.email} className="mb-1 block text-sm font-medium">
                  {t("auth.email")}
                </label>
                <input
                  id={ids.email}
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  aria-describedby={error ? ids.error : undefined}
                  className={INPUT}
                />
              </div>
              <div>
                <label htmlFor={ids.password} className="mb-1 block text-sm font-medium">
                  {t("auth.password")}
                </label>
                <input
                  id={ids.password}
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className={INPUT}
                />
              </div>
              {errorLine}
              <button type="submit" disabled={login.isPending} className={PRIMARY}>
                {login.isPending ? t("auth.signingIn") : t("auth.signIn")}
              </button>
            </form>
          ) : (
            <form onSubmit={submitCode} className="space-y-4" noValidate>
              <div>
                <h2 id={ids.title} className="text-xl font-semibold">
                  {t("auth.totpTitle")}
                </h2>
                <p id={ids.hint} className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  {t("auth.totpHelp")}
                </p>
              </div>
              <CodeField
                id={ids.code}
                label={t("auth.code")}
                value={code}
                onChange={setCode}
                describedBy={error ? `${ids.hint} ${ids.error}` : ids.hint}
                invalid={Boolean(error)}
              />
              {totpHint && (
                <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
                  <p>{t("auth.demoCode", { code: totpHint })}</p>
                  <p className="mt-0.5 text-xs">{t("auth.demoCodeFresh")}</p>
                </div>
              )}
              {errorLine}
              <button type="submit" disabled={verify.isPending} className={PRIMARY}>
                {verify.isPending ? t("auth.verifying") : t("auth.verify")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setStep("password");
                  setCode("");
                  setError(null);
                }}
                className="w-full text-sm text-teal-800 underline dark:text-teal-300"
              >
                {t("common.back")}
              </button>
            </form>
          )}
        </div>

        {step === "password" && demo.data && demo.data.length > 0 && (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950">
            <h3 className="font-semibold text-amber-900 dark:text-amber-100">{t("auth.demoTitle")}</h3>
            <p className="mt-1 text-sm text-amber-900/80 dark:text-amber-100/80">{t("auth.demoHelp")}</p>
            <p className="mt-2 text-sm text-amber-900 dark:text-amber-100">
              {t("auth.ownShop")}{" "}
              <Link to="/signup" className="font-semibold underline">{t("auth.ownShopLink")}</Link>
            </p>
            <ul className="mt-3 space-y-2">
              {demo.data.map((account) => (
                <li key={account.email}>
                  <button
                    type="button"
                    onClick={() => signInWithDemo(account)}
                    disabled={login.isPending}
                    className="flex w-full items-center justify-between rounded-xl bg-white px-3 py-2.5 text-left text-sm ring-1 ring-amber-200 hover:bg-amber-100 dark:bg-slate-900 dark:ring-amber-900 dark:hover:bg-slate-800"
                  >
                    <span className="font-medium">
                      {t("auth.demoAs", { role: t(`role.${account.role}`) })}
                    </span>
                    <span className="truncate pl-2 text-xs text-slate-500 dark:text-slate-400">
                      {account.business_name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </PublicLayout>
  );
}
