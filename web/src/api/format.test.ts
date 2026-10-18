import { describe, expect, it } from "vitest";

import { formatTaka, groupDigits, toAsciiDigits, toBanglaDigits } from "./format";

describe("formatTaka", () => {
  it.each([
    ["1234567.00", "en", "৳12,34,567"],
    ["1234567.00", "zh", "৳1,234,567"],
    ["1234567.00", "bn", "৳১২,৩৪,৫৬৭"],
    ["999", "en", "৳999"],
    ["-45000.50", "en", "-৳45,000"],
    ["0.00", "en", "৳0"],
    ["-0.00", "en", "৳0"],
    ["00012000", "en", "৳12,000"],
  ] as const)("%s in %s -> %s", (amount, lang, expected) => {
    expect(formatTaka(amount, lang)).toBe(expected);
  });

  it("keeps paisa exactly when asked, without float rounding", () => {
    expect(formatTaka("0.1", "en", { paisa: true })).toBe("৳0.10");
    expect(formatTaka("1234567.89", "en", { paisa: true })).toBe("৳12,34,567.89");
    expect(formatTaka("90071992547409.99", "en", { paisa: true })).toBe("৳9,00,71,99,25,47,409.99");
  });

  it.each(["", "abc", "1e5", "12,000", "NaN"])("rejects %j", (bad) => {
    expect(() => formatTaka(bad, "en")).toThrow();
  });
});

describe("digit helpers", () => {
  it("groups South Asian and Western styles differently", () => {
    expect(groupDigits("100000", "south_asian")).toBe("1,00,000");
    expect(groupDigits("100000", "western")).toBe("100,000");
  });

  it("converts every ASCII digit to Bangla", () => {
    expect(toBanglaDigits("0123456789")).toBe("০১২৩৪৫৬৭৮৯");
  });

  it("reads Bangla and full-width digits back as ASCII, leaving other text alone", () => {
    expect(toAsciiDigits("০১২৩৪৫৬৭৮৯")).toBe("0123456789");
    expect(toAsciiDigits("０１２３４５６７８９")).toBe("0123456789");
    expect(toAsciiDigits("কোড ২৪৬-810")).toBe("কোড 246-810");
  });
});
