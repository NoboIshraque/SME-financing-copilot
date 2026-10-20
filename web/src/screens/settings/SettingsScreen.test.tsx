import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ACCOUNTANT, LENDER, renderApp } from "../../test/render";

describe("Settings screen", () => {
  it("shows who is signed in and applies the chosen theme", async () => {
    const { user } = renderApp("/settings");
    const profile = await screen.findByRole("region", { name: "You" });
    expect(profile).toHaveTextContent("RoleOwner");
    expect(profile).toHaveTextContent("BusinessMirpur Mudi Store");
    expect(profile).toHaveTextContent("Two-step sign-inOn (authenticator code)");
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
  });

  it("lets the owner opt in to auto-sent reminders and saves it", async () => {
    const { user, db } = renderApp("/settings");
    const notify = await screen.findByRole("region", { name: "Notifications" });
    await user.click(await within(notify).findByLabelText(/Send low-risk reminders automatically/));
    await user.click(within(notify).getByRole("button", { name: "Save" }));
    expect(await within(notify).findByText("Saved.")).toBeInTheDocument();
    expect(db.settings).toEqual({ auto_send_reminders: true, email_alerts: true });
  });

  it("keeps the auto-send choice with the owner", async () => {
    renderApp("/settings", { signedInAs: ACCOUNTANT });
    const notify = await screen.findByRole("region", { name: "Notifications" });
    expect(await within(notify).findByLabelText(/Send low-risk reminders automatically/)).toBeDisabled();
    expect(within(notify).getByText("Only the owner can change this.")).toBeInTheDocument();
  });

  it("leaves out the notifications card when the server has no settings route", async () => {
    renderApp("/settings", { overrides: { "GET /api/settings": { status: 404, body: { detail: "Not Found" } } } });
    expect(await screen.findByRole("heading", { level: 3, name: "Data" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("region", { name: "Notifications" })).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a lender viewer when access ends, without business settings", async () => {
    renderApp("/settings", { signedInAs: LENDER });
    expect(await screen.findByRole("region", { name: "You" })).toHaveTextContent("Access until25 October 2026");
    expect(screen.queryByRole("region", { name: "Notifications" })).not.toBeInTheDocument();
  });
});
