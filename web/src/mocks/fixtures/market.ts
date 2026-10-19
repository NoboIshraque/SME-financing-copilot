// Mock WP-09 output: TCB-style Dhaka retail prices for the grocery's inputs (public data shape,
// illustrative values), vendor quotes from its own ledger (synthetic), and a negotiation plan.
import type { PricePoint, VendorQuote } from "../../api/contracts";
import type { MarketAlert, NegotiationPlan, NegotiationRequest, VendorRank, WatchItem } from "../../api/types";
import { AS_OF, figure, money } from "./common";

function price(commodity: string, unit: string, mid: number, low: number, high: number, observed = AS_OF): PricePoint {
  return { commodity, unit, price: money(mid), low: money(low), high: money(high), market: "Dhaka", source: "tcb", observed_on: observed, source_url: null, data_mode: "public" };
}

const WATCH: Array<[string, string, number, number, number, number, string]> = [
  ["onion", "kg", 70, 65, 75, 62, "12.9"],
  ["lentil_masur", "kg", 105, 100, 110, 110, "-4.5"],
  ["rice_coarse", "kg", 58, 55, 60, 60, "-3.3"],
  ["soybean_oil", "litre", 178, 175, 180, 172, "3.5"],
  ["sugar", "kg", 125, 120, 130, 125, "0"],
];

export function watchlist(): WatchItem[] {
  return WATCH.map(([commodity, unit, mid, low, high, median, change]) => ({
    commodity,
    unit,
    latest: price(commodity, unit, mid, low, high),
    median_4w: money(median),
    change_pct: change,
    history: [21, 14, 7].map((days) => price(commodity, unit, median, median - 3, median + 3, `2026-09-${String(30 - days).padStart(2, "0")}`)),
  }));
}

export function marketAlerts(): MarketAlert[] {
  return [
    { id: "mk-onion-up", commodity: "onion", direction: "rise", observed_on: AS_OF, source: "tcb", change: figure("fig-mk-onion", "market.change_vs_median", "12.9", "percent", { formula_id: "market.change_vs_4w_median", parameters: { threshold_pct: "8" } }) },
    { id: "mk-lentil-down", commodity: "lentil_masur", direction: "drop", observed_on: AS_OF, source: "tcb", change: figure("fig-mk-lentil", "market.change_vs_median", "-4.5", "percent", { formula_id: "market.change_vs_4w_median", parameters: { threshold_pct: "4" } }) },
  ];
}

function quote(vendor: string, unitPrice: string, delivery: number, lead: number, onTime: string | null): VendorQuote {
  return { vendor_token: vendor, commodity: "rice_coarse", unit: "kg", unit_price: money(unitPrice), delivery_cost: money(delivery), lead_time_days: lead, on_time_rate: onTime, quoted_on: "2026-09-28", data_mode: "synthetic" };
}

function landed(id: string, total: string, parts: Array<[string, string]>): [VendorRank["landed_cost"], VendorRank["breakdown"]] {
  const params = { quantity_kg: "500" };
  return [
    figure(`fig-landed-${id}`, "market.landed_cost", total, "BDT", { formula_id: "market.landed_cost_per_unit", parameters: params }),
    parts.map(([label, value]) => figure(`fig-${label}-${id}`, `market.${label}`, value, "BDT", { formula_id: `market.${label}`, parameters: params })),
  ];
}

export function vendorRanking(commodity: string): VendorRank[] {
  if (commodity !== "rice_coarse") return [];
  const ranks: Array<[number, string, VendorQuote, string, Array<[string, string]>]> = [
    [1, "Supplier 7 (pickup)", quote("PARTY_7a1c0e5b2d", "57.00", 0, 0, "1.0"), "57.00", [["unit_price", "57.00"], ["delivery_per_unit", "0.00"], ["delay_cost", "0.00"], ["reliability_penalty", "0.00"]]],
    [2, "Supplier 2", quote("PARTY_efd9a5e9e9", "56.00", 400, 2, "0.9"), "57.70", [["unit_price", "56.00"], ["delivery_per_unit", "0.80"], ["delay_cost", "0.30"], ["reliability_penalty", "0.60"]]],
    [3, "Supplier 5", quote("PARTY_905192e72a", "55.50", 900, 3, "0.75"), "59.20", [["unit_price", "55.50"], ["delivery_per_unit", "1.80"], ["delay_cost", "0.50"], ["reliability_penalty", "1.40"]]],
  ];
  return ranks.map(([rank, label, q, total, parts]) => {
    const [landedCost, breakdown] = landed(String(rank), total, parts);
    return { rank, vendor_label: label, quote: q, landed_cost: landedCost, breakdown };
  });
}

export function negotiationPlan(request: NegotiationRequest): NegotiationPlan {
  const params = { quantity: request.quantity, offer: request.offer_price.amount, payment_days: String(request.payment_days), best_apr: "10.52" };
  const f = (id: string, label: string, value: string, unit: "BDT" | "percent" = "BDT") => figure(`fig-neg-${id}`, `negotiation.${label}`, value, unit, { formula_id: `negotiation.${label}`, parameters: params });
  return {
    walk_away: f("walk", "walk_away", "59.40"),
    target: f("target", "target", "63.00"),
    steps: [
      { text_key: "negotiation.step.open_high", figures: [f("open", "price", "64.00")] },
      { text_key: "negotiation.step.trade_term", figures: [f("term-price", "price", "63.00"), f("credit", "credit_cost", "0.52")] },
      { text_key: "negotiation.step.discount_for_speed", figures: [f("disc", "discount", "2", "percent"), f("disc-cost", "monthly_cost", "0.7", "percent"), f("loan-cost", "loan_monthly_cost", "0.88", "percent")] },
      { text_key: "negotiation.step.walk_away", figures: [f("walk-step", "walk_away", "59.40")] },
    ],
  };
}
