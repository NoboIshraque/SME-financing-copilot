import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import { renderApp, requestedPaths } from "../../test/render";

describe("Messages & approvals inbox", () => {
  it("shows the owner what the accountant asked to approve, and clears it once approved with the code", async () => {
    const { user, db } = renderApp("/messages");
    const queue = await screen.findByRole("region", { name: "Waiting for your approval" });
    const request = await within(queue).findByRole("article", { name: "Submit the loan application" });
    expect(within(queue).getByText(/^Requested by u-accountant/)).toBeInTheDocument();
    await user.click(within(request).getByRole("button", { name: "Approve with code" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    expect(await within(queue).findByText("Nothing is waiting for approval.")).toBeInTheDocument();
    expect(db.approvals[0]?.approval.status).toBe("executed");
  });

  it("tells the accountant a requested approval is waiting for the owner", async () => {
    renderApp("/messages", { signedInAs: "accountant@hishab.demo" });
    const queue = await screen.findByRole("region", { name: "Waiting for your approval" });
    const request = await within(queue).findByRole("article", { name: "Submit the loan application" });
    expect(within(request).getByText("Waiting for the owner's approval.")).toBeInTheDocument();
    expect(within(request).queryByRole("button", { name: /Approve|Ask the owner/ })).not.toBeInTheDocument();
  });

  it("approves a Bangla draft, then copies exactly the approved text", async () => {
    const { user, db } = renderApp("/messages");
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    const draft = await screen.findByRole("article", { name: "Friendly reminder before the due date · Customer 11" });
    const body = within(draft).getByText(/প্রিয় Customer 11/);
    expect(body).toHaveAttribute("lang", "bn");

    await user.click(within(draft).getByRole("button", { name: "Approve message" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await user.click(await within(draft).findByRole("button", { name: "Copy message" }));
    expect(writeText).toHaveBeenCalledWith(db.drafts[0]?.body);
    expect(within(draft).getByRole("button", { name: "Copied. Paste it into your chat app." })).toBeInTheDocument();
    expect(db.drafts[0]?.status).toBe("approved");
  });

  it("sends an approved email draft and shows it as sent", async () => {
    const { user, db } = renderApp("/messages");
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    await user.click(within(draft).getByRole("button", { name: "Approve message" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await user.click(await within(draft).findByRole("button", { name: "Send" }));
    expect(await within(draft).findByText("Sent", { selector: "p" })).toBeInTheDocument();
    expect(db.drafts[1]?.status).toBe("sent");
  });

  it("keeps a draft unapproved when the code is wrong", async () => {
    const { user, db } = renderApp("/messages");
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    await user.click(within(draft).getByRole("button", { name: "Approve message" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "111111");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
    expect(db.drafts[1]?.status).toBe("draft");
  });

  it("leaves message approval to the owner: the accountant sees no approve button", async () => {
    renderApp("/messages", { signedInAs: "accountant@hishab.demo" });
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    expect(within(draft).getByText("Your role can't approve this.")).toBeInTheDocument();
    expect(within(draft).queryByRole("button", { name: "Approve message" })).not.toBeInTheDocument();
  });

  it("asks for Bangla drafts when the owner reads in Bangla", async () => {
    await i18n.changeLanguage("bn");
    const { fetchMock } = renderApp("/messages");
    await screen.findAllByRole("article");
    expect(requestedPaths(fetchMock)).toContain("/api/messages/drafts?language=bn");
  });

  it("does not let staff approve drafts", async () => {
    renderApp("/messages", { signedInAs: "staff@hishab.demo" });
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    expect(within(draft).getByText("Your role can't approve this.")).toBeInTheDocument();
    expect(within(draft).queryByRole("button")).not.toBeInTheDocument();
  });
});
