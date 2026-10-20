// Market (WP-09, N3): the screen shows TCB's published Dhaka price list with its date and a link
// to the source, not the bundled sample label.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { needsRoutes } from "../support/target";

test.use({ storageState: sessionFile("owner") });

test("the Market screen names TCB's list and its publication date instead of the sample label", async ({ app, page }) => {
  await needsRoutes(["GET /api/market/prices"], { mockCannot: "serve TCB's published lists" });

  await app.start("market");
  const note = page.getByRole("note").filter({ hasText: tPattern("market.sourceNoteAt", { source: ".+", place: ".+", date: ".+" }, app.language, false) });
  await expect(note).toBeVisible();
  await expect(note.getByRole("link", { name: app.t("market.sourceLink") })).toHaveAttribute("href", /^https:\/\//);
  const watch = page.getByRole("region", { name: app.t("market.watchTitle") });
  await expect(watch.getByRole("row").nth(1)).toContainText(app.t("market.source.tcb"));
  await expect(watch.getByText(app.t("market.sampleLabel"))).toHaveCount(0);
  await expect(page.getByText(app.t("market.sampleNote"))).toHaveCount(0);

  // Vendors (the shop's own ledger suppliers, synthetic quotes) and the negotiation plan are live too.
  const vendors = page.getByRole("region", { name: app.t("market.vendorsTitle") });
  await vendors.getByRole("button", { name: app.t("market.rank") }).click();
  await expect(vendors.getByRole("listitem").first()).toContainText(/Supplier \d+/);
  await expect(vendors.getByText(app.t("market.sampleLabel"))).toHaveCount(0);
  const negotiate = page.getByRole("region", { name: app.t("market.negotiateTitle") });
  await negotiate.getByRole("button", { name: app.t("market.makePlan") }).click();
  await expect(negotiate.getByText(app.t("market.walkAway"))).toBeVisible();
  await expect(negotiate).toContainText(app.t("market.cost_of_money"));
  await expect(negotiate.getByText(app.t("market.sampleLabel"))).toHaveCount(0);

  // The owner can pick another place: a WFP market elsewhere in Bangladesh, or China.
  const picker = page.getByLabel(app.t("market.location"));
  await picker.selectOption({ label: `Gazipur Sadar (${app.t("market.cadence.monthly")})` });
  await expect(note).toContainText(app.t("market.sourceName.wfp"));
  await expect(note).toContainText("Gazipur Sadar");
  await picker.selectOption("cn-national");
  await expect(note).toContainText(app.t("market.sourceName.nbs"));
  await expect(watch.getByRole("row").nth(1)).toContainText("¥");
});

