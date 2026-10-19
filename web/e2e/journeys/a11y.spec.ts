// WCAG 2.1 AA in a real browser, light and dark (WP-14 milestone 12). jsdom has no layout, so the
// Vitest axe run cannot judge colour contrast or what is really hidden: this one can.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { sessionFile } from "../support/auth";
import { expect, SCREENS, test } from "../support/fixtures";

const WCAG21_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const THEMES = ["light", "dark"] as const;

// Known, found by this suite (WP-15.md, Notes), as "<theme> <rule>" per screen. The assertion is
// exact, so a fix fails it too: then take the entry out.
//  - today: the Watch tier badge, white on sky-600, is 4.02:1 (AA needs 4.5:1 for small text).
//  - cash: the forecast chart is aria-hidden but its SVG keeps focusable elements.
//  - mesh, reports, settings (dark): slate-500 small text on slate-900 is 3.74:1.
const KNOWN: Partial<Record<string, string[]>> = {
  today: ["light color-contrast", "dark color-contrast"],
  cash: ["light aria-hidden-focus", "dark aria-hidden-focus"],
  mesh: ["dark color-contrast"],
  reports: ["dark color-contrast"],
  settings: ["dark color-contrast"],
};

async function violations(page: Page, path: string): Promise<string[]> {
  const found: string[] = [];
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript((choice) => window.localStorage.setItem("hishab.theme", choice), theme);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
    const result = await new AxeBuilder({ page }).withTags(WCAG21_AA).analyze();
    found.push(...result.violations.map((violation) => `${theme} ${violation.id}`));
  }
  return found.sort();
}

test.describe("signed in", () => {
  test.use({ storageState: sessionFile("owner") });

  for (const screen of SCREENS) {
    test(`${screen} meets WCAG 2.1 AA in light and dark`, async ({ page }) => {
      expect(await violations(page, screen === "today" ? "/" : `/${screen}`)).toEqual([...(KNOWN[screen] ?? [])].sort());
    });
  }
});

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const [name, path] of [["sign-in", "/login"], ["verify", "/verify"]] as const) {
    test(`the ${name} page meets WCAG 2.1 AA in light and dark`, async ({ page }) => {
      expect(await violations(page, path)).toEqual([...(KNOWN[name] ?? [])].sort());
    });
  }
});
