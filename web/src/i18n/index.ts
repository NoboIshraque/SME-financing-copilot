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

/** Hashes, digests and transaction ids: compared character by character, so never localised. */
const HEX_RUN = /(?:0x)?[0-9a-f]*[a-f][0-9a-f]*/gi;
const MIN_HEX_RUN = 6;

/** Bangla digits everywhere except inside hex runs (a hash shown in Bangla must still match). */
export function toBanglaDigitsOutsideHashes(value: string): string {
  let out = "";
  let last = 0;
  for (const match of value.matchAll(HEX_RUN)) {
    if (match[0].length < MIN_HEX_RUN || !/\d/.test(match[0])) continue;
    out += toBanglaDigits(value.slice(last, match.index)) + match[0];
    last = match.index + match[0].length;
  }
  return out + toBanglaDigits(value.slice(last));
}

/** In Bangla, digits inside translated sentences (counts, days, minutes) are written ০-৯. */
const banglaDigits: PostProcessorModule = {
  type: "postProcessor",
  name: "banglaDigits",
  process(value: string, _key: string | string[], options: { lng?: string }, translator: { language?: string }) {
    return (options.lng ?? translator.language) === "bn" ? toBanglaDigitsOutsideHashes(value) : value;
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
