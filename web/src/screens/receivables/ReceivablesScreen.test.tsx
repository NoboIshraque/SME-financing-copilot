import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

describe("Receivables screen", () => {
  it("summarises what is owed and how old it is", async () => {
    renderApp("/receivables");
    expect(await screen.findByText("৳21,859")).toBeInTheDocument();
    expect(screen.getByText("৳15,542")).toBeInTheDocument();
    expect(screen.getByText("11.2 days")).toBeInTheDocument();
    const aging = screen.getByRole("region", { name: "How old the money owed is" });
    const buckets = within(aging).getAllByRole("listitem");
    expect(buckets[0]).toHaveTextContent("0–30 days৳18,258 (11 invoices)");
    expect(buckets[1]).toHaveTextContent("31–60 days৳3,601 (1 invoice)");
    expect(buckets[3]).toHaveTextContent("Over 90 days৳0 (0 invoices)");
  });

  it("lists open invoices riskiest first, with their top risk factors", async () => {
    renderApp("/receivables");
    const list = await screen.findByRole("region", { name: "Open invoices, riskiest first" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveAccessibleName("Customer 10 INV-00786");
    expect(rows[0]).toHaveTextContent("High risk · 78/100");
    expect(rows[0]).toHaveTextContent("19 days late");
    expect(within(rows[0] as HTMLElement).getByText("Usually pays slowly")).toBeInTheDocument();
    expect(rows[rows.length - 1]).toHaveTextContent("Low risk · 18/100");
  });

  it("records a dispute, takes the invoice out of the likely forecast, and resolves it", async () => {
    const { user, db, fetchMock } = renderApp("/receivables");
    const row = await screen.findByRole("listitem", { name: "Customer 9 INV-00813" });
    await user.click(within(row).getByRole("button", { name: "Record a dispute" }));
    const dialog = screen.getByRole("dialog", { name: "Record a dispute" });
    await user.click(within(dialog).getByLabelText("Wrong quantity"));
    await user.click(within(dialog).getByRole("button", { name: "Record a dispute" }));

    const disputed = await screen.findByRole("listitem", { name: "Customer 9 INV-00813" });
    expect(await within(disputed).findByText("Disputed: Wrong quantity")).toBeInTheDocument();
    expect(within(disputed).getByText("Left out of the likely forecast until it is resolved.")).toBeInTheDocument();
    expect(db.disputes).toEqual({ "sme_grocery:GRO-INV-00813": "quantity" });
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/dispute"));
    expect(String(call?.[0])).toBe("/api/receivables/sme_grocery%3AGRO-INV-00813/dispute");

    await user.click(within(disputed).getByRole("button", { name: "Mark resolved" }));
    const resolved = screen.getByRole("listitem", { name: "Customer 9 INV-00813" });
    expect(await within(resolved).findByRole("button", { name: "Record a dispute" })).toBeInTheDocument();
    expect(db.disputes).toEqual({});
  });

  it("offers the reminder ladder as one-tap drafts", async () => {
    const { user, db } = renderApp("/receivables");
    const reminders = await screen.findByRole("region", { name: "Reminders to send" });
    const cards = await within(reminders).findAllByRole("article");
    expect(cards).toHaveLength(3);
    expect(cards[2]).toHaveTextContent("Send a friendly reminder before the due date");
    await user.click(within(cards[1] as HTMLElement).getByRole("button", { name: "Approve draft" }));
    expect(await within(cards[1] as HTMLElement).findByText("Approved. It is recorded in the audit log.")).toBeInTheDocument();
    expect(db.approvals[0]?.action_card_id).toBe("act-remind-customer-10");
  });

  it("flags chronic late payers with a stop-credit suggestion and shows each limit", async () => {
    renderApp("/receivables");
    const credit = await screen.findByRole("region", { name: "Customers and credit limits" });
    const customer9 = within(credit).getByText("Customer 9").closest("li") as HTMLElement;
    expect(customer9).toHaveTextContent("Stop credit");
    expect(customer9).toHaveTextContent("Credit limit: ৳8,000");
    const customer1 = within(credit).getByText("Customer 1").closest("li") as HTMLElement;
    expect(customer1).not.toHaveTextContent("Stop credit");
  });

  it("lets staff see reminders but not approve them", async () => {
    renderApp("/receivables", { signedInAs: "staff@hishab.demo" });
    const reminders = await screen.findByRole("region", { name: "Reminders to send" });
    const cards = await within(reminders).findAllByRole("article");
    expect(within(cards[0] as HTMLElement).getByText("Your role can't approve this.")).toBeInTheDocument();
    expect(within(reminders).queryByRole("button")).not.toBeInTheDocument();
  });

  it("has an empty state when nobody owes money", async () => {
    renderApp("/receivables", {
      overrides: {
        "GET /api/receivables": {
          body: { as_of: "2026-09-30", figures: [], aging: [], invoices: [], customers: [] },
        },
        "GET /api/receivables/plan": { body: { reminders: [] } },
      },
    });
    expect(await screen.findByText("Nobody owes you money right now.")).toBeInTheDocument();
    expect(screen.getByText("No reminders due.")).toBeInTheDocument();
  });
});
