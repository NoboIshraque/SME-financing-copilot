// Flow 11: permission tiers (CLAUDE.md rule 4, WP-11). Staff see a money-moving card but get no
// control to approve it, and the API refuses them; a DENY action is refused even to the owner.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { apiContext, needsRoutes, routeIsLive, TARGET } from "../support/target";

const RETIME = { id: "e2e-tier-retime", title_key: "action.retime_payable", action_type: "retime_payable", tier: "EXECUTE", payload: {} };
const BANK_CHANGE = { id: "e2e-tier-bank-change", title_key: "action.change_bank_details", action_type: "change_bank_details", tier: "EXECUTE", payload: {} };

function key(): Record<string, string> {
  return { "X-Idempotency-Key": `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}` };
}

test.use({ storageState: sessionFile("staff") });

test("staff cannot approve what moves money, and nobody may request a DENY action", async ({ app, page }) => {
  await needsRoutes(["POST /api/approvals"]);

  // Today's cards come from the copilot (WP-10; the labelled mock on the local target).
  if (TARGET === "local" || (await routeIsLive("GET /api/copilot/today"))) {
    await app.start("today");
    const actions = page.getByRole("region", { name: app.t("today.actionsTitle") });
    await expect(actions).toBeVisible();
    // The live copilot offers staff only cards their role may act on (WP-10, P9); any money-moving
    // card that does show must still be owner-only, with no control for staff.
    const execute = actions.getByRole("article").filter({ hasText: app.t("tier.EXECUTE") });
    for (const card of await execute.all()) {
      await expect(card).toContainText(app.t("actionCard.ownerOnly"));
      for (const action of ["actionCard.approveWithCode", "actionCard.askOwner"]) {
        await expect(card.getByRole("button", { name: app.t(action) })).toHaveCount(0);
      }
    }
    // Staff work on sales and collections; cash planning stays with the owner and accountant.
    const nav = app.isPhone ? page.getByRole("navigation", { name: app.t("nav.quick") }) : app.mainNav();
    await expect(nav.getByRole("link", { name: app.t("nav.cash"), exact: true })).toHaveCount(0);
  } else {
    test.info().annotations.push({ type: "not deployed", description: "GET /api/copilot/today: the UI half was not run" });
  }

  // The API is the boundary: staff may only suggest a payable's new date, so they cannot even ask.
  const asked = await page.request.post("/api/approvals", { data: { card: RETIME }, headers: key() });
  expect(asked.status()).toBe(403);

  // DENY: not even the owner may ask to change a supplier's bank details (classic invoice fraud).
  const owner = await apiContext(sessionFile("owner"));
  try {
    const denied = await owner.post("/api/approvals", { data: { card: BANK_CHANGE }, headers: key() });
    expect(denied.status()).toBe(403);
    expect(((await denied.json()) as { code: string }).code).toBe("action_denied");
  } finally {
    await owner.dispose();
  }
});
