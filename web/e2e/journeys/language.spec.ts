// Journey: switch the language to Bangla, then Chinese, and walk every screen (WP-14 i18n). On
// each one the heading and tab title are in that language, no English UI sentence is left
// behind, and the page has talked to no host but its own (China reachability, WP-18 milestone 4).
import { sessionFile } from "../support/auth";
import { expect, SCREENS, test, type App } from "../support/fixtures";
import { untranslatedTells, type Language } from "../support/i18n";

async function expectTranslated(app: App, language: Language, where: string): Promise<void> {
  const page = app.page;
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  const text = await page.locator("main").innerText();
  const leftovers = untranslatedTells(language).filter((sentence) => text.includes(sentence));
  expect(leftovers, `English left on ${where} in ${language}`).toEqual([]);
}

test.describe("signed in", () => {
  test.use({ storageState: sessionFile("owner") });

  test("every signed-in screen reads in Bangla and in Chinese", async ({ app, page, foreignHosts }) => {
    await app.start("today");
    for (const language of ["bn", "zh"] as const) {
      await app.switchLanguage(language);
      for (const screen of SCREENS) {
        await app.open(screen);
        await expect(page).toHaveTitle(new RegExp(app.t(`nav.${screen}`).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
        await expectTranslated(app, language, screen);
      }
    }
    // The choice is remembered: a reload comes back in Chinese.
    await page.reload();
    await expect(app.heading("settings")).toBeVisible();
    expect(foreignHosts, `third-party hosts contacted: ${foreignHosts.join(", ")}`).toEqual([]);
  });
});

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the sign-in and public verify pages read in Bangla and in Chinese", async ({ app, page, foreignHosts }) => {
    for (const language of ["bn", "zh"] as const) {
      await page.goto("/login");
      await app.switchLanguage(language);
      await expect(page.getByRole("heading", { level: 2, name: app.t("auth.title") })).toBeVisible();
      await expect(page.getByRole("button", { name: app.t("auth.signIn"), exact: true })).toBeVisible();
      await expectTranslated(app, language, "sign-in");

      await page.goto("/verify");
      await expect(page.getByRole("heading", { level: 2, name: app.t("verify.title") })).toBeVisible();
      await expect(page.getByLabel(app.t("verify.passportId"))).toBeVisible();
      await expectTranslated(app, language, "verify");
    }
    expect(foreignHosts, `third-party hosts contacted: ${foreignHosts.join(", ")}`).toEqual([]);
  });
});
