// Permission tiers (CLAUDE.md rule 4, WP-11): staff see a money-moving card but only the owner
// may approve it, in the UI and at the API; a DENY action is refused whoever asks.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { apiContext, needsRoutes } from "../support/target";

const RETIME = { id: "e2e-tier-retime", title_key: "action.retime_payable", action_type: "retime_payable", tier: "EXECUTE", payload: {} };
const MOVE_MONEY = { id: "e2e-tier-move-money", title_key: "action.move_money", action_type: "move_money", tier: "EXECUTE", payload: {} };

function key(): Record<string, string> {
  return { "X-Idempotency-Key": `e2e-${Date.now()}-${Math.random().toString(36).slice(2)}` };
}

test.describe("staff", () => {
  test.use({ storageState: sessionFile("staff") });

  test("staff see the day's actions but cannot approve one that moves money; nobody can request a DENY action", async ({ app, page }) => {
    await needsRoutes(["GET /api/copilot/today"]);

    await app.start("today");
    const actions = page.getByRole("region", { name: app.t("today.actionsTitle") });
    const execute = actions.getByRole("article").filter({ hasText: app.t("tier.EXECUTE") }).first();
    await expect(execute).toContainText(app.t("actionCard.ownerOnly"));
    for (const action of ["actionCard.approveWithCode", "actionCard.askOwner"]) {
      await expect(execute.getByRole("button", { name: app.t(action) })).toHaveCount(0);
    }
    // Staff work on sales and collections; cash planning stays with the owner and accountant.
    const nav = app.isPhone ? page.getByRole("navigation", { name: app.t("nav.quick") }) : app.mainNav();
    await expect(nav.getByRole("link", { name: app.t("nav.cash"), exact: true })).toHaveCount(0);

    // The API agrees: staff cannot even ask for the approval.
    const asked = await page.request.post("/api/approvals", { data: { card: RETIME }, headers: key() });
    expect(asked.status()).toBe(403);

    // DENY: not even the owner may request it (the owner's saved session, outside this page).
    const owner = await apiContext(sessionFile("owner"));
    try {
      const denied = await owner.post("/api/approvals", { data: { card: MOVE_MONEY }, headers: key() });
      expect(denied.status()).toBe(403);
      expect(((await denied.json()) as { code: string }).code).toBe("action_denied");
    } finally {
      await owner.dispose();
    }
  });
});
