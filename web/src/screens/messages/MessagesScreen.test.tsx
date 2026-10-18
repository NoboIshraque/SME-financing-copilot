import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderApp } from "../../test/render";

describe("Messages & approvals inbox", () => {
  it("queues every DRAFT and EXECUTE card for a decision, and drops one once approved", async () => {
    const { user } = renderApp("/messages");
    const queue = await screen.findByRole("region", { name: "Waiting for your approval" });
    const cards = await within(queue).findAllByRole("article");
    expect(cards).toHaveLength(5);
    const reminder = within(queue).getAllByRole("article", { name: "Send a payment reminder" })[0] as HTMLElement;
    await user.click(within(reminder).getByRole("button", { name: "Approve draft" }));
    await waitFor(() => expect(within(queue).getAllByRole("article")).toHaveLength(4));
  });

  it("approves a Bangla draft, then copies exactly the approved text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { user, db } = renderApp("/messages");
    const draft = await screen.findByRole("article", { name: "Friendly reminder before the due date · Customer 11" });
    const body = within(draft).getByText(/প্রিয় Customer 11/);
    expect(body).toHaveAttribute("lang", "bn");

    await user.click(within(draft).getByRole("button", { name: "Approve message" }));
    await user.click(await within(draft).findByRole("button", { name: "Copy message" }));
    expect(writeText).toHaveBeenCalledWith(db.drafts[0]?.body);
    expect(within(draft).getByRole("button", { name: "Copied. Paste it into your chat app." })).toBeInTheDocument();
    expect(db.drafts[0]?.status).toBe("approved");
  });

  it("sends an approved email draft and shows it as sent", async () => {
    const { user, db } = renderApp("/messages");
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    await user.click(within(draft).getByRole("button", { name: "Approve message" }));
    await user.click(await within(draft).findByRole("button", { name: "Send" }));
    expect(await within(draft).findByText("Sent", { selector: "p" })).toBeInTheDocument();
    expect(db.drafts[1]?.status).toBe("sent");
  });

  it("does not let staff approve drafts", async () => {
    renderApp("/messages", { signedInAs: "staff@hishab.demo" });
    const draft = await screen.findByRole("article", { name: "Overdue reminder · Customer 9" });
    expect(within(draft).getByText("Your role can't approve this.")).toBeInTheDocument();
    expect(within(draft).queryByRole("button")).not.toBeInTheDocument();
  });
});
