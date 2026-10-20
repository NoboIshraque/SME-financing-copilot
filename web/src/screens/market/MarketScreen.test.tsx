import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PricePoint } from "../../api/contracts";
import type { MarketAlert, WatchItem } from "../../api/types";
import { sessionFor } from "../../mocks/db";
import { renderApp } from "../../test/render";

const TCB_URL = "https://objectstorage.example/office-tcb/2026-10-19.xlsx";

function tcbPoint(amount: string, observed: string): PricePoint {
  return { commodity: "chickpea", unit: "kg", price: { amount, currency: "BDT" }, low: null, high: null, market: "Dhaka", source: "tcb", source_url: TCB_URL, observed_on: observed, data_mode: "public" };
}

/** What the WP-09 server answers: TCB's published list, with its date. */
const LIVE_PRICES: WatchItem[] = [
  { commodity: "chickpea", unit: "kg", latest: tcbPoint("117.50", "2026-10-19"), median_4w: { amount: "105.00", currency: "BDT" }, change_pct: "11.9", history: [tcbPoint("105.00", "2026-10-12"), tcbPoint("117.50", "2026-10-19")], published_on: "2026-10-19", baseline_basis: "median_4w", baseline_points: 16 },
];
const LIVE_ALERTS: MarketAlert[] = [
  { id: "mk-chickpea", commodity: "chickpea", direction: "rise", observed_on: "2026-10-19", source: "tcb", source_url: TCB_URL, published_on: "2026-10-19", change: { id: "f", label_key: "market.change_vs_median", value: "11.9", unit: "percent", data_mode: "public", provenance: { formula_id: "market.change_vs_4w_median", formula_version: 1 } } },
];
const LIVE = { "GET /api/market/prices": { body: LIVE_PRICES }, "GET /api/market/alerts": { body: LIVE_ALERTS } };
const SAMPLE_LABEL = "Sample data: a preview of a planned feature, not live prices";

describe("Market screen", () => {
  it("shows watched prices with the 4-week median, change, and when the source published them", async () => {
    renderApp("/market");
    const watch = await screen.findByRole("region", { name: "Prices you watch" });
    const onion = await within(watch).findByRole("row", { name: /Onion/ });
    expect(onion).toHaveTextContent("TCB Dhaka, published 30 Sept");
    expect(onion).toHaveTextContent("৳70 / kg৳6212.9%");
    expect(within(watch).getByRole("row", { name: /Lentils/ })).toHaveTextContent("-4.5%");
  });

  it("labels every card as sample data when the server has no market prices", async () => {
    renderApp("/market");
    expect(await screen.findByText(/The server has no market prices yet/)).toBeInTheDocument();
    for (const name of ["Prices you watch", "Price alerts", "Best vendor for an order", "Negotiate a sale"]) {
      expect(within(await screen.findByRole("region", { name })).getByText(SAMPLE_LABEL)).toBeInTheDocument();
    }
  });

  it("shows TCB's published list with its date and link, and no sample label on the price cards", async () => {
    renderApp("/market", { overrides: LIVE });
    const note = await screen.findByText(/TCB's daily retail price list for Dhaka, published 19 October 2026/);
    expect(note).toHaveTextContent("these are not live prices");
    expect(screen.getByRole("link", { name: "Open TCB's list" })).toHaveAttribute("href", TCB_URL);
    const watch = screen.getByRole("region", { name: "Prices you watch" });
    expect(within(watch).getByRole("row", { name: /Chickpeas/ })).toHaveTextContent("TCB Dhaka, published 19 Oct");
    expect(within(watch).queryByText(SAMPLE_LABEL)).not.toBeInTheDocument();
    const alerts = screen.getByRole("region", { name: "Price alerts" });
    expect(await within(alerts).findByText(/Chickpeas is up/)).toBeInTheDocument();
    expect(within(alerts).queryByText(SAMPLE_LABEL)).not.toBeInTheDocument();
    // Vendors and negotiation still come from the sample until their routes exist.
    expect(within(screen.getByRole("region", { name: "Best vendor for an order" })).getByText(SAMPLE_LABEL)).toBeInTheDocument();
  });

  it("never shows sample vendors to a self-service shop as its own", async () => {
    const { user } = renderApp("/market", {
      overrides: { "GET /api/auth/me": (_req, state) => ({ body: { ...sessionFor(state.users[0]!), data_mode: "live" } }) },
    });
    const vendors = await screen.findByRole("region", { name: "Best vendor for an order" });
    await user.click(within(vendors).getByRole("button", { name: "Rank vendors" }));
    expect(await within(vendors).findByText(/Add a supplier quote to compare vendors/)).toBeInTheDocument();
    expect(within(vendors).queryByText(/Supplier 7/)).not.toBeInTheDocument();
  });

  it("raises an alert for each big move, with advice", async () => {
    renderApp("/market");
    const alerts = await screen.findByRole("region", { name: "Price alerts" });
    const items = await within(alerts).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Onion (local) is up 12.9%");
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
