// Frame for screens outside the signed-in shell (sign-in, public verify page). Keeps the
// language switch and theme toggle on every screen.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DemoBanner } from "./DemoBanner";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { OfflineNotice } from "./OfflineNotice";
import { ThemeToggle } from "./ThemeToggle";

export function PublicLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-dvh flex-col">
      <DemoBanner />
      <OfflineNotice />
      <header className="flex items-center gap-2 px-4 py-3">
        <div className="flex-1">
          <h1 className="text-lg font-semibold text-teal-800 dark:text-teal-300">{t("app.name")}</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">{t("app.tagline")}</p>
        </div>
        <LanguageSwitcher />
        <ThemeToggle />
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pb-10 pt-4 sm:items-center">
        {children}
      </main>
    </div>
  );
}
