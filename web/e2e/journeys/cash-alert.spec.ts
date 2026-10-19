// Flow 3: a Critical cash alert is pinned on Today -> its ranked fixes on Cash -> the owner
// approves an EXECUTE lever with a step-up code (WP-11 approvals: request, approve, execute)
// -> the action is in the audit log and the chain still verifies.
//
// With WP-04 live the alert is the engine's own: the setup project found an owner whose business
// it flags as Critical (auth.setup.ts). Without it, a labelled stand-in plays that alert.
import { existsSync } from "node:fs";

import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { CRITICAL_LEVER_ID, standInCriticalAlert } from "../support/stand-ins";
import { needsRoutes } from "../support/target";

test.use({ storageState: { cookies: [], origins: [] } });

test("a Critical alert is pinned on Today and the owner approves its lever with a code", async ({ app, page }) => {
  test.setTimeout(240_000); // the real engine runs 1,000 paths per answer, and codes may queue
  const live = await needsRoutes(["GET /api/cash/alerts", "POST /api/approvals", "POST /api/approvals/probe/approve"]);
  if (live["GET /api/cash/alerts"]) {
    const file = sessionFile("critical_owner");
    expect(existsSync(file), "a demo business the cash engine flags as Critical (seeded ledger)").toBe(true);
    await app.useSession(file);
  } else {
    await app.useSession(sessionFile("owner"));
    const me = (await (await page.request.get("/api/auth/me")).json()) as { principal: { tenant_id: string } };
    await standInCriticalAlert(page, me.principal.tenant_id);
  }
  const owner = await app.signedInAccount();

  await app.start("today");
  // Critical alerts come first, above the cash figures.
  const firstAlert = page.locator("article[data-alert-tier]").first();
  await expect(firstAlert).toHaveAttribute("data-alert-tier", "critical", { timeout: 60_000 });
  await expect(firstAlert).toContainText(app.t("alertTier.critical"));
  await expect(firstAlert.getByRole("button", { name: new RegExp(app.t("today.shortfall")) })).toBeVisible();

  await firstAlert.getByRole("link", { name: tPattern("today.seeFixes", { count: "\\d+" }) }).click();
  await expect(app.heading("cash")).toBeVisible();

  const levers = page.getByRole("region", { name: app.t("cash.leversTitle") });
  const lever = levers.getByRole("article").filter({ hasText: app.t("tier.EXECUTE") }).first();
  await expect(lever).toBeVisible({ timeout: 60_000 });
  if (!live["GET /api/cash/alerts"]) await expect(lever).toContainText(app.t("action.retime_payable"));

  const requested = page.waitForResponse((response) => /\/api\/approvals$/.test(response.url()) && response.request().method() === "POST");
  await lever.getByRole("button", { name: app.t("actionCard.approveWithCode") }).click();
  await expect(app.stepUpDialog()).toContainText(app.t("stepUp.help"));
  await app.confirmStepUp(owner);
  await expect(lever).toContainText(app.t("actionCard.executed"));

  // The approval went through the real chain: requested, approved with step-up, executed.
  const approval = (await (await requested).json()) as { approval: { id: string; action_card_id: string; tier: string } };
  expect(approval.approval.tier).toBe("EXECUTE");
  if (!live["GET /api/cash/alerts"]) expect(approval.approval.action_card_id).toBe(CRITICAL_LEVER_ID);

  await app.open("trust");
  await expect(page.getByRole("table", { name: app.t("trust.eventsTitle") })).toContainText(approval.approval.id);
  await expect(page.getByText(tPattern("trust.chainValid", { value: "[\\d,]+" }))).toBeVisible();
});
