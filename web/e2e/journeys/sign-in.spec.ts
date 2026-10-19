// Journey: sign in with password + TOTP (WP-11 through WP-14's sign-in screen), and sign out.
import type { Page, Response } from "@playwright/test";

import { expect, test } from "../support/fixtures";
import { tPattern } from "../support/i18n";
import { withFreshCode } from "../support/totp";

test.use({ storageState: { cookies: [], origins: [] } });

/** Click, and click again after the Retry-After if the sign-in rate limit (WP-11) answered 429. */
async function clickAnswered(page: Page, click: () => Promise<void>, url: RegExp): Promise<Response> {
  for (let attempt = 1; ; attempt += 1) {
    const answer = page.waitForResponse((response) => url.test(response.url()) && response.request().method() === "POST");
    await click();
    const response = await answer;
    if (response.status() !== 429 || attempt === 3) return response;
    await page.waitForTimeout(Number(response.headers()["retry-after"] ?? "5") * 1000 + 250);
  }
}

test("the owner signs in with a password and a TOTP code, and signs out again", async ({ app, page }) => {
  const owner = await app.account("owner");

  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?next=%2F$/);

  // Demo mode lists one-tap accounts; the owner's still needs the second factor.
  const demoButton = page.getByRole("button", { name: new RegExp(`^${app.t("auth.demoAs", { role: app.t("role.owner") })}`) })
    .filter({ hasText: owner.business_name });
  const login = await clickAnswered(page, () => demoButton.click(), /\/api\/auth\/login$/);
  expect(login.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 2, name: app.t("auth.totpTitle") })).toBeVisible();
  await expect(page.getByText(tPattern("auth.demoCode", { code: "\\d{6}" }))).toBeVisible();

  const codeField = page.getByLabel(app.t("auth.code"));
  const verify = page.getByRole("button", { name: app.t("auth.verify") });

  await withFreshCode(page.request, owner, async (code) => {
    // A wrong code is refused on the spot and the screen stays on the code step.
    const wrong = code.replace(/^\d/, (digit) => String((Number(digit) + 5) % 10));
    await codeField.fill(wrong);
    const refused = await clickAnswered(page, () => verify.click(), /\/api\/auth\/login\/totp$/);
    expect(refused.status()).toBe(401);
    await expect(page.getByRole("alert")).toHaveText(app.t("error.invalid_totp"));
    await expect(codeField).toHaveAttribute("aria-invalid", "true");

    await codeField.fill(code);
    const accepted = await clickAnswered(page, () => verify.click(), /\/api\/auth\/login\/totp$/);
    if (accepted.status() === 401) return false; // that step was used elsewhere: next code
    expect(accepted.status()).toBe(200);
    return true;
  });

  await expect(app.heading("today")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("banner")).toContainText(owner.business_name);

  await page.getByRole("button", { name: app.t("shell.signOut") }).click();
  await expect(page).toHaveURL(/\/login(\?next=%2F)?$/);
  await expect(page.getByRole("heading", { level: 2, name: app.t("auth.title") })).toBeVisible();
  // The server ended the session: coming back to the app asks to sign in again.
  await page.goto("/cash");
  await expect(page).toHaveURL(/\/login\?next=%2Fcash$/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});
