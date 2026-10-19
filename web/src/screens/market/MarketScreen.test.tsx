import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

describe("Market screen", () => {
  it("shows watched prices with the 4-week median, change, and when the source published them", async () => {
    renderApp("/market");
    const watch = await screen.findByRole("region", { name: "Prices you watch" });
    const onion = await within(watch).findByRole("row", { name: /Onion/ });
    expect(onion).toHaveTextContent("TCB Dhaka, published 30 Sept");
    expect(onion).toHaveTextContent("৳70 / kg৳6212.9%");
    expect(within(watch).getByRole("row", { name: /Lentils/ })).toHaveTextContent("-4.5%");
  });

  it("raises an alert for each big move, with advice", async () => {
    renderApp("/market");
    const alerts = await screen.findByRole("region", { name: "Price alerts" });
    const items = await within(alerts).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Onion is up 12.9%");
    expect(items[0]).toHaveTextContent("Buy only what you need this week");
    expect(items[1]).toHaveTextContent("Lentils (masur) is down -4.5%");
    expect(items[1]).toHaveTextContent("A good time to stock up");
  });

  it("ranks vendors by landed cost and shows what makes up each cost", async () => {
    const { user, fetchMock } = renderApp("/market");
    const vendors = await screen.findByRole("region", { name: "Best vendor for an order" });
    await user.click(within(vendors).getByRole("button", { name: "Rank vendors" }));
    const first = await within(vendors).findByRole("listitem", { name: "Supplier 7 (pickup)" });
    expect(first).toHaveTextContent("1. Supplier 7 (pickup)৳57 / kg");
    const second = within(vendors).getByRole("listitem", { name: "Supplier 2" });
    expect(second).toHaveTextContent("Price৳56Delivery৳0.80Waiting cost৳0.30Reliability risk৳0.60");
    expect(second).toHaveTextContent("arrives in 2 days · on time 90%");
    const call = fetchMock.mock.calls.find(([path]) => String(path) === "/api/market/vendors/rank");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ commodity: "rice_coarse", quantity: "500" });
  });

  it("builds a negotiation plan: walk-away, target, and numbered steps with their numbers", async () => {
    const { user, fetchMock } = renderApp("/market");
    const negotiate = await screen.findByRole("region", { name: "Negotiate a sale" });
    await user.click(within(negotiate).getByRole("button", { name: "Make my plan" }));
    expect(await within(negotiate).findByText("Walk away below")).toBeInTheDocument();
    expect(negotiate).toHaveTextContent("Walk away below৳59.40Aim for৳63");
    const steps = within(negotiate).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[2]).toHaveTextContent("Offer a small discount for fast payment: it costs less than borrowing.");
    expect(steps[2]).toHaveTextContent("Discount: 2%Its cost per month: 0.7%Your loan's cost per month: 0.88%");
    expect(within(negotiate).queryByRole("alert")).not.toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([path]) => String(path) === "/api/market/negotiate");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({
      commodity: "rice_coarse",
      quantity: "500",
      offer_price: { amount: "62.00", currency: "BDT" },
      payment_days: 30,
    });
  });

  it("warns when a plan's target falls below the walk-away point", async () => {
    const plan = {
      walk_away: { id: "w", label_key: "negotiation.walk_away", value: "59.40", unit: "BDT", data_mode: "synthetic", provenance: { formula_id: "x", formula_version: 1 } },
      target: { id: "t", label_key: "negotiation.target", value: "58.00", unit: "BDT", data_mode: "synthetic", provenance: { formula_id: "x", formula_version: 1 } },
      steps: [],
    };
    const { user } = renderApp("/market", { overrides: { "POST /api/market/negotiate": { body: plan } } });
    const negotiate = await screen.findByRole("region", { name: "Negotiate a sale" });
    await user.click(within(negotiate).getByRole("button", { name: "Make my plan" }));
    expect(await within(negotiate).findByRole("alert")).toHaveTextContent("The target is below your walk-away point.");
  });

  it("explains an empty watchlist", async () => {
    renderApp("/market", { overrides: { "GET /api/market/prices": { body: [] }, "GET /api/market/alerts": { body: [] } } });
    expect(await screen.findByText("No inputs watched yet. They appear once purchases are on record.")).toBeInTheDocument();
    expect(screen.getByText("No big price moves today.")).toBeInTheDocument();
  });
});
