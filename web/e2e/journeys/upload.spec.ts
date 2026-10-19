// Journey: upload a bKash statement -> preview -> commit (WP-02 ingest through the copilot's
// upload flow). The statement is generated per run with fresh transaction ids, so every run adds
// new rows, and the re-upload proves duplicates are caught. Labelled synthetic (rule 8). It runs as
// the owner of the second demo business, so the home business's demo figures stay as seeded.
import { randomBytes } from "node:crypto";

import { demoAccounts, HOME_TENANT_INDEX } from "../support/accounts";
import { expect, test } from "../support/fixtures";
import { needsRoutes } from "../support/target";

test.use({ storageState: { cookies: [], origins: [] } });

const HEADER = "TrxID,Date Time,Transaction Type,From/To,Amount (BDT),Fee,Balance,Reference,Data Mode";

function bkashStatement(rows: number): { name: string; mimeType: string; buffer: Buffer } {
  const run = randomBytes(4).toString("hex").toUpperCase();
  let balance = 50_000;
  const lines = Array.from({ length: rows }, (_, i) => {
    const trxId = randomBytes(5).toString("hex").toUpperCase(); // 10 characters, like bKash's
    const amount = 500 + Math.floor(Math.random() * 4000);
    balance += amount;
    const time = `${String(10 + i).padStart(2, "0")}:${String(7 * i + 3).padStart(2, "0")}:00`;
    return `${trxId},28/09/2026 ${time},Payment Received,0171000${String(1000 + i)},${amount}.00,0.00,${balance}.00,E2E-${run},synthetic`;
  });
  return { name: `bkash_statement_e2e_${run}.csv`, mimeType: "text/csv", buffer: Buffer.from([HEADER, ...lines].join("\n") + "\n") };
}

test("the owner uploads a bKash statement, checks the preview and commits it; a re-upload is caught as duplicates", async ({ app, page }) => {
  test.setTimeout(180_000); // the owner's sign-in may wait for a fresh TOTP step
  await needsRoutes(["POST /api/ingest/preview", "POST /api/ingest/commit"], { mockCannot: "parse a real file" });
  const accounts = await demoAccounts(page.request);
  const home = accounts[HOME_TENANT_INDEX]?.business_name;
  const owner = accounts.find((account) => account.role === "owner" && account.business_name !== home);
  if (!owner) throw new Error("no second demo business");
  await app.signInAs(owner);
  const statement = bkashStatement(3);

  // The copilot (and its upload) is on every screen; Settings runs no engine, so nothing else is
  // writing (the local dev API is SQLite: a forecast being recorded would lock the upload out).
  await app.start("settings");
  await page.getByRole("button", { name: app.t("copilot.open") }).click();
  await page.getByRole("dialog", { name: app.t("copilot.title") }).getByRole("button", { name: app.t("upload.open") }).click();
  const dialog = page.getByRole("dialog", { name: app.t("upload.title") });
  const file = dialog.getByLabel(app.t("upload.choose"));

  await file.setInputFiles(statement);
  await expect(dialog.getByText(app.t("upload.format.bkash_statement"), { exact: true })).toBeVisible();
  await expect(dialog.getByText(app.t("upload.transactions", { count: 3 }))).toBeVisible();

  // Nothing is written before the owner confirms.
  const before = await page.request.get("/api/ingest/history");
  expect(((await before.json()) as { filename: string }[]).map((item) => item.filename)).not.toContain(statement.name);

  await dialog.getByRole("button", { name: app.t("upload.commit", { count: 3 }) }).click();
  await expect(dialog.getByText(app.t("upload.done", { count: 3 }))).toBeVisible();

  const history = (await (await page.request.get("/api/ingest/history")).json()) as { filename: string; transactions: number; data_mode: string }[];
  expect(history.find((item) => item.filename === statement.name)).toMatchObject({ transactions: 3, data_mode: "synthetic" });

  // The same statement again: every row is already in the ledger.
  await file.setInputFiles(statement);
  await expect(dialog.getByText(app.t("upload.duplicates", { count: 3 }))).toBeVisible();
  await expect(dialog.getByRole("button", { name: app.t("upload.commit", { count: 0 }) })).toBeDisabled();
});
