import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

const liveOwner = {
  principal: { user_id: "u-judge", tenant_id: "shop-abc123", role: "owner", scopes: [], expires_at: null },
  display_name: "Judge", business_name: "Judge Test Store", totp_enrolled: false, data_mode: "live",
};

describe("Shop set-up in Settings", () => {
  it("is offered to the owner of a self-service shop, with what they entered", async () => {
    renderApp("/settings", {
      overrides: {
        "GET /api/auth/me": { body: liveOwner },
        "GET /api/onboarding/profile": { body: { opening_balance: "80000.00", opening_date: "2026-06-22", trade_licence: true } },
      },
    });
    expect(await screen.findByRole("heading", { name: "Set up your shop" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Cash on hand at the start (Tk)")).toHaveValue("80000.00");
    expect(screen.getByLabelText("Has a trade licence")).toBeChecked();
    expect(screen.getByRole("link", { name: "Download example file" })).toHaveAttribute("href", "/api/onboarding/template.csv");
  });

  it("is not shown for the synthetic demo shops", async () => {
    renderApp("/settings");
    await screen.findByRole("heading", { level: 2 });
    expect(screen.queryByRole("heading", { name: "Set up your shop" })).not.toBeInTheDocument();
  });
});
