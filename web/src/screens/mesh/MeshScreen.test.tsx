import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { initialRounds } from "../../mocks/fixtures/mesh";
import { renderApp } from "../../test/render";

const GARMENT = "garment@hishab.demo";

describe("Mesh screen", () => {
  it("tells a business outside any debt ring what the mesh will do", async () => {
    renderApp("/mesh");
    expect(await screen.findByText(/You are not in any debt ring yet/)).toBeInTheDocument();
  });

  it("lists who owes whom in the ring, with amounts and due dates", async () => {
    renderApp("/mesh", { signedInAs: GARMENT });
    const graph = await screen.findByRole("region", { name: "Who owes whom" });
    const items = within(graph).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Ashulia Stitch Works owes Islampur Fabric House ৳4,50,000 · due 12 Oct (confirmed by both sides)");
    expect(items[2]).not.toHaveTextContent("confirmed by both sides");
  });

  it("shows the proposed round: debt cleared, cash needed, settlements and approvals", async () => {
    renderApp("/mesh", { signedInAs: GARMENT });
    const round = await screen.findByRole("article", { name: "Proposed netting round" });
    expect(round).toHaveTextContent("Clears ৳11,50,000 of debt with only ৳1,30,000");
    expect(round).toHaveTextContent("Ashulia Stitch Works pays Islampur Fabric House ৳70,000");
    expect(within(round).getByText("Islampur Fabric House").nextSibling).toHaveTextContent("approved");
    expect(within(round).getByText("Ashulia Stitch Works (you)").nextSibling).toHaveTextContent("waiting");
  });

  it("approves the round only with the owner's code, then waits for the others", async () => {
    const { user, db } = renderApp("/mesh", { signedInAs: GARMENT });
    const round = await screen.findByRole("article", { name: "Proposed netting round" });
    await user.click(within(round).getByRole("button", { name: "Approve the round with code" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    expect(dialog).toHaveTextContent("Clear ৳11,50,000 of debt by paying ৳1,30,000 in total");
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    expect(await within(round).findByText("You approved. Waiting for Nawabpur Hardware Traders.")).toBeInTheDocument();
    expect(db.rounds[0]?.approvals).toEqual({ sme_fabric: true, sme_garment: true });
  });

  it("links a settled round to its testnet transaction and verifies the hash", async () => {
    const rounds = initialRounds();
    const settled = rounds[1];
    if (settled?.anchor) settled.anchor = { ...settled.anchor, explorer_url: "https://sepolia.etherscan.io/tx/0x5e1d3a7c" };
    const { user } = renderApp("/mesh", { signedInAs: GARMENT, overrides: { "GET /api/mesh/rounds": { body: rounds } } });
    const card = await screen.findByRole("article", { name: "Settled round of 20 August 2026" });
    expect(within(card).getByText("Anchored on Ethereum Sepolia (testnet)")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Transaction 0x5e1d3a7c/ })).toHaveAttribute("href", "https://sepolia.etherscan.io/tx/0x5e1d3a7c");
    await user.click(within(card).getByRole("button", { name: "Verify against the chain" }));
    expect(await within(card).findByText("Verified: the record matches the anchored hash.")).toBeInTheDocument();
  });

  it("warns loudly when the record does not match the anchored hash", async () => {
    const { user } = renderApp("/mesh", {
      signedInAs: GARMENT,
      overrides: { "GET /api/mesh/rounds/:id/verify": { body: { round_id: "round-2026-08", valid: false, recomputed_digest: "00", anchor: null } } },
    });
    const card = await screen.findByRole("article", { name: "Settled round of 20 August 2026" });
    await user.click(within(card).getByRole("button", { name: "Verify against the chain" }));
    expect(await within(card).findByText("Does not match the anchored hash. Do not trust this record.")).toBeInTheDocument();
  });
});
