import { describe, expect, it } from "vitest";

import { LANGUAGES, resources } from ".";

function keys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("locales", () => {
  const english = keys(resources.en.translation).sort();

  it.each(LANGUAGES.filter((l) => l !== "en"))("%s has exactly the same keys as English", (lang) => {
    expect(keys(resources[lang].translation).sort()).toEqual(english);
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
});
