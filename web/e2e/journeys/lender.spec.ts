// Journey: a lender viewer (WP-11 consented lender access) sees only what was shared: the Trust
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
});

// Known gaps, found by this suite (WP-15.md, Notes): WP-11 grants a lender no ledger:read, yet
// GET /api/facts/{metric} computes ledger figures for one and GET /api/ingest/history lists the
// shop's uploads. Expected to fail until those routes check the permission; Playwright reports
// them as soon as they pass, so the markers can come off.
test("the lender viewer cannot read ledger figures", async ({ page }) => {
  test.fail(true, "WP-01: GET /api/facts/{metric} does not check ledger:read");
  knownBug("WP-01 (security): GET /api/facts/{metric} computes the shop's ledger figures for a lender viewer, who holds no ledger:read");
  const response = await page.request.get("/api/facts/net_sales?start=2026-09-01&end=2026-09-30&granularity=month");
  expect(response.status()).toBe(403);
});

test("the lender viewer cannot list the shop's uploads", async ({ page }) => {
  test.fail(true, "WP-02: GET /api/ingest/history does not check ledger:read");
  knownBug("WP-02 (security): GET /api/ingest/history lists the shop's uploads to a lender viewer, who holds no ledger:read");
  const response = await page.request.get("/api/ingest/history");
  expect(response.status()).toBe(403);
});
