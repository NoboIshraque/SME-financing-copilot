import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

async function openNumber(name: RegExp) {
  return screen.findByRole("button", { name });
}

describe("provenance drawer (N13)", () => {
  it("explains the cash balance: formula, inputs with values, and source rows", async () => {
    const { user } = renderApp("/");
    await user.click(await openNumber(/^Cash now: ৳4,27,842\. Show how this was calculated$/));
    const drawer = screen.getByRole("dialog", { name: "Cash now" });
    expect(await within(drawer).findByText("opening_balance + cash_in - cash_out")).toBeInTheDocument();
    expect(within(drawer).getByText("cash.closing_balance, version 1")).toBeInTheDocument();
    expect(within(drawer).getByRole("row", { name: /Cash at start/ })).toHaveTextContent("৳3,48,635");
    expect(within(drawer).getByRole("row", { name: /Money in/ })).toHaveTextContent("৳16,08,740");
    expect(within(drawer).getByRole("row", { name: /Money out/ })).toHaveTextContent("৳15,29,533");
    expect(within(drawer).getByText("bank_statement.csv#L820")).toBeInTheDocument();
    expect(drawer).toHaveTextContent("No AI model produced this number.");
  });

  it.each([
    ["an engine figure", "/receivables", /^Days to get paid \(DSO\): 11\.2 days\./, "receivables / net_sales * days_in_period"],
    ["an invoice amount", "/receivables", /^Customer 10 · INV-00786: ৳3,601\./, "baki_register.csv#INV-00786"],
    ["a forecast table cell", "/cash", /^Likely \(P50\) · 4 Nov: ৳87,333\./, "20261020"],
    ["a gap driver", "/", /^Salaries: ৳60,000\./, "sme_grocery:OBL-2"],
  ])("opens for %s", async (_kind, path, name, evidence) => {
    const { user } = renderApp(path);
    await user.click(await openNumber(name));
    const drawer = screen.getByRole("dialog");
    expect(await within(drawer).findByText(evidence)).toBeInTheDocument();
  });

  it("falls back to the provenance recorded on the figure when the ledger cannot explain it", async () => {
    const { user } = renderApp("/", {
      overrides: { "GET /api/explain/:id": { status: 404, body: { code: "figure_not_found", message_key: "error.figure_not_found" } } },
    });
    await user.click(await openNumber(/^Runway: 31 days\./));
    const drawer = screen.getByRole("dialog", { name: "Runway" });
    expect(await within(drawer).findByText(/The detailed breakdown is not available yet/)).toBeInTheDocument();
    expect(within(drawer).getByText("cash.runway_days, version 1")).toBeInTheDocument();
    expect(within(drawer).getByText("seed").nextSibling).toHaveTextContent("20261020");
  });

  it("says when source rows are hidden for the viewer's role", async () => {
    const { user } = renderApp("/", {
      overrides: {
        "GET /api/explain/:id": {
          body: { figure_id: "fig-cash-balance", formula: { formula_id: "cash.closing_balance", version: 1, expression: "opening_balance + cash_in - cash_out" }, value: "427842.00", unit: "BDT", inputs: [], source_rows: [], masked: true },
        },
      },
    });
    await user.click(await openNumber(/^Cash now: ৳4,27,842\./));
    expect(await screen.findByText("Some source rows are hidden for your role.")).toBeInTheDocument();
  });

  it("closes with Escape and returns focus to the number", async () => {
    const { user } = renderApp("/");
    const number = await openNumber(/^Cash now: ৳4,27,842\./);
    await user.click(number);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(number).toHaveFocus();
  });
});
