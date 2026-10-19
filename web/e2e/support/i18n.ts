// UI strings straight from the app's locale files, so journeys find controls by what a person
// reads in each language and never drift from the translations.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { WEB_DIR } from "./target";

export const LANGUAGES = ["en", "bn", "zh"] as const;
export type Language = (typeof LANGUAGES)[number];

type Tree = { [key: string]: string | Tree };

const locales = Object.fromEntries(
  LANGUAGES.map((lang) => [lang, JSON.parse(readFileSync(join(WEB_DIR, "src", "i18n", "locales", `${lang}.json`), "utf8")) as Tree]),
) as Record<Language, Tree>;

const BANGLA_DIGITS = "০১২৩৪৫৬৭৮৯";

function lookup(tree: Tree, key: string): string | undefined {
  let node: string | Tree | undefined = tree;
  for (const part of key.split(".")) {
    if (typeof node !== "object") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/**
 * English UI sentences whose `lang` translation reads differently: on a screen in `lang`, none of
 * them should show (an untranslated string falls back to English). Fragments around {{slots}}
 * count when they are long enough to be unmistakable.
 */
export function untranslatedTells(lang: Language): string[] {
  const tells = new Set<string>();
  const walk = (en: Tree, other: Tree | string | undefined) => {
    for (const [key, value] of Object.entries(en)) {
      const translated = typeof other === "object" ? other[key] : undefined;
      if (typeof value !== "string") {
        walk(value, translated);
        continue;
      }
      if (typeof translated !== "string" || translated === value) continue;
      for (const fragment of value.split(/\{\{\s*\w+\s*\}\}/)) {
        const text = fragment.trim();
        if (text.length >= 16 && text.includes(" ") && !translated.includes(text)) tells.add(text);
      }
    }
  };
  walk(locales.en, locales[lang]);
  return [...tells];
}

/**
 * The text of `key` (any plural form), with each {{slot}} matched by the given regex source, e.g.
 * tPattern("trust.chainValid", { value: "[\\d,]+" }). `whole`: the text is the whole string.
 */
export function tPattern(key: string, slots: Record<string, string>, lang: Language = "en", whole = true): RegExp {
  const forms = [key, `${key}_one`, `${key}_other`].filter((form) => lookup(locales[lang], form) !== undefined);
  if (forms.length === 0) throw new Error(`missing ${lang} string: ${key}`);
  const markers = Object.fromEntries(Object.keys(slots).map((name) => [name, `${name}`]));
  const sources = forms.map((form) =>
    t(form, markers, lang)
      .split(/(\w+)/)
      .map((part, index) => (index % 2 === 1 ? `(?:${slots[part] ?? ""})` : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
      .join(""),
  );
  return new RegExp(whole ? `^(?:${sources.join("|")})$` : `(?:${sources.join("|")})`);
}

/** `key` in `lang`, with {{name}} filled in (and Bangla digits in Bangla, as the app writes them). */
export function t(key: string, values: Record<string, string | number> = {}, lang: Language = "en"): string {
  const plural = typeof values.count === "number" ? `${key}_${values.count === 1 ? "one" : "other"}` : null;
  const template = (plural && lookup(locales[lang], plural)) ?? lookup(locales[lang], key);
  if (template === undefined) throw new Error(`missing ${lang} string: ${key}`);
  const text = template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, name: string) => String(values[name] ?? ""));
  return lang === "bn" ? text.replace(/[0-9]/g, (digit) => BANGLA_DIGITS[Number(digit)] ?? digit) : text;
}
