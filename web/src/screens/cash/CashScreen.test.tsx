import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatCompactTaka } from "../../api/format";
import { cashGaps } from "../../mocks/fixtures/cash";
import { renderApp, requestedPaths } from "../../test/render";

describe("Cash screen", () => {
  it("shows the 13-week band as a week-by-week table with P10, P50, P90 and risk", async () => {
    renderApp("/cash");
    const table = await screen.findByRole("table", { name: "Week-by-week forecast balance" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(14);
    // Week 5 ends 4 Nov (day 35), between the 31 Oct salary dip and the 5 Nov low.
    expect(within(rows[5] as HTMLElement).getByRole("rowheader")).toHaveTextContent("Week 5 (4 Nov)");
    expect(rows[5]).toHaveTextContent("৳29,833৳87,333৳1,37,833");
    expect(screen.getByText("Simulated over 1,000 paths (seed 20261020).")).toBeInTheDocument();
  });

  it("lists the gaps ahead with their date, chance and expected shortfall", async () => {
    renderApp("/cash");
    const gaps = await screen.findByRole("region", { name: "Gaps ahead" });
    const item = await within(gaps).findByRole("listitem");
    expect(item).toHaveTextContent("31 October 2026, in 31 days");
    expect(item).toHaveTextContent("Chance of dipping below the buffer: 54%");
    expect(item).toHaveTextContent("Expected shortfall: ৳48,500");
  });

  it("says so calmly when there is no gap", async () => {
    renderApp("/cash", { overrides: { "GET /api/cash/gaps": { body: { ...cashGaps(), gaps: [] } } } });
    expect(await screen.findByText("No gaps in the next 13 weeks.")).toBeInTheDocument();
  });

  it("re-runs the engine when a what-if slider moves, and resets", async () => {
    const { user, fetchMock } = renderApp("/cash");
    const panel = await screen.findByRole("region", { name: "What if…" });
    fireEvent.change(within(panel).getByLabelText(/Sales change/), { target: { value: "-30" } });

    expect(await within(panel).findByText("Runway in this case")).toBeInTheDocument();
    expect(within(panel).getByRole("slider", { name: /Sales change/ })).toHaveAttribute("aria-valuetext", "-30%");
    const call = fetchMock.mock.calls.find(([path]) => String(path) === "/api/cash/whatif");
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toMatchObject({ sales_change_pct: "-30", collection_delay_days: 0 });
    // A 30% sales drop pulls the runway in from 31 to 27 days and takes the low below zero.
    expect(await within(panel).findByText("27 days")).toBeInTheDocument();
    expect(within(panel).getByText("-৳28,200")).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Reset" }));
    expect(within(panel).queryByText("Runway in this case")).not.toBeInTheDocument();
    expect(requestedPaths(fetchMock).filter((p) => p === "/api/cash/whatif")).toHaveLength(1);
  });

  it("sends one what-if request for a burst of slider moves, with the value it rests on", async () => {
    const { fetchMock } = renderApp("/cash");
    const panel = await screen.findByRole("region", { name: "What if…" });
    const slider = within(panel).getByLabelText(/Sales change/);
    for (const value of ["-5", "-10", "-15", "-20", "-25", "-30"]) fireEvent.change(slider, { target: { value } });

    expect(within(panel).getByRole("status")).toHaveTextContent("Updating…");
    expect(await within(panel).findByText("27 days")).toBeInTheDocument();
    const calls = fetchMock.mock.calls.filter(([path]) => String(path) === "/api/cash/whatif");
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String((calls[0]?.[1] as RequestInit).body))).toMatchObject({ sales_change_pct: "-30" });
  });

  it("asks at once when the slider is released", async () => {
    const { fetchMock } = renderApp("/cash");
    const panel = await screen.findByRole("region", { name: "What if…" });
    const slider = within(panel).getByLabelText(/Sales change/);
    fireEvent.change(slider, { target: { value: "-30" } });
    fireEvent.pointerUp(slider);
    await waitFor(() => expect(requestedPaths(fetchMock)).toContain("/api/cash/whatif"), { timeout: 200 });
  });

  it("offers the ranked fixes as approvable action cards", async () => {
    renderApp("/cash");
    const levers = await screen.findByRole("region", { name: "Ways to close the gap" });
    const cards = await within(levers).findAllByRole("article");
    expect(cards.map((c) => within(c).getByRole("heading").textContent)).toEqual([
      "Pay a supplier later, within terms",
      "Send a payment reminder",
    ]);
    expect(within(cards[0] as HTMLElement).getByRole("button", { name: "Approve with code" })).toBeInTheDocument();
  });

  it("shows an error with retry when the forecast cannot load", async () => {
    renderApp("/cash", { overrides: { "GET /api/cash/forecast": { status: 500, body: { code: "boom", message_key: "error.server" } } } });
    const forecast = await screen.findByRole("region", { name: "Balance for the next 13 weeks" });
    expect(await within(forecast).findByRole("alert")).toHaveTextContent("The server had a problem.");
    expect(within(forecast).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("chart axis amounts", () => {
  it.each([
    ["4278420", "en", "৳42.8 L"],
    ["12500000", "en", "৳1.3 Cr"],
    ["85000", "en", "৳85K"],
    ["427842", "bn", "৳৪.৩ লাখ"],
    ["427842", "zh", "৳42.8万"],
    ["-50000", "en", "-৳50K"],
    ["950", "en", "৳950"],
  ] as const)("%s in %s -> %s", (amount, lang, expected) => {
    expect(formatCompactTaka(amount, lang)).toBe(expected);
  });
});
