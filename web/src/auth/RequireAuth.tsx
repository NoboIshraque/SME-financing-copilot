// Route guards: signed in at all (RequireAuth), and allowed to see this screen (ScreenGate).
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useLocation } from "react-router-dom";

import { ErrorState, LoadingState } from "../components/States";
import { canSee, homePath, type Screen } from "../navigation";
import { useRequiredSession, useSession } from "./session";

export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const session = useSession();
  if (session.isPending) {
    return (
      <div className="p-4">
        <LoadingState />
      </div>
    );
  }
  if (session.isError) {
    return (
      <div className="p-4">
        <ErrorState error={session.error} onRetry={() => void session.refetch()} />
      </div>
    );
  }
  if (!session.data) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

/** Screens a role does not use say so plainly instead of showing an empty page. */
export function ScreenGate({ screen, children }: { screen: Screen; children: ReactNode }) {
  const { t } = useTranslation();
  const session = useRequiredSession();
  const role = session.principal.role;
  if (canSee(role, screen)) return <>{children}</>;
  if (screen === "today") return <Navigate to={homePath(role)} replace />;
  return (
    <section aria-labelledby="h-forbidden" className="space-y-3">
      <h2 id="h-forbidden" className="text-xl font-semibold">
        {t("shell.notForRoleTitle")}
      </h2>
      <p className="text-slate-600 dark:text-slate-400">
        {t("shell.notForRole", { role: t(`role.${role}`) })}
      </p>
      <Link to={homePath(role)} className="inline-block text-teal-800 underline dark:text-teal-300">
        {t("common.goHome")}
      </Link>
    </section>
  );
}
