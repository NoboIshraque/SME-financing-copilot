// Signed-in frame. Phones (360 px first): bottom bar with the main screens and "More", which
// slides the full navigation in. Wider screens: the same navigation as a sidebar.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { api } from "../api/endpoints";
import { SESSION_KEY, useRequiredSession } from "../auth/session";
import { QUICK_SCREENS, SCREEN_ICONS, SCREENS, canSee, screenPath } from "../navigation";
import { DemoBanner } from "./DemoBanner";
import { Icon } from "./Icon";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

function SignOutButton() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const signOut = async () => {
    try {
      await api.auth.logout();
    } catch {
      // the session is dropped locally either way
    }
    queryClient.setQueryData(SESSION_KEY, null);
    // Nothing of this tenant's data may stay in memory for the next person on the device.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
    navigate("/login", { replace: true });
  };
  return (
    <button
      type="button"
      onClick={() => void signOut()}
      aria-label={t("shell.signOut")}
      title={t("shell.signOut")}
      className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
    >
      <Icon name="logout" />
    </button>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const session = useRequiredSession();
  const role = session.principal.role;
  const screens = SCREENS.filter((screen) => canSee(role, screen));
  const preferred = screens.filter((screen) => QUICK_SCREENS.includes(screen));
  const quick = preferred.length > 0 ? preferred : screens.slice(0, QUICK_SCREENS.length);
  const [menuOpen, setMenuOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    navRef.current?.querySelector<HTMLElement>("a")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:text-teal-900"
      >
        {t("shell.skipToContent")}
      </a>
      <DemoBanner />
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2">
          <div className="min-w-0 flex-1">
            <h1 className="text-base font-semibold leading-tight text-teal-800 dark:text-teal-300">{t("app.name")}</h1>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">{session.business_name}</p>
          </div>
          <LanguageSwitcher />
          <ThemeToggle />
          <SignOutButton />
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-7xl flex-1">
        {menuOpen && (
          <div className="fixed inset-0 z-30 bg-slate-900/40 md:hidden" aria-hidden="true" onClick={() => setMenuOpen(false)} />
        )}
        <nav
          id="main-nav"
          ref={navRef}
          aria-label={t("nav.main")}
          className={`fixed inset-y-0 left-0 z-40 w-72 overflow-y-auto border-r border-slate-200 bg-white p-3 transition-transform dark:border-slate-800 dark:bg-slate-900 md:visible md:sticky md:top-14 md:z-0 md:h-[calc(100dvh-3.5rem)] md:w-60 md:shrink-0 md:translate-x-0 md:bg-transparent md:dark:bg-transparent ${
            menuOpen ? "translate-x-0" : "-translate-x-full max-md:invisible"
          }`}
        >
          <ul className="space-y-1">
            {screens.map((screen) => (
              <li key={screen}>
                <NavLink
                  to={screenPath(screen)}
                  end
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm ${
                      isActive
                        ? "bg-teal-50 font-semibold text-teal-900 dark:bg-teal-950 dark:text-teal-100"
                        : "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                    }`
                  }
                >
                  <Icon name={SCREEN_ICONS[screen]} />
                  {t(`nav.${screen}`)}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="mt-6 border-t border-slate-200 px-3 pt-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
            <p>{t("shell.signedInAs", { name: session.display_name })}</p>
            <p className="mt-0.5 font-medium">{t(`role.${role}`)}</p>
          </div>
        </nav>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 pb-28 pt-4 outline-none md:px-8 md:pb-10">
          <Outlet />
        </main>
      </div>

      <nav
        aria-label={t("nav.quick")}
        className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 md:hidden"
      >
        <ul className="flex">
          {quick.map((screen) => (
            <li key={screen} className="flex-1">
              <NavLink
                to={screenPath(screen)}
                end
                className={({ isActive }) =>
                  `flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] ${
                    isActive ? "font-semibold text-teal-800 dark:text-teal-300" : "text-slate-600 dark:text-slate-400"
                  }`
                }
              >
                <Icon name={SCREEN_ICONS[screen]} />
                {t(`nav.${screen}`)}
              </NavLink>
            </li>
          ))}
          <li className="flex-1">
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-controls="main-nav"
              onClick={() => setMenuOpen((open) => !open)}
              className="flex min-h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] text-slate-600 dark:text-slate-400"
            >
              <Icon name={menuOpen ? "close" : "more"} />
              {t("nav.more")}
            </button>
          </li>
        </ul>
      </nav>
    </div>
  );
}
