// Self-service shop (hosted demo only): a judge creates their own shop and runs DecisionGuard on
// numbers they enter. The server refuses this outside demo mode, so the link only shows there.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { api } from "../api/endpoints";
import { PublicLayout } from "../components/PublicLayout";
import { useDocumentTitle } from "../components/useDocumentTitle";
import { describeError, useServerText } from "../i18n/serverText";
import { SESSION_KEY, useSession } from "./session";

const INPUT =
  "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 dark:border-slate-600 dark:bg-slate-800";
const PRIMARY =
  "w-full rounded-xl bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 disabled:opacity-60";

export function SignupScreen() {
  const { t } = useTranslation();
  const text = useServerText();
  useDocumentTitle(t("signup.title"));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useSession();
  const ids = { title: useId(), name: useId(), email: useId(), password: useId(), error: useId() };
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ key: string; values: Record<string, string> } | null>(null);

  const signup = useMutation({
    mutationFn: () => api.auth.signup({ business_name: name.trim(), email: email.trim(), password }),
    onSuccess: (created) => {
      queryClient.setQueryData(SESSION_KEY, created);
      navigate("/settings#shop-setup", { replace: true });
    },
    onError: (failure) => setError(describeError(failure)),
  });

  if (session.data && !signup.isPending) return <Navigate to="/" replace />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    signup.mutate();
  };

  return (
    <PublicLayout>
      <div className="mx-auto w-full max-w-md space-y-6 p-4">
        <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
          <h2 id={ids.title} className="text-xl font-semibold">{t("signup.title")}</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{t("signup.help")}</p>
          <form onSubmit={submit} aria-labelledby={ids.title} className="mt-4 space-y-4" noValidate>
            <div>
              <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">{t("signup.business")}</label>
              <input id={ids.name} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={80} autoComplete="organization" className={INPUT} />
            </div>
            <div>
              <label htmlFor={ids.email} className="mb-1 block text-sm font-medium">{t("auth.email")}</label>
              <input id={ids.email} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" className={INPUT} />
            </div>
            <div>
              <label htmlFor={ids.password} className="mb-1 block text-sm font-medium">{t("auth.password")}</label>
              <input id={ids.password} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" className={INPUT} aria-describedby={error ? ids.error : undefined} />
              <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{t("signup.passwordHelp")}</p>
            </div>
            {error && (
              <p id={ids.error} role="alert" className="text-sm text-red-700 dark:text-red-300">
                {text(error.key, error.values)}
              </p>
            )}
            <button type="submit" disabled={signup.isPending} className={PRIMARY}>
              {signup.isPending ? t("signup.creating") : t("signup.create")}
            </button>
          </form>
          <p className="mt-4 text-xs text-slate-600 dark:text-slate-400">{t("signup.privacy")}</p>
        </div>
        <p className="text-center text-sm">
          <Link to="/login" className="text-teal-800 underline dark:text-teal-300">{t("signup.haveAccount")}</Link>
        </p>
      </div>
    </PublicLayout>
  );
}
