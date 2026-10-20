import { act, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { OWNER, renderApp } from "./test/render";

// WCAG 2.1 A and AA rules. Colour contrast needs real layout and fonts, which jsdom does not
// have: the Playwright axe run on the hosted app (WP-15) checks it.
const WCAG21_AA = {
  runOnly: { type: "tag" as const, values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
  rules: { "color-contrast": { enabled: false } },
};

async function violations(): Promise<string[]> {
  const results = await axe(document.body, WCAG21_AA);
  return results.violations.map((v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

describe("WCAG 2.1 AA (axe)", () => {
  it.each([
    ["sign-in", "/", null, "Try the demo"],
    ["Today", "/", OWNER, "৳4,27,842"],
    ["Cash", "/cash", OWNER, "Week 13 (30 Dec)"],
    ["Receivables", "/receivables", OWNER, "৳21,859"],
    ["Analysis", "/analysis", OWNER, "94.2%"],
    ["Mesh", "/mesh", "garment@hishab.demo", "Proposed netting round"],
    ["Market", "/market", OWNER, "Onion (local) is up"],
    ["Messages", "/messages", OWNER, "Overdue reminder · Customer 9"],
    ["Reports", "/reports", OWNER, "Version 2 · 30 September 2026"],
    ["Trust & audit", "/trust", OWNER, "Intact: 1,284 entries, each linked to the one before."],
    ["Settings", "/settings", OWNER, "Mirpur Mudi Store"],
    ["public verify", "/verify/pp-grocery-2", null, "Verify a Trust Passport"],
  ])("%s screen has no violations", async (_name, path, signedInAs, ready) => {
    renderApp(path, { signedInAs });
    await screen.findAllByText(new RegExp(ready.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    expect(await violations()).toEqual([]);
  });

  it("financing results, with every option and the application card, have no violations", async () => {
    const { user } = renderApp("/financing");
    await user.click(await screen.findByRole("button", { name: "Find options" }));
    await screen.findByRole("region", { name: "Your options, best first" });
    expect(await violations()).toEqual([]);
  });

  it("the provenance drawer has no violations", async () => {
    const { user } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: /^Cash now: ৳4,27,842\./ }));
    await within(screen.getByRole("dialog")).findByText("opening_balance + cash_in - cash_out");
    expect(await violations()).toEqual([]);
  });

  it("the copilot panel with an answer has no violations", async () => {
    const { user } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Ask DecisionGuard" }));
    const panel = screen.getByRole("dialog", { name: "Ask DecisionGuard" });
    await user.click(within(panel).getByRole("button", { name: "Which customer should I chase first?" }));
    await within(panel).findByText(/Chase Customer 10 first/);
    expect(await violations()).toEqual([]);
  });
});

describe("offline shell", () => {
  it("tells the user when the device goes offline, and clears when it is back", async () => {
    renderApp("/");
    await screen.findByText("৳4,27,842");
    const onLine = Object.getOwnPropertyDescriptor(Navigator.prototype, "onLine");
    let online = false;
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => online });
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByText("You're offline. The app still opens, but numbers need a connection.")).toBeInTheDocument();

    online = true;
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.queryByText(/You're offline/)).not.toBeInTheDocument();
    if (onLine) Object.defineProperty(Navigator.prototype, "onLine", onLine);
    delete (navigator as { onLine?: boolean }).onLine;
  });
});
