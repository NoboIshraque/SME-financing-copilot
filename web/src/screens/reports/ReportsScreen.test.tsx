import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LENDER, renderApp } from "../../test/render";

describe("Reports & Trust Passport", () => {
  it("shows the latest passport: evidence, attestations, honesty record, anchor and verify link", async () => {
    renderApp("/reports");
    const passport = await screen.findByRole("article", { name: /Version 2/ });
    expect(within(passport).getByText("Mobile money statements").nextSibling).toHaveTextContent("checked against source");
    expect(within(passport).getByText("e-TIN").nextSibling).toHaveTextContent("self-declared");
    expect(passport).toHaveTextContent("12 confirmed, 1 disputed");
    expect(passport).toHaveTextContent("How often DecisionGuard said \"I don't know\"6%");
    expect(passport).not.toHaveTextContent("Audit drill");  // P8 (nightly audit drill) was cut
    expect(passport).toHaveTextContent("Anchored on Ethereum Sepolia (testnet)");
    expect(within(passport).getByRole("link", { name: "Open the public verify page" })).toHaveAttribute("href", "/verify/pp-grocery-2");
  });

  it("shares with a lender for a limited scope and time, behind the owner's code", async () => {
    const { user, db, fetchMock } = renderApp("/reports");
    const form = await screen.findByRole("form", { name: "Share with a lender" });
    await user.type(within(form).getByLabelText("Lender's name"), "Bank Asia SME desk");
    await user.click(within(form).getByLabelText("Statements"));
    await user.selectOptions(within(form).getByLabelText("Access ends after"), "14");
    await user.click(within(form).getByRole("button", { name: "Share with code" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm it's you" });
    expect(dialog).toHaveTextContent("Share your passport with Bank Asia SME desk for 14 days");
    await user.type(within(dialog).getByLabelText("6-digit code"), "246810");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));

    const shares = screen.getByRole("region", { name: "Who can see it" });
    expect(await within(shares).findByRole("listitem", { name: "Bank Asia SME desk" })).toHaveTextContent("Trust Passport, Statements · until 14 October 2026");
    expect(db.shares).toHaveLength(2);
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/share"));
    expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ lender_label: "Bank Asia SME desk", scopes: ["passport:read", "statements:read"], days: 14 });
  });

  it("revokes a lender's access", async () => {
    const { user, db } = renderApp("/reports");
    const shares = await screen.findByRole("region", { name: "Who can see it" });
    const grant = await within(shares).findByRole("listitem", { name: "Lender 1 (demo)" });
    await user.click(within(grant).getByRole("button", { name: "Revoke" }));
    expect(await within(grant).findByText(/revoked/)).toBeInTheDocument();
    expect(db.shares[0]?.revoked).toBe(true);
  });

  it("gives a lender viewer the shared passport read-only, with the access end date", async () => {
    renderApp("/reports", { signedInAs: LENDER });
    expect(await screen.findByRole("note")).toHaveTextContent("Your access ends on 25 October 2026.");
    await screen.findByRole("article", { name: /Version 2/ });
    expect(screen.queryByRole("button", { name: "Issue a new version" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Share with a lender" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Who can see it" })).not.toBeInTheDocument();
  });
});

describe("public verify page", () => {
  it("verifies a passport without signing in", async () => {
    const { user } = renderApp("/verify/pp-grocery-2", { signedInAs: null });
    const input = await screen.findByLabelText("Passport ID");
    expect(input).toHaveValue("pp-grocery-2");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Genuine: this passport has not been changed since it was anchored.")).toBeInTheDocument();
    expect(screen.getAllByText("3c9e1a7b5d2f4e6081a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f7a8")).toHaveLength(2);
  });

  it("says plainly when a passport is not genuine or does not exist", async () => {
    const { user } = renderApp("/verify", {
      signedInAs: null,
      overrides: {
        "GET /api/verify/pp-edited": { body: { passport_id: "pp-edited", recomputed_digest: "11", anchored_digest: "22", valid: false, checked_on: "2026-10-01" } },
      },
    });
    await user.type(await screen.findByLabelText("Passport ID"), "pp-edited");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Not genuine: the passport does not match its anchored fingerprint.")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Passport ID"));
    await user.type(screen.getByLabelText("Passport ID"), "pp-nope");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No passport with that ID.");
  });
});
