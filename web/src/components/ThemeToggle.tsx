import { useTranslation } from "react-i18next";

import { resolveTheme, setThemePreference, useThemePreference } from "../theme";
import { Icon } from "./Icon";

/** Header switch between light and dark. Settings also offers "follow the system". */
export function ThemeToggle() {
  const { t } = useTranslation();
  const dark = resolveTheme(useThemePreference()) === "dark";
  return (
    <button
      type="button"
      aria-pressed={dark}
      aria-label={t("shell.darkMode")}
      title={t("shell.darkMode")}
      onClick={() => setThemePreference(dark ? "light" : "dark")}
      className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
    >
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}
