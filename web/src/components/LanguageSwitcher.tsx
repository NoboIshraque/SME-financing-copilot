import { useTranslation } from "react-i18next";

import { LANGUAGES, rememberLanguage, type Language } from "../i18n";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <select
      aria-label={t("language.label")}
      className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800"
      value={i18n.language}
      onChange={(event) => {
        const language = event.target.value as Language;
        rememberLanguage(language);
        void i18n.changeLanguage(language);
      }}
    >
      {LANGUAGES.map((code) => (
        <option key={code} value={code} lang={code}>
          {t(`language.${code}`)}
        </option>
      ))}
    </select>
  );
}
