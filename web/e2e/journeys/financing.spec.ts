// Flow 4: financing match -> open the provenance of the best option's true cost -> the
// pre-filled application, which leaves only after the owner approves it with a step-up code
// (WP-06 match + submit_loan_application through WP-11 approvals) -> the audit log.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { needsRoutes } from "../support/target";

test.use({ storageState: sessionFile("owner") });

test("the owner matches financing, opens how the true cost was calculated, and submits the application with a code", async ({ app, page }) => {
  test.setTimeout(180_000);
  await needsRoutes(["POST /api/financing/match", "POST /api/approvals", "POST /api/approvals/probe/approve"]);
  const owner = await app.account("owner");

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
  const application = page.getByRole("article").filter({ hasText: app.t("action.submit_loan_application") });
  await expect(application).toContainText(app.t("tier.EXECUTE"));
  const approve = application.getByRole("button", { name: app.t("actionCard.approveWithCode") });

  // Nothing leaves without a fresh code: cancelling the step-up sends nothing.
  let sent = false;
  const watch = (request: { method(): string; url(): string }) => {
    if (request.method() === "POST" && /\/api\/approvals/.test(request.url())) sent = true;
  };
  page.on("request", watch);
  await approve.click();
  await app.stepUpDialog().getByRole("button", { name: app.t("common.cancel") }).click();
  await expect(app.stepUpDialog()).toBeHidden();
  expect(sent).toBe(false);
  page.off("request", watch);

  // With the code it goes through: requested, approved with step-up, executed, and on record.
  const requested = page.waitForResponse((response) => /\/api\/approvals$/.test(response.url()) && response.request().method() === "POST");
  await approve.click();
  await app.confirmStepUp(owner);
  await expect(application).toContainText(app.t("actionCard.executed"));
  const approval = (await (await requested).json()) as { approval: { id: string; tier: string }; action_type: string };
  expect(approval).toMatchObject({ approval: { tier: "EXECUTE" }, action_type: "submit_loan_application" });

  await app.open("trust");
  await expect(page.getByRole("table", { name: app.t("trust.eventsTitle") })).toContainText(approval.approval.id);
  await expect(page.getByText(tPattern("trust.chainValid", { value: "[\\d,]+" }))).toBeVisible();
});
