import { useTranslation } from "react-i18next";

import { LANGUAGES, rememberLanguage, type Language } from "../i18n";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only">{t("language.label")}</span>
      <select
        aria-label={t("language.label")}
        className="rounded border border-slate-300 bg-white px-2 py-1"
        value={i18n.language}
        onChange={(event) => {
          const language = event.target.value as Language;
          rememberLanguage(language);
          void i18n.changeLanguage(language);
          document.documentElement.lang = language;
        }}
      >
        {LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {t(`language.${code}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
