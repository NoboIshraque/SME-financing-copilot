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
// "too wide" for a page wider than the device. All fixed on 20 Oct (final audit, M10-M13): the
// cash chart's focusable SVG, dark slate-500 text on mesh/reports/settings, the Watch badge, and
// trust's audit table on a phone. Add an entry here only for a newly found, reported bug.
const KNOWN: Record<string, { desktop?: string[]; phone?: string[] }> = {};

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
  // Scrolled to the end, the last thing on the screen must sit above the floating Ask button.
  const covered = await page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    const ask = Array.from(document.querySelectorAll("button")).find((b) => getComputedStyle(b).position === "fixed");
    const last = document.querySelector("main")?.lastElementChild;
    if (!ask || !last) return false;
    return last.getBoundingClientRect().bottom > ask.getBoundingClientRect().top + 1;
  });
  if (covered) found.push("covered by the Ask button");
  return found.sort();
}

function describe(name: string, entry: string): string {
  if (entry === "too wide") return `WP-14 (layout): the ${name} page is wider than the device, so it pans sideways`;
  if (entry === "covered by the Ask button") return `WP-14 (layout): the end of the ${name} page sits under the floating Ask button`;
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
