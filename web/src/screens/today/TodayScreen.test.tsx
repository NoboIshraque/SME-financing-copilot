import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Alert, Recommendation } from "../../api/contracts";
import { alerts, cashForecast } from "../../mocks/fixtures/cash";
import { money, NOW } from "../../mocks/fixtures/common";
import { todayRecommendation } from "../../mocks/fixtures/copilot";
import { ACCOUNTANT, renderApp } from "../../test/render";

const criticalAlert: Alert = {
  id: "al-payroll",
  tenant_id: "sme_grocery",
  tier: "critical",
  title_key: "alert.payroll_at_risk",
  gap: {
    first_breach_day: "2026-10-05",
    lead_time_days: 5,
    probability: "0.71",
    expected_shortfall: money(30000),
    worst_day: "2026-10-05",
    drivers: [{ kind: "obligation", label_key: "driver.rent", amount: money(35000) }],
  },
  indicators: ["payroll_or_emi_at_risk"],
  fixes: [],
  dedupe_key: "gap:2026-10-05",
  created_at: NOW,
  data_mode: "synthetic",
};

function card(name: RegExp) {
  return screen.getByRole("article", { name });
}

describe("Today screen", () => {
  it("shows cash now, the runway and the buffer from the forecast's figures", async () => {
    renderApp("/");
    const cash = await screen.findByRole("region", { name: "Cash now" });
    expect(await within(cash).findByText("৳4,27,842")).toBeInTheDocument();
    expect(within(cash).getByText("31 days")).toBeInTheDocument();
    expect(within(cash).getByText("৳1,00,000")).toBeInTheDocument();
    expect(within(cash).getByText("৳85,000")).toBeInTheDocument();
    expect(screen.getByText("As of 30 September 2026")).toBeInTheDocument();
  });

  it("says the balance holds when the runway reaches the end of the forecast", async () => {
    const forecast = cashForecast();
    forecast.figures = forecast.figures.map((f) => (f.label_key === "cash.runway_days" ? { ...f, value: "91" } : f));
    renderApp("/", { overrides: { "GET /api/cash/forecast": { body: forecast } } });
    expect(
      await screen.findByText("Your likely balance stays above your safety buffer for the whole forecast."),
    ).toBeInTheDocument();
  });

  it("pins critical alerts above everything and groups the rest by tier", async () => {
    renderApp("/", { overrides: { "GET /api/cash/alerts": { body: [...alerts(), criticalAlert] } } });
    const critical = await screen.findByRole("article", { name: "Payroll at risk" });
    const cashHeading = screen.getByRole("heading", { level: 3, name: "Cash now" });
    expect(critical.compareDocumentPosition(cashHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(critical).getByRole("heading", { level: 3 })).toBeInTheDocument();

    const alertsRegion = screen.getByRole("region", { name: "Alerts" });
    expect(within(alertsRegion).getByRole("heading", { level: 4, name: "Warning (1)" })).toBeInTheDocument();
    expect(within(alertsRegion).getByRole("heading", { level: 4, name: "Watch (1)" })).toBeInTheDocument();
    expect(within(alertsRegion).queryByText("Payroll at risk")).not.toBeInTheDocument();
  });

  it("explains an alert: what, when, how much and why", async () => {
    renderApp("/");
    const alert = await screen.findByRole("article", { name: "Cash gap ahead" });
    expect(within(alert).getByText("54%")).toBeInTheDocument();
    expect(within(alert).getByText("৳48,500")).toBeInTheDocument();
    expect(within(alert).getByText(/31 Oct/)).toHaveTextContent("(in 31 days)");
    expect(within(alert).getByText("Salaries").nextSibling).toHaveTextContent("৳60,000");
    expect(within(alert).getByText("Top customer paying later")).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "See 2 ranked fixes" })).toHaveAttribute("href", "/cash");
  });

  it("lists today's top 3 actions with their permission tiers and the case against", async () => {
    renderApp("/");
    const actions = await screen.findByRole("region", { name: "Do these today" });
    const cards = await within(actions).findAllByRole("article");
    const badges = cards.map((c) => c.querySelector("[data-tier]"));
    expect(badges.map((badge) => badge?.getAttribute("data-tier"))).toEqual(["EXECUTE", "DRAFT", "READ"]);
    expect(badges.map((badge) => badge?.firstChild?.textContent)).toEqual(["Moves money", "Draft", "View"]);
    expect(cards[0]).toHaveTextContent("Moves money or makes a commitment, so the owner approves it with a code.");
    expect(within(actions).getByText(/Supplier 2 has refused new dates before/)).toBeInTheDocument();
  });

  it("approves an EXECUTE card only with the step-up code, sent with an idempotency key", async () => {
    const { user, db, fetchMock } = renderApp("/");
    const retime = await screen.findByRole("article", { name: "Pay a supplier later, within terms" });
    expect(within(retime).getByText("Supplier 2 · due 31 Oct · new date 10 Nov")).toBeInTheDocument();
    await user.click(within(retime).getByRole("button", { name: "Approve with code" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    expect(await within(retime).findByText("Approved. It is recorded in the audit log.")).toBeInTheDocument();
    expect(db.approvals).toHaveLength(1);
    expect(db.approvals[0]).toMatchObject({ action_card_id: "act-retime-supplier-2", step_up_verified: true });
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/act-retime-supplier-2/approve"));
    const headers = (call?.[1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-Step-Up-Code"]).toBe("246810");
    expect(headers["X-Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("approves a DRAFT card in one tap, without a code", async () => {
    const { user, db } = renderApp("/");
    const remind = await screen.findByRole("article", { name: "Send a payment reminder" });
    await user.click(within(remind).getByRole("button", { name: "Approve draft" }));
    expect(await within(remind).findByText("Approved. It is recorded in the audit log.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(db.approvals[0]).toMatchObject({ tier: "DRAFT", step_up_verified: false });
  });

  it("shows an accountant the EXECUTE card without a way to approve it", async () => {
    renderApp("/", { signedInAs: ACCOUNTANT });
    const retime = await screen.findByRole("article", { name: "Pay a supplier later, within terms" });
    expect(within(retime).getByText("Only the owner can approve this.")).toBeInTheDocument();
    expect(within(retime).queryByRole("button")).not.toBeInTheDocument();
    expect(within(card(/Send a payment reminder/)).getByRole("button", { name: "Approve draft" })).toBeEnabled();
  });

  it("opens the screen a READ card points to", async () => {
    const { user } = renderApp("/");
    const view = await screen.findByRole("article", { name: "Compare standby financing" });
    await user.click(within(view).getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Financing" })).toBeInTheDocument();
  });

  it("never offers a button on a DENY card", async () => {
    const recommendation: Recommendation = {
      ...todayRecommendation(),
      action_cards: [{ id: "act-export", title_key: "action.export_raw_pii", action_type: "export_raw_pii", tier: "DENY" }],
    };
    renderApp("/", { overrides: { "GET /api/copilot/today": { body: recommendation } } });
    const denied = await screen.findByRole("article", { name: "Export raw personal data" });
    expect(within(denied).getByText("Blocked: Hishab never does this.")).toBeInTheDocument();
    expect(within(denied).queryByRole("button")).not.toBeInTheDocument();
  });

  it("falls back to the alerts' ranked fixes when the copilot router has not landed", async () => {
    renderApp("/", { overrides: { "GET /api/copilot/today": { status: 404, body: { detail: "Not Found" } } } });
    const actions = await screen.findByRole("region", { name: "Do these today" });
    const titles = (await within(actions).findAllByRole("article")).map((a) => within(a).getByRole("heading").textContent);
    expect(titles).toEqual(["Pay a supplier later, within terms", "Send a payment reminder"]);
  });

  it("shows the copilot's abstention, naming what is missing, instead of guessing", async () => {
    const recommendation: Recommendation = {
      ...todayRecommendation(),
      action_cards: [],
      abstention: {
        reason: "insufficient_data",
        message_key: "abstain.insufficient_data",
        missing: ["at least 90 days of sales history"],
      },
    };
    renderApp("/", { overrides: { "GET /api/copilot/today": { body: recommendation } } });
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Not enough to advise yet");
    expect(note).toHaveTextContent("I don't have enough data to advise on this safely.");
    expect(within(note).getByRole("listitem")).toHaveTextContent("at least 90 days of sales history");
  });

  it("has a calm empty state, and an error state whose retry recovers", async () => {
    let forecastCalls = 0;
    const { user } = renderApp("/", {
      overrides: {
        "GET /api/cash/alerts": { body: [] },
        "GET /api/cash/forecast": () =>
          (forecastCalls += 1) === 1
            ? { status: 503, body: { code: "unavailable", message_key: "error.server" } }
            : { body: cashForecast() },
      },
    });
    expect(await screen.findByText("No alerts. Your cash looks steady for the next 13 weeks.")).toBeInTheDocument();
    const cash = screen.getByRole("region", { name: "Cash now" });
    expect(await within(cash).findByRole("alert")).toHaveTextContent("The server had a problem. Please try again.");

    await user.click(within(cash).getByRole("button", { name: "Try again" }));
    expect(await within(cash).findByText("৳4,27,842")).toBeInTheDocument();
  });

  it.each([
    ["bn", "৳৪,২৭,৮৪২", "৩১ দিন"],
    ["zh", "৳427,842", "31 天"],
  ])("writes money and days for %s readers", async (lang, balance, runway) => {
    const { user } = renderApp("/");
    await screen.findByText("৳4,27,842");
    await user.selectOptions(screen.getByLabelText("Language"), lang);
    expect(await screen.findByText(balance)).toBeInTheDocument();
    expect(screen.getAllByText(runway).length).toBeGreaterThan(0);
  });
});
