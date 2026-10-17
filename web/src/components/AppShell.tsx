import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { DemoBanner } from "./DemoBanner";
import { LanguageSwitcher } from "./LanguageSwitcher";

export const SCREENS = [
  "today",
  "cash",
  "receivables",
  "financing",
  "analysis",
  "mesh",
  "market",
  "messages",
  "reports",
  "trust",
  "settings",
] as const;
export type Screen = (typeof SCREENS)[number];

export function AppShell() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <DemoBanner />
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold text-teal-800">{t("app.name")}</h1>
          <p className="text-xs text-slate-500">{t("app.tagline")}</p>
        </div>
        <LanguageSwitcher />
      </header>
      <nav aria-label="Main" className="overflow-x-auto border-b border-slate-200 bg-white">
        <ul className="flex gap-1 px-2">
          {SCREENS.map((screen) => (
            <li key={screen}>
              <NavLink
                to={screen === "today" ? "/" : `/${screen}`}
                end
                className={({ isActive }) =>
                  `block whitespace-nowrap px-3 py-2 text-sm ${
                    isActive ? "border-b-2 border-teal-700 font-medium text-teal-800" : "text-slate-600"
                  }`
                }
              >
                {t(`nav.${screen}`)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="mx-auto max-w-5xl p-4">
        <Outlet />
      </main>
    </div>
  );
}
