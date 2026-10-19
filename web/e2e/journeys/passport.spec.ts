// Flow 8: Reports -> the Trust Passport -> the public verify page (WP-13 through WP-14), plus
// sharing it with a lender behind a step-up code and revoking that share.
import { sessionFile } from "../support/auth";
import { expect, test, type StepUpCall } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { needsRoutes } from "../support/target";

const SHARE: StepUpCall = { route: "POST /api/reports/passport/probe/share", url: /\/api\/reports\/passport\/[^/]+\/share$/ };

test.describe("owner", () => {
  test.use({ storageState: sessionFile("owner") });

  test("the owner opens the Trust Passport, checks it on the public verify page, shares it with a lender and revokes", async ({ app, page, browser, baseURL }) => {
    await needsRoutes(["GET /api/reports/passport", "POST /api/reports/passport/probe/share", "GET /api/verify/probe"]);
    const owner = await app.account("owner");

    await app.start("reports");
    const passport = page.getByRole("region", { name: app.t("reports.passportTitle") });
    const latest = passport.getByRole("article").first();
    await expect(latest.getByRole("heading", { level: 4 })).toHaveText(tPattern("reports.version", { version: "\\d+" }, "en", false));
    await expect(latest).toContainText(app.t("mesh.chain.sepolia"));
    await expect(latest.getByText(tPattern("reports.digest", { hash: "[0-9a-f]{10}…[0-9a-f]{6}" }))).toBeVisible();

    // Share with a lender: limited scope and time, and a fresh code.
    const share = page.getByRole("form", { name: app.t("reports.shareTitle") });
    const lender = `Lender E2E ${Date.now().toString(36)}`;
    await share.getByLabel(app.t("reports.lender")).fill(lender);
    await share.getByLabel(app.t("reports.expiresIn")).selectOption("7");
    await share.getByRole("button", { name: app.t("reports.shareWithCode") }).click();
    await expect(app.stepUpDialog()).toContainText(app.t("reports.shareSummary", { lender, days: 7 }));
    await app.confirmStepUp(owner, SHARE);
    const shares = page.getByRole("region", { name: app.t("reports.sharesTitle") });
    const grant = shares.getByRole("listitem", { name: lender });
    await expect(grant).toContainText(app.t("reports.scope.passport_read"));
    await grant.getByRole("button", { name: app.t("reports.revoke") }).click();
    await expect(grant).toContainText(app.t("reports.revoked"));

    // The verify page recomputes the fingerprint and compares it with the anchored one.
    await latest.getByRole("link", { name: app.t("reports.openVerify") }).click();
    await expect(page).toHaveURL(/\/verify\/[^/]+$/);
    const verifyUrl = page.url();
    await page.getByRole("button", { name: app.t("verify.check") }).click();
    await expect(page.getByText(app.t("verify.valid"))).toBeVisible();

    // Anyone can check it, signed out.
    const visitor = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
    try {
      const view = await visitor.newPage();
      await view.goto(verifyUrl);
      await expect(view.getByRole("heading", { level: 2, name: app.t("verify.title") })).toBeVisible();
      await view.getByRole("button", { name: app.t("verify.check") }).click();
      await expect(view.getByText(app.t("verify.valid"))).toBeVisible();
    } finally {
      await visitor.close();
    }
  });
});
