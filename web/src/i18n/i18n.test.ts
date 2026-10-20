import { describe, expect, it } from "vitest";

import i18n, { LANGUAGES, resources } from ".";
import serverKeys from "./server-keys.json";
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

  it("every key the source code passes to t() exists (plural keys as _one/_other)", () => {
    const used = new Set<string>();
    for (const text of Object.values(sources)) {
      for (const match of text.matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) used.add(match[1] ?? "");
    }
    expect(used.size).toBeGreaterThan(30);
    const missing = [...used].filter(
      (key) => !english.has(key) && !(english.has(`${key}_one`) && english.has(`${key}_other`)),
    );
    expect(missing).toEqual([]);
  });

  it("labels every permission tier, alert tier and leading indicator", () => {
    const tiers = ["READ", "SUGGEST", "DRAFT", "EXECUTE", "DENY"];
    const alertTiers = ["critical", "warning", "watch"];
    const indicators = ["dso_rising", "top_customer_slowing", "stock_building", "sales_below_seasonal_norm", "payroll_or_emi_at_risk"];
    const expected = [
      ...tiers.flatMap((tier) => [`tier.${tier}`, `tierHelp.${tier}`]),
      ...alertTiers.map((tier) => `alertTier.${tier}`),
      ...indicators.map((name) => `indicator.${name}`),
    ];
    expect(expected.filter((key) => !english.has(key))).toEqual([]);
  });

  it("writes digits inside Bangla sentences in Bangla script", () => {
    expect(i18n.t("error.account_locked", { lng: "bn", retry_after_minutes: "15" })).toContain("১৫");
    expect(i18n.t("error.account_locked", { lng: "zh", retry_after_minutes: "15" })).toContain("15");
  });

  it("keeps a hash comparable in Bangla: digits inside it stay ASCII, the rest turn Bangla", () => {
    const head = "3ee12ab9c04d5f6e7a8b9c0d1e2f30415263748596a7b8c9d0e1f2031425364";
    expect(i18n.t("trust.head", { lng: "bn", hash: head })).toBe(`সর্বশেষ হ্যাশ ${head}`);
    expect(i18n.t("mesh.tx", { lng: "bn", hash: "0x2b4d6f8a" })).toContain("0x2b4d6f8a");
    expect(i18n.t("error.account_locked", { lng: "bn", retry_after_minutes: "15" })).toContain("১৫");
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

describe("keys the demo API returns (scripts/server_keys.py)", () => {
  const lookup = (lang: (typeof LANGUAGES)[number], key: string): unknown =>
    key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], resources[lang].translation);

  it.each(LANGUAGES)("every one is translated in %s, so no screen falls back to English", (lang) => {
    const missing = serverKeys.filter((key) => typeof lookup(lang, key) !== "string");
    expect(missing).toEqual([]);
  });

  it("Bangla and Chinese say it in their own words, not the English", () => {
    const same = serverKeys.filter((key) => lookup("bn", key) === lookup("en", key) || lookup("zh", key) === lookup("en", key));
    expect(same).toEqual([]);
  });
});
