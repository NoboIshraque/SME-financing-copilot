import i18n, { type PostProcessorModule } from "i18next";
import { initReactI18next } from "react-i18next";

import { toBanglaDigits } from "../api/format";
import bn from "./locales/bn.json";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

export const LANGUAGES = ["en", "bn", "zh"] as const;
export type Language = (typeof LANGUAGES)[number];
export const resources = { en: { translation: en }, bn: { translation: bn }, zh: { translation: zh } };

const STORAGE_KEY = "hishab.language";

export function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && (LANGUAGES as readonly string[]).includes(saved)) return saved as Language;
  } catch {
    // storage can be unavailable (private mode); fall back to English
  }
  return "en";
}

export function rememberLanguage(language: Language): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // ignore: remembering the language is a convenience only
  }
}

/** In Bangla, digits inside translated sentences (counts, days, minutes) are written ০-৯. */
const banglaDigits: PostProcessorModule = {
  type: "postProcessor",
  name: "banglaDigits",
  process(value: string, _key: string | string[], options: { lng?: string }, translator: { language?: string }) {
    return (options.lng ?? translator.language) === "bn" ? toBanglaDigits(value) : value;
  },
};

// <html lang> follows the UI language, so screen readers and fonts pick the right script.
i18n.on("languageChanged", (language) => {
  document.documentElement.lang = language;
});

void i18n
  .use(banglaDigits)
  .use(initReactI18next)
  .init({
    resources,
    lng: initialLanguage(),
    fallbackLng: "en",
    interpolation: { escapeValue: false },
    returnNull: false,
    postProcess: ["banglaDigits"],
  });

export default i18n;
