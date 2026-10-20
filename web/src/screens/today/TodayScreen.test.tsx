import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Alert, Recommendation } from "../../api/contracts";
import { alerts, cashForecast } from "../../mocks/fixtures/cash";
import { money, NOW } from "../../mocks/fixtures/common";
import { todayRecommendation } from "../../mocks/fixtures/copilot";
import i18n from "../../i18n";
import { ACCOUNTANT, renderApp, requestedPaths } from "../../test/render";

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

  it("asks the copilot for today's advice in the language the owner reads", async () => {
    await i18n.changeLanguage("bn");
    const { fetchMock } = renderApp("/");
    await screen.findAllByRole("article");
    expect(requestedPaths(fetchMock).filter((path) => path.includes("/api/copilot/today"))).toContain(
      "/api/copilot/today?language=bn",
    );
  });

  it("lists two supplier bills that drive the same gap as two rows", async () => {
    const twoBills: Alert = {
      ...criticalAlert,
      gap: {
        ...criticalAlert.gap!,
        drivers: [
          { kind: "bill_due", label_key: "driver.supplier_bill", amount: money(12000), reference_id: "bill-1" },
          { kind: "bill_due", label_key: "driver.supplier_bill", amount: money(7000), reference_id: "bill-2" },
        ],
      },
    };
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      renderApp("/", { overrides: { "GET /api/cash/alerts": { body: [twoBills] } } });
      const critical = await screen.findByRole("article", { name: "Payroll at risk" });
      const why = within(critical).getByText("Why").nextElementSibling as HTMLElement;
      expect(within(why).getAllByRole("listitem")).toHaveLength(2);
      expect(within(why).getByText("৳12,000")).toBeInTheDocument();
      expect(within(why).getByText("৳7,000")).toBeInTheDocument();
      expect(errors.mock.calls.some((call) => String(call[0]).includes("same key"))).toBe(false);
    } finally {
      errors.mockRestore();
    }
  });
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

  it("approves and executes an EXECUTE card through WP-11 approvals, with the code and idempotency keys", async () => {
    const { user, db, fetchMock } = renderApp("/");
    const retime = await screen.findByRole("article", { name: "Pay a supplier later, within terms" });
    expect(within(retime).getByText("Supplier 2 · due 31 Oct · new date 10 Nov")).toBeInTheDocument();
    await user.click(within(retime).getByRole("button", { name: "Approve with code" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    expect(await within(retime).findByText("Approved and carried out. It is recorded in the audit log.")).toBeInTheDocument();
    const record = db.approvals.find((r) => r.card.id === "act-retime-supplier-2");
    expect(record?.approval).toMatchObject({ status: "executed", step_up_verified: true });
    const headersOf = (suffix: string) => {
      const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith(suffix));
      return (call?.[1] as RequestInit).headers as Record<string, string>;
    };
    expect(headersOf("/api/approvals")["X-Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(headersOf("/approve")["X-Step-Up-Code"]).toBe("246810");
    expect(headersOf("/execute")["X-Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("approves a DRAFT card's message draft with the owner's code (the message leaves DecisionGuard)", async () => {
    const { user, db } = renderApp("/");
    const remind = await screen.findByRole("article", { name: "Send a payment reminder" });
    await user.click(within(remind).getByRole("button", { name: "Approve draft with code" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(remind).findByText("Approved. It is recorded in the audit log.")).toBeInTheDocument();
    expect(db.drafts.find((d) => d.id === "msg-overdue-9")?.status).toBe("approved");
  });

  it("lets an accountant only ask the owner to approve an EXECUTE card", async () => {
    const { user, db } = renderApp("/", { signedInAs: ACCOUNTANT });
    const retime = await screen.findByRole("article", { name: "Pay a supplier later, within terms" });
    expect(within(retime).queryByRole("button", { name: "Approve with code" })).not.toBeInTheDocument();
    await user.click(within(retime).getByRole("button", { name: "Ask the owner to approve" }));
    expect(await within(retime).findByText("Sent to the owner for approval.")).toBeInTheDocument();
    expect(db.approvals.find((r) => r.card.id === "act-retime-supplier-2")?.approval).toMatchObject({ status: "pending", requested_by: "u-accountant" });
    expect(within(card(/Send a payment reminder/)).getByText("Only the owner can approve this.")).toBeInTheDocument();
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
    expect(within(denied).getByText("Blocked: DecisionGuard never does this.")).toBeInTheDocument();
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
