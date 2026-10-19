import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FinancingNeed } from "../../api/contracts";
import { financingMatch } from "../../mocks/fixtures/financing";
import { renderApp } from "../../test/render";
import { parseAmount } from "./amount";

async function findOptions(path = "/financing") {
  const view = renderApp(path);
  await view.user.click(await screen.findByRole("button", { name: "Find options" }));
  const region = await screen.findByRole("region", { name: "Your options, best first" });
  return { ...view, region };
}

function option(region: HTMLElement, name: string) {
  return within(region).getByRole("article", { name });
}

describe("Financing screen", () => {
  it("sends the need as exact decimals and ranks every option, loans and non-loans", async () => {
    const { region, fetchMock } = await findOptions();
    const call = fetchMock.mock.calls.find(([path]) => String(path) === "/api/financing/match");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      tenant_id: "sme_grocery",
      amount: { amount: "200000.00", currency: "BDT" },
      needed_by: "2026-10-25",
      tenor_days: 180,
      purpose_key: "purpose.working_capital",
    });
    const application = within(region).getByRole("article", { name: "Draft a loan application" });
    const names = within(region)
      .getAllByRole("article")
      .filter((article) => article !== application)
      .map((article) => within(article).getByRole("heading").textContent);
    expect(names[0]).toBe("Ask for 14 more days on the 31 Oct bill");
    expect(names[1]).toBe("CMSME working capital refinance fund (Tk 5,000 crore)");
    expect(names).toHaveLength(6);
  });

  it("shows the true yearly cost, total cost, speed and fit of each option", async () => {
    const { region } = await findOptions();
    const refinance = option(region, "CMSME working capital refinance fund (Tk 5,000 crore)");
    expect(refinance).toHaveTextContent("True yearly cost10.52%");
    expect(refinance).toHaveTextContent("Total cost৳6,250");
    expect(refinance).toHaveTextContent("Money in24 days");
    expect(refinance).toHaveTextContent("6% chance of dipping below the buffer");
    expect(refinance).toHaveTextContent("Advertised 9% a year · regulatory cap");
  });

  it("explains eligibility: a failed rule and a fact that is not on record", async () => {
    const { region } = await findOptions();
    const bkash = option(region, "bKash digital loan");
    expect(within(bkash).getByText("Not eligible")).toBeInTheDocument();
    expect(bkash).toHaveTextContent("Amount within the product's limit — no");
    const prime = option(region, "Prime Chalti (SME working capital)");
    expect(within(prime).getByText("Not on record")).toBeInTheDocument();
    expect(prime).toHaveTextContent("Collateral available — not on record, so not counted");
  });

  it("links each published rate to its source and shows the lender's track record", async () => {
    const withSource = (need: FinancingNeed) => {
      const match = financingMatch(need);
      match.options = match.options.map((o) =>
        o.product.id === "bd-bankasia-micro-wc"
          ? { ...o, product: { ...o.product, source_url: "https://www.bankasia-bd.com/downloads/Lending_Rate_Economy-sec-24-Aug-2026.pdf" } }
          : o,
      );
      return { body: match };
    };
    const view = renderApp("/financing", { overrides: { "POST /api/financing/match": (req) => withSource(req.body as FinancingNeed) } });
    await view.user.click(await screen.findByRole("button", { name: "Find options" }));
    const region = await screen.findByRole("region", { name: "Your options, best first" });
    const { user } = view;
    const bankAsia = option(region, "Cottage/micro working capital (rate sheet)");
    expect(within(bankAsia).getByRole("link", { name: "Source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(bankAsia).toHaveTextContent("checked 18 October 2026");
    await user.click(within(bankAsia).getByText("Lender check"));
    expect(bankAsia).toHaveTextContent("LicenceLicensed · Bangladesh Bank");
    expect(bankAsia).toHaveTextContent("Realised minus quoted cost0.3 percentage points");
    expect(bankAsia).toHaveTextContent("14 past loans in the mesh · Synthetic demo data");
  });

  it("offers the pre-filled application as an EXECUTE card needing the owner's code", async () => {
    const { region, user, db } = await findOptions();
    const application = within(region).getByRole("article", { name: "Draft a loan application" });
    await user.click(within(application).getByRole("button", { name: "Approve with code" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(application).findByText("Approved and carried out. It is recorded in the audit log.")).toBeInTheDocument();
    // The accountant's earlier request is the one approved: no duplicate request is created.
    expect(db.approvals.filter((r) => r.card.id === "act-apply-bb-refinance")).toHaveLength(1);
    expect(db.approvals[0]?.approval).toMatchObject({ status: "executed", step_up_verified: true });
  });

  it("refuses an amount that is not taka, without calling the server", async () => {
    const { user, fetchMock } = renderApp("/financing");
    const amount = await screen.findByLabelText("Amount (৳)");
    await user.clear(amount);
    await user.type(amount, "two lakh");
    await user.click(screen.getByRole("button", { name: "Find options" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an amount in taka, for example 200000.");
    expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/financing/match")).toBe(false);
  });
});

describe("parseAmount", () => {
  it.each([
    ["200000", "200000.00"],
    ["2,00,000", "200000.00"],
    ["২,০০,০০০", "200000.00"],
    ["৳ 1500.5", "1500.50"],
    ["0", null],
    ["12.345", null],
    ["-500", null],
  ])("%s -> %s", (raw, expected) => {
    expect(parseAmount(raw)).toBe(expected);
  });
});
