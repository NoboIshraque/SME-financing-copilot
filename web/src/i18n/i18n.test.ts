import { describe, expect, it } from "vitest";

import i18n, { LANGUAGES, resources } from ".";
import { humanizeKey } from "./serverText";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

const english = new Set(keys(resources.en.translation));

// Every source file except tests, read as text.
const sources = import.meta.glob(["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("locales", () => {
  const englishKeys = [...english].sort();

  it.each(LANGUAGES.filter((l) => l !== "en"))("%s has exactly the same keys as English", (lang) => {
    expect(keys(resources[lang].translation).sort()).toEqual(englishKeys);
  });

  it.each(LANGUAGES)("%s has no empty strings", (lang) => {
    const flat = keys(resources[lang].translation);
    for (const key of flat) {
      const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], resources[lang].translation);
      expect(String(value).trim(), `${lang}:${key}`).not.toBe("");
    }
  });

  it("Bangla strings are actually in Bangla script", () => {
    expect(resources.bn.translation.nav.cash).toMatch(/[ঀ-৿]/);
    expect(resources.zh.translation.nav.cash).toMatch(/[一-鿿]/);
  });

  it("every key the source code passes to t() exists", () => {
    const used = new Set<string>();
    for (const text of Object.values(sources)) {
      for (const match of text.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) used.add(match[1] ?? "");
    }
    expect(used.size).toBeGreaterThan(30);
    expect([...used].filter((key) => !english.has(key))).toEqual([]);
  });

  it("writes digits inside Bangla sentences in Bangla script", () => {
    expect(i18n.t("error.account_locked", { lng: "bn", retry_after_minutes: "15" })).toContain("১৫");
    expect(i18n.t("error.account_locked", { lng: "zh", retry_after_minutes: "15" })).toContain("15");
  });
});

describe("server keys", () => {
  it.each([
    ["alert.gap_ahead", "Gap ahead"],
    ["driver.salary", "Salary"],
    ["plain", "Plain"],
  ])("an untranslated %s reads as %s, never as the raw key", (key, words) => {
    expect(humanizeKey(key)).toBe(words);
  });
});
