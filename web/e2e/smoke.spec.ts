import { sessionFile } from "./support/auth";
import { expect, test } from "./support/fixtures";

test.describe("signed in", () => {
  test.use({ storageState: sessionFile("owner") });

  // External-domain audit (WP-18 milestone 4; the language journey repeats it on every screen):
  // the app only talks to its own host, so nothing depends on services blocked in mainland China.
  test("home loads and contacts no third-party host", async ({ app, page, foreignHosts }) => {
    await app.start("today");
    await page.waitForLoadState("networkidle");
    expect(foreignHosts, `third-party hosts contacted: ${foreignHosts.join(", ")}`).toEqual([]);
  });

  test("the synthetic-data banner is visible in demo mode", async ({ app }) => {
    await app.start("today");
    await expect(app.banner()).toBeVisible();
  });
});

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a signed-out visitor is sent to sign in, keeping where they were going", async ({ app, page }) => {
    await page.goto("/cash");
    await expect(page).toHaveURL(/\/login\?next=%2Fcash$/);
    await expect(page.getByRole("heading", { level: 2, name: app.t("auth.title") })).toBeVisible();
    await expect(app.banner()).toBeVisible();
  });
});
