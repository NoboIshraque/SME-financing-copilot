// Flow 7: switch the language to Bangla, then Chinese, and walk every screen (WP-14 i18n), signed
// in and signed out (sign-in and the public verify page). On each one the heading is in that
// language, no English UI sentence is left behind, and the page has talked to no host but its own
// (China reachability, WP-18 milestone 4).
import type { Page } from "@playwright/test";

import { sessionFile } from "../support/auth";
import { App, expect, SCREENS, test } from "../support/fixtures";
import { untranslatedTells, type Language } from "../support/i18n";

const LANGUAGES = ["bn", "zh"] as const;

// Trust last, and each language starts from a fresh load: on a phone Trust is wider than the
// screen (known WP-14 bug, see a11y.spec.ts) and its fixed bottom bar then takes no taps.
const WALK = [...SCREENS.filter((screen) => screen !== "trust"), "trust" as const];

async function expectTranslated(app: App, language: Language, where: string): Promise<void> {
  const page = app.page;
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  // What the owner typed (quoted in <q>, e.g. a question in the abstention log) is theirs, not UI.
  let text = await page.locator("main").innerText();
  for (const quoted of await page.locator("main q").allInnerTexts()) text = text.replace(quoted, "");
  const leftovers = untranslatedTells(language).filter((sentence) => text.includes(sentence));
  expect(leftovers, `English left on ${where} in ${language}`).toEqual([]);
}

function recordForeignHosts(page: Page, own: string, hosts: string[]): void {
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && url.host !== own && !hosts.includes(url.host)) hosts.push(url.host);
  });
}

test.use({ storageState: sessionFile("owner") });

test("every screen reads in Bangla and in Chinese, and only our own host is contacted", async ({ app, page, foreignHosts, browser, baseURL }) => {
  test.setTimeout(180_000);
  for (const language of LANGUAGES) {
    await app.start("today");
    await app.switchLanguage(language);
    for (const screen of WALK) {
      await app.open(screen);
      await expect(page).toHaveTitle(new RegExp(app.t(`nav.${screen}`).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
      await expectTranslated(app, language, screen);
    }
  }
  // The choice is remembered: a reload comes back in Chinese.
  await page.reload();
  await expect(app.heading("trust")).toBeVisible();

  // Signed out: the sign-in screen and the public verify page.
  const visitorContext = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  try {
    const visitor = new App(await visitorContext.newPage());
    recordForeignHosts(visitor.page, new URL(baseURL ?? "").host, foreignHosts);
    for (const language of LANGUAGES) {
      await visitor.page.goto("/login");
      await visitor.switchLanguage(language);
      await expect(visitor.page.getByRole("heading", { level: 2, name: visitor.t("auth.title") })).toBeVisible();
      await expect(visitor.page.getByRole("button", { name: visitor.t("auth.signIn"), exact: true })).toBeVisible();
      await expectTranslated(visitor, language, "sign-in");

      await visitor.page.goto("/verify");
      await expect(visitor.page.getByRole("heading", { level: 2, name: visitor.t("verify.title") })).toBeVisible();
      await expect(visitor.page.getByLabel(visitor.t("verify.passportId"))).toBeVisible();
      await expectTranslated(visitor, language, "verify");
    }
  } finally {
    await visitorContext.close();
  }
  expect(foreignHosts, `third-party hosts contacted: ${foreignHosts.join(", ")}`).toEqual([]);
});
