// Journey: financing match -> open the provenance of the best option's true cost -> the drafted
// application waits behind a step-up code (WP-06 through WP-14's financing screen).
//
// Approving the application is not part of this journey yet: WP-11's policy gives the owner only
// DRAFT on draft_loan_application while the application card is EXECUTE, so the approval API
// refuses it (question open in WP-06.md). The journey checks the draft is offered and that nothing
// is sent until the owner confirms with a code.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { needsRoutes } from "../support/target";

test.use({ storageState: sessionFile("owner") });

test("the owner matches financing, opens how the true cost was calculated, and finds the application drafted", async ({ app, page }) => {
  await needsRoutes(["POST /api/financing/match"]);

  await app.start("financing");
  await page.getByRole("button", { name: app.t("financing.find") }).click();
  const results = page.getByRole("region", { name: app.t("financing.optionsTitle") });
  await expect(results).toBeVisible();

  // Options are ranked; each shows its true yearly cost as a number with provenance.
  const options = results.getByRole("listitem").filter({ has: page.getByRole("article") });
  expect(await options.count()).toBeGreaterThan(1);
  const best = options.first().getByRole("article");
  await expect(best.getByLabel(app.t("financing.rank", { rank: 1 }))).toBeVisible();
  const trueCost = best.getByRole("button", { name: new RegExp(`^${app.t("financing.effective_apr")}: `) });
  const shown = (await trueCost.innerText()).trim();
  expect(shown).toMatch(/%$/);

  await trueCost.click();
  const drawer = page.getByRole("dialog", { name: app.t("financing.effective_apr") });
  await expect(drawer).toContainText(app.t("provenance.title"));
  await expect(drawer.getByRole("heading", { name: app.t("provenance.formula") })).toBeVisible();
  await expect(drawer).toContainText(/financing\.\w+, version \d+/);
  await expect(drawer).toContainText(app.t("provenance.codeComputes"));
  await drawer.getByRole("button", { name: app.t("provenance.close") }).click();
  await expect(drawer).toBeHidden();

  // The application is pre-filled for the best option the business qualifies for.
  await expect(page.getByText(app.t("financing.applicationHelp"))).toBeVisible();
  const application = page.getByRole("article").filter({ hasText: app.t("action.draft_loan_application") });
  await expect(application).toContainText(app.t("tier.EXECUTE"));

  // Nothing leaves without a fresh code: cancelling the step-up sends nothing.
  let sent = false;
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/approvals/.test(request.url())) sent = true;
  });
  await application.getByRole("button", { name: app.t("actionCard.approveWithCode") }).click();
  const stepUp = app.stepUpDialog();
  await expect(stepUp).toContainText(app.t("stepUp.help"));
  await stepUp.getByRole("button", { name: app.t("common.cancel") }).click();
  await expect(stepUp).toBeHidden();
  await expect(application.getByRole("button", { name: app.t("actionCard.approveWithCode") })).toBeVisible();
  expect(sent).toBe(false);
});
