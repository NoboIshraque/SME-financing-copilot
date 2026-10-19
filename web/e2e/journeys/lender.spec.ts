// Flow 10: a lender viewer (WP-11 consented lender access) sees only what was shared: the Trust
// Passport and their own settings. Other screens say so plainly, and the API refuses the rest.
import { sessionFile } from "../support/auth";
import { expect, knownBug, test } from "../support/fixtures";
import { tPattern } from "../support/i18n";

test.use({ storageState: sessionFile("lender_viewer") });

test("the lender viewer sees only the shared Trust Passport, and the API refuses everything else", async ({ app, page }) => {
  await page.goto("/");
  // A lender lands on Reports, not Today.
  await expect(app.heading("reports")).toBeVisible();
  await expect(page).toHaveURL(/\/reports$/);

  const visible = app.isPhone
    ? page.getByRole("navigation", { name: app.t("nav.quick") }).getByRole("link")
    : app.mainNav().getByRole("link");
  await expect(visible).toHaveText([app.t("nav.reports"), app.t("nav.settings")]);
  await expect(page.getByRole("button", { name: app.t("copilot.open") })).toHaveCount(0);

  // Read-only passport with the access end date; no issuing, sharing or share list.
  await expect(page.getByRole("note")).toHaveText(tPattern("reports.lenderAccess", { date: ".+" }));
  await expect(page.getByRole("region", { name: app.t("reports.passportTitle") }).getByRole("article")).toBeVisible();
  await expect(page.getByRole("button", { name: app.t("reports.issue") })).toHaveCount(0);
  await expect(page.getByRole("form", { name: app.t("reports.shareTitle") })).toHaveCount(0);
  await expect(page.getByRole("region", { name: app.t("reports.sharesTitle") })).toHaveCount(0);

  // Typing another screen's address explains instead of showing the shop's data.
  await page.goto("/cash");
  await expect(page.getByRole("heading", { level: 2, name: app.t("shell.notForRoleTitle") })).toBeVisible();
  await expect(page.getByText(app.t("shell.notForRole", { role: app.t("role.lender_viewer") }))).toBeVisible();

  // The API is the boundary, not the navigation (WP-11).
  for (const path of ["/api/approvals?status=pending", "/api/audit/events?limit=20", "/api/guard/quarantine"]) {
    expect((await page.request.get(path)).status(), path).toBe(403);
  }
  const card = { id: "e2e-lender-card", title_key: "action.retime_payable", action_type: "retime_payable", tier: "EXECUTE", payload: {} };
  const write = await page.request.post("/api/approvals", { data: { card }, headers: { "X-Idempotency-Key": `e2e-${Date.now()}` } });
  expect(write.status()).toBe(403);

  // Known gaps: WP-11 grants a lender no ledger:read, yet these routes do not check it. Reported in
  // the run's known-bugs list while they stay open (WP-15.md, Notes).
  const gaps = {
    "/api/facts/net_sales?start=2026-09-01&end=2026-09-30&granularity=month":
      "WP-01 (security): GET /api/facts/{metric} computes the shop's ledger figures for a lender viewer, who holds no ledger:read",
    "/api/ingest/history": "WP-02 (security): GET /api/ingest/history lists the shop's uploads to a lender viewer, who holds no ledger:read",
  };
  for (const [path, bug] of Object.entries(gaps)) {
    if ((await page.request.get(path)).status() !== 403) knownBug(bug);
  }
});
