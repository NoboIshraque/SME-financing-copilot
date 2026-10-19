import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { auditVerification } from "../../mocks/fixtures/inbox";
import { renderApp } from "../../test/render";

describe("Trust & audit screen", () => {
  it("shows the audit chain intact with its anchored head, and the drill score", async () => {
    renderApp("/trust");
    const chain = await screen.findByRole("region", { name: "Audit log" });
    expect(await within(chain).findByText("Intact: 1,284 entries, each linked to the one before.")).toBeInTheDocument();
    expect(await within(chain).findByText(/Anchored on Ethereum Sepolia \(testnet\)/)).toBeInTheDocument();
    expect(chain).toHaveTextContent("Transaction 0x2b4d6f8a");
    const drill = screen.getByRole("region", { name: "Nightly audit drill" });
    expect(await within(drill).findByText("90%")).toBeInTheDocument();
    expect(drill).toHaveTextContent("caught 18 of 20 planted errors");
  });

  it("lists recent actions with their tiers and every abstention with what was missing", async () => {
    renderApp("/trust");
    const events = await screen.findByRole("region", { name: "Recent actions" });
    const rows = (await within(events).findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(5);
    expect(rows[1]).toHaveTextContent("Blocked a suspicious instruction · chat-msg-77");
    expect(rows[1]?.querySelector("[data-tier]")).toHaveAttribute("data-tier", "DENY");
    const log = screen.getByRole("region", { name: "When Hishab said \"I don't know\"" });
    const first = (await within(log).findAllByRole("listitem"))[0];
    expect(first).toHaveTextContent("How big a loan can I safely take for Eid stock?");
    expect(first?.querySelector("q")).toHaveTextContent("How big a loan can I safely take for Eid stock?");
    expect(first).toHaveTextContent("Missing: last year's Eid-ul-Adha sales (only 5 months of history)");
  });

  it("says where the chain broke when it was tampered with", async () => {
    renderApp("/trust", { overrides: { "GET /api/audit/verify": { body: { ...auditVerification(), valid: false, first_bad_seq: 812, reason: "hash mismatch at seq 812" } } } });
    const chain = await screen.findByRole("region", { name: "Audit log" });
    expect(await within(chain).findByText("Broken at entry 812: something was changed or removed.")).toBeInTheDocument();
    expect(within(chain).getByText("hash mismatch at seq 812")).toBeInTheDocument();
  });
});
