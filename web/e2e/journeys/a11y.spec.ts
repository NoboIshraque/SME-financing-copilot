/// <reference lib="dom" />
// WCAG 2.1 AA in a real browser, light and dark (WP-14 milestone 12). jsdom has no layout, so the
// Vitest axe run cannot judge colour contrast or what is really hidden: this one can.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { sessionFile } from "../support/auth";
import { expect, SCREENS, test } from "../support/fixtures";

type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];

const WCAG21_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const THEMES = ["light", "dark"] as const;

// Known, found by this suite (WP-15.md, Notes), as "<theme> <rule>" per screen and viewport. The
// assertion is exact, so a fix fails it too: then take the entry out.
//  - today: the Watch tier badge, white on sky-600, is 4.02:1 (AA needs 4.5:1 for small text).
//  - cash: the forecast chart is aria-hidden but its SVG keeps focusable elements.
//  - mesh, reports, settings (desktop) in dark: slate-500 small text on slate-900 is 3.74:1.
//  - trust on a phone: the audit table scrolls sideways in a box the keyboard cannot reach.
const BOTH_THEMES = (rule: string) => [`dark ${rule}`, `light ${rule}`];
const KNOWN: Record<string, { desktop?: string[]; phone?: string[] }> = {
  today: { desktop: BOTH_THEMES("color-contrast"), phone: BOTH_THEMES("color-contrast") },
  cash: { desktop: BOTH_THEMES("aria-hidden-focus"), phone: BOTH_THEMES("aria-hidden-focus") },
  mesh: { desktop: ["dark color-contrast"], phone: ["dark color-contrast"] },
  reports: { desktop: ["dark color-contrast"], phone: ["dark color-contrast"] },
  settings: { desktop: ["dark color-contrast"] },
  trust: { phone: BOTH_THEMES("scrollable-region-focusable") },
};

function known(name: string, phone: boolean): string[] {
  return [...((phone ? KNOWN[name]?.phone : KNOWN[name]?.desktop) ?? [])].sort();
}

async function violations(page: Page, path: string): Promise<string[]> {
  const found: string[] = [];
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript((choice) => window.localStorage.setItem("hishab.theme", choice), theme);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
    // @axe-core/playwright types against the hoisted playwright-core (newer than the runner's).
    const result = await new AxeBuilder({ page: page as unknown as AxePage }).withTags(WCAG21_AA).analyze();
    found.push(...result.violations.map((violation) => `${theme} ${violation.id}`));
  }
  return found.sort();
}

test.describe("signed in", () => {
  test.use({ storageState: sessionFile("owner") });

  for (const screen of SCREENS) {
    test(`${screen} meets WCAG 2.1 AA in light and dark`, async ({ app, page }) => {
      expect(await violations(page, screen === "today" ? "/" : `/${screen}`)).toEqual(known(screen, app.isPhone));
    });
  }
});

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const [name, path] of [["sign-in", "/login"], ["verify", "/verify"]] as const) {
    test(`the ${name} page meets WCAG 2.1 AA in light and dark`, async ({ app, page }) => {
      expect(await violations(page, path)).toEqual(known(name, app.isPhone));
    });
  }
});
