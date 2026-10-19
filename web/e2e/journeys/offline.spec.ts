// Journey: the connection drops (WP-14 milestone 12, PWA). The app says so, the shell keeps
// working, and the notice clears when the connection is back.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";

test.use({ storageState: sessionFile("owner") });

test("losing the connection shows the offline notice, and it clears once back online", async ({ app, page, context }) => {
  await app.start("today");
  const notice = page.getByText(app.t("shell.offline"));
  await expect(notice).toHaveCount(0);

  await context.setOffline(true);
  await expect(notice).toBeVisible();
  await expect(notice).toHaveAttribute("aria-live", "polite");
  // Navigation still works: the shell is already loaded, only numbers need the server.
  await app.open("settings");

  await context.setOffline(false);
  await expect(notice).toHaveCount(0);
});
