// Flow 6: a receivables reminder (WP-05 plan, WP-12 draft) approved in one tap on Receivables,
// then found approved in Messages and sent from there.
import { sessionFile } from "../support/auth";
import { expect, test } from "../support/fixtures";
import { needsRoutes } from "../support/target";

test.use({ storageState: sessionFile("owner") });

test("the owner approves a reminder draft on Receivables and sends it from Messages", async ({ app, page }) => {
  await needsRoutes(["GET /api/receivables/plan", "GET /api/messages/drafts", "POST /api/messages/probe/approve"]);

  await app.start("receivables");
  const reminders = page.getByRole("region", { name: app.t("receivables.remindersTitle") });
  await expect(reminders.getByRole("article").first()).toBeVisible();
  // Live WP-05: a reminder leaves Hishab, so each card is EXECUTE and waits in the owner's approval
  // queue (WP-12 sending was cut 19 Oct; N2 keeps drafts there). The draft-in-Messages half below
  // runs only against the labelled mock plan.
  const live = reminders.getByRole("article").filter({ hasText: app.t("tier.EXECUTE") });
  if ((await live.count()) > 0) {
    await expect(live.first().getByRole("button", { name: app.t("actionCard.approveWithCode") })).toBeVisible();
    test.info().annotations.push({ type: "live plan", description: "EXECUTE reminders; Messages half not run" });
    return;
  }
  const first = reminders.getByRole("article").filter({ has: page.getByRole("button", { name: app.t("actionCard.approveDraft") }) }).first();
  // "Customer 9 · 4 invoices · due ...": the first detail is who the reminder goes to.
  const recipient = (await first.locator("h4 + p").innerText()).split(" · ")[0]?.trim() ?? "";
  expect(recipient).not.toBe("");
  const reminder = reminders.getByRole("article").filter({ has: page.getByText(new RegExp(`^${recipient} · `)) });
  await expect(reminder).toContainText(app.t("tier.DRAFT"));

  await reminder.getByRole("button", { name: app.t("actionCard.approveDraft") }).click();
  await expect(reminder).toContainText(app.t("actionCard.approved"));

  await app.open("messages");
  const drafts = page.getByRole("region", { name: app.t("messages.draftsTitle") });
  const draft = drafts.getByRole("article").filter({ has: page.getByRole("heading", { name: new RegExp(`· ${recipient}$`) }) });
  await expect(draft).toContainText(app.t("messages.status.approved"));
  // Approved is not sent: the owner still sends it (or copies it into a chat app).
  const send = draft.getByRole("button", { name: app.t("messages.send"), exact: true });
  if ((await send.count()) > 0) {
    await send.click();
    await expect(draft).toContainText(app.t("messages.sent"));
  } else {
    await expect(draft.getByRole("button", { name: app.t("messages.copy") })).toBeVisible();
  }
});
