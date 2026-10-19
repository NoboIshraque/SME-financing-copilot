/// <reference lib="dom" />
// Flow 12: every screen, signed in and public, in a real browser (WP-14 milestone 12 and its
// mobile-first design): WCAG 2.1 AA by axe in light and dark, and no screen wider than the device.
// jsdom (the Vitest axe run) has no layout, so it cannot judge contrast, hiding or overflow: this can.
// A new problem fails the flow; known ones are reported in the run's known-bugs list.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { sessionFile } from "../support/auth";
import { expect, knownBug, SCREENS, test } from "../support/fixtures";

type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];

const WCAG21_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const THEMES = ["light", "dark"] as const;

// Known, found by this suite (WP-15.md, Notes), as "<theme> <rule>" per page and viewport, plus
// "too wide" for a page wider than the device:
//  - cash: the forecast chart is aria-hidden but its SVG keeps focusable elements.
//  - mesh, reports, settings (desktop) in dark: slate-500 small text on slate-900 is 3.74:1.
//  - trust on a phone: TierBadge's visually hidden text escapes the audit table's scroll box, so
//    the page is 31-57 px too wide (it pans; the fixed bottom bar is laid out off-screen), and that
//    scroll box cannot be reached by keyboard.
const both = (rule: string) => [`dark ${rule}`, `light ${rule}`];
const KNOWN: Record<string, { desktop?: string[]; phone?: string[] }> = {
  cash: { desktop: both("aria-hidden-focus"), phone: both("aria-hidden-focus") },
  mesh: { desktop: ["dark color-contrast"], phone: ["dark color-contrast"] },
  reports: { desktop: ["dark color-contrast"], phone: ["dark color-contrast"] },
  settings: { desktop: ["dark color-contrast"] },
  trust: { phone: [...both("scrollable-region-focusable"), "too wide"] },
};

const MEANING: Record<string, string> = {
  "color-contrast": "text below the 4.5:1 contrast minimum",
  "aria-hidden-focus": "focusable elements inside an aria-hidden region",
  "scrollable-region-focusable": "a scrolling region the keyboard cannot reach",
};

async function problems(page: Page, path: string): Promise<string[]> {
  const found: string[] = [];
  for (const theme of THEMES) {
    await page.emulateMedia({ colorScheme: theme });
    await page.addInitScript((choice) => window.localStorage.setItem("hishab.theme", choice), theme);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await expect(page.locator("[aria-busy='true']")).toHaveCount(0, { timeout: 60_000 });
    // @axe-core/playwright types against the hoisted playwright-core (newer than the runner's).
    const result = await new AxeBuilder({ page: page as unknown as AxePage }).withTags(WCAG21_AA).analyze();
    found.push(...result.violations.map((violation) => `${theme} ${violation.id}`));
  }
  const width = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (width > 0) found.push("too wide");
  return found.sort();
}

function describe(name: string, entry: string): string {
  if (entry === "too wide") return `WP-14 (layout): the ${name} page is wider than the device, so it pans sideways`;
  const [theme, rule = ""] = entry.split(" ");
  return `WP-14 (WCAG 2.1 AA): ${name}, ${theme} theme: ${MEANING[rule] ?? rule}`;
}

test.use({ storageState: sessionFile("owner") });

test("every screen meets WCAG 2.1 AA in light and dark and fits the device", async ({ app, page, browser, baseURL }) => {
  test.setTimeout(300_000);
  const pages: [string, Page, string][] = SCREENS.map((screen) => [screen, page, screen === "today" ? "/" : `/${screen}`]);
  const { viewport, userAgent, deviceScaleFactor, isMobile, hasTouch } = test.info().project.use;
  const visitorContext = await browser.newContext({
    viewport, userAgent, deviceScaleFactor, isMobile, hasTouch, baseURL, storageState: { cookies: [], origins: [] },
  });
  try {
    const visitor = await visitorContext.newPage();
    pages.push(["sign-in", visitor, "/login"], ["verify", visitor, "/verify"]);

    const unexpected: string[] = [];
    for (const [name, where, path] of pages) {
      const known = (app.isPhone ? KNOWN[name]?.phone : KNOWN[name]?.desktop) ?? [];
      for (const entry of await problems(where, path)) {
        if (known.includes(entry)) knownBug(describe(name, entry));
        else unexpected.push(`${name}: ${entry}`);
      }
    }
    expect(unexpected, "new accessibility or layout problems").toEqual([]);
  } finally {
    await visitorContext.close();
  }
});
