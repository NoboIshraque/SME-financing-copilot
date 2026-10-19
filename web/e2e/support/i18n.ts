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

/** `key` in `lang`, with {{name}} filled in (and Bangla digits in Bangla, as the app writes them). */
export function t(key: string, values: Record<string, string | number> = {}, lang: Language = "en"): string {
  const plural = typeof values.count === "number" ? `${key}_${values.count === 1 ? "one" : "other"}` : null;
  const template = (plural && lookup(locales[lang], plural)) ?? lookup(locales[lang], key);
  if (template === undefined) throw new Error(`missing ${lang} string: ${key}`);
  const text = template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, name: string) => String(values[name] ?? ""));
  return lang === "bn" ? text.replace(/[0-9]/g, (digit) => BANGLA_DIGITS[Number(digit)] ?? digit) : text;
}
