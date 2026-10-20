import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StabilityReport } from "../../api/contracts";
import { stability } from "../../mocks/fixtures/analysis";
import { renderApp, requestedPaths } from "../../test/render";

describe("Analysis screen", () => {
  it("switches between the profit and loss, balance sheet and cash flow", async () => {
    const { user } = renderApp("/analysis");
    const statements = await screen.findByRole("region", { name: "Statements" });
    expect(await within(statements).findByRole("rowheader", { name: "Net profit" })).toBeInTheDocument();
    expect(within(statements).getByRole("row", { name: /Net profit/ })).toHaveTextContent("৳1,31,550");

    await user.click(within(statements).getByRole("button", { name: "Balance sheet (lite)" }));
    expect(within(statements).getByRole("button", { name: "Balance sheet (lite)" })).toHaveAttribute("aria-pressed", "true");
    expect(within(statements).getByRole("row", { name: /Net position/ })).toHaveTextContent("৳2,84,465");
    expect(within(statements).queryByRole("rowheader", { name: "Net profit" })).not.toBeInTheDocument();
  });

  it("shows ratios with benchmarks and says when one does not apply", async () => {
    renderApp("/analysis");
    const ratios = await screen.findByRole("region", { name: "Key ratios" });
    expect(await within(ratios).findByRole("listitem", { name: "Gross margin" })).toHaveTextContent("15.1%Typical: 12-18In the usual range for a grocery.");
    expect(within(ratios).getByRole("listitem", { name: "Current ratio" })).toHaveTextContent("2.73");
    expect(within(ratios).getByRole("listitem", { name: "Debt service cover" })).toHaveTextContent("Not applicable");
  });

  it("compares expected with actual, biggest gap first, with the forecast's accuracy", async () => {
    renderApp("/analysis");
    const variance = await screen.findByRole("region", { name: "Expected vs reality" });
    expect(await within(variance).findByText("94.2%")).toBeInTheDocument();
    const rows = within(variance).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getByRole("rowheader").textContent)).toEqual(["Net sales", "Collections", "Purchases", "Cash at month end"]);
    expect(rows[0]).toHaveTextContent("৳16,20,000৳15,80,750 below expected");
    expect(rows[2]).toHaveTextContent("above expected");
  });

  it("simulates the chosen decisions and marks the best risk-adjusted one", async () => {
    const { user, fetchMock } = renderApp("/analysis");
    const scenarios = await screen.findByRole("region", { name: "Compare decisions" });
    await user.click(within(scenarios).getByLabelText("Offer an early-payment discount"));
    await user.click(within(scenarios).getByRole("button", { name: "Compare" }));

    const best = await within(scenarios).findByRole("row", { name: /Recommended/ });
    expect(best).toHaveTextContent("Pay the supplier after salary day");
    expect(best).toHaveTextContent("৳3,18,000৳1,12,0007%");
    const call = fetchMock.mock.calls.find(([path]) => String(path) === "/api/analysis/scenarios");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ decisions: ["retime_supplier", "take_loan", "do_nothing"] });
  });

  it("needs at least two decisions to compare", async () => {
    const { user } = renderApp("/analysis");
    const scenarios = await screen.findByRole("region", { name: "Compare decisions" });
    for (const label of ["Take the refinance loan", "Offer an early-payment discount", "Do nothing"]) {
      await user.click(within(scenarios).getByLabelText(label));
    }
    expect(within(scenarios).getByRole("button", { name: "Compare" })).toBeDisabled();
  });

  it("asks for the stability of the recommended choice only once decisions are compared", async () => {
    const { user, fetchMock } = renderApp("/analysis");
    const region = await screen.findByRole("region", { name: "How stable is the recommended choice?" });
    expect(within(region).getByText(/Compare decisions above/)).toBeInTheDocument();
    expect(requestedPaths(fetchMock)).not.toContain("/api/analysis/stability");

    const scenarios = screen.getByRole("region", { name: "Compare decisions" });
    await user.click(within(scenarios).getByRole("button", { name: "Compare" }));
    const meter = await within(region).findByRole("meter", { name: "Decision stability" });
    expect(meter).toHaveAttribute("aria-valuenow", "80");
    expect(within(region).getByText("Holds in 8 of 10 variations")).toBeInTheDocument();
    const [wouldFlip] = within(region).getAllByRole("list");
    expect(within(wouldFlip as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Sales 20% lower",
      "A surprise bill",
    ]);
    expect(within(region).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("flags advice that changed on irrelevant noise as unreliable", async () => {
    const report: StabilityReport = {
      ...stability(),
      results: stability().results.map((r) => (r.name === "rows_shuffled" ? { ...r, held: false, choice: "take_loan" } : r)) as StabilityReport["results"],
    };
    const { user } = renderApp("/analysis", { overrides: { "POST /api/analysis/stability": { body: report } } });
    const scenarios = await screen.findByRole("region", { name: "Compare decisions" });
    await user.click(within(scenarios).getByRole("button", { name: "Compare" }));
    const region = screen.getByRole("region", { name: "How stable is the recommended choice?" });
    expect(await within(region).findByRole("alert")).toHaveTextContent(
      "Unreliable: the advice changed on irrelevant noise (Rows in a different order).",
    );
  });
});
