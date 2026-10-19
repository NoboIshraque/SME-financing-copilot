import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SCREENS } from "./navigation";
import { LENDER, renderApp } from "./test/render";

describe("App shell", () => {
  it("shows the owner a navigation link for every screen", async () => {
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(SCREENS.length);
  });

  it.each([
    ["/", "Today"],
    ["/cash", "Cash"],
    ["/mesh", "Mesh"],
    ["/trust", "Trust & audit"],
  ])("route %s renders the %s screen and names the browser tab", async (path, heading) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    expect(document.title).toBe(`${heading} · DecisionGuard`);
  });

  it("sends a signed-out visitor to sign in", async () => {
    renderApp("/receivables", { signedInAs: null });
    expect(await screen.findByRole("heading", { level: 2, name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the synthetic-data banner when the server runs on synthetic data", async () => {
    renderApp("/");
    expect(await screen.findByRole("status")).toHaveTextContent(/synthetic/i);
  });

  it("shows no banner on real data", async () => {
    renderApp("/", {
      overrides: { "GET /api/health": { body: { status: "ok", contracts_version: "1.1.0", data_mode_banner: null } } },
    });
    await screen.findByRole("heading", { level: 2 });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("switches the whole UI to Bangla and remembers the choice", async () => {
    const { user } = renderApp("/cash");
    await user.selectOptions(await screen.findByLabelText("Language"), "bn");
    expect(await screen.findByRole("heading", { level: 2, name: "নগদ" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("bn");
    expect(window.localStorage.getItem("hishab.language")).toBe("bn");
  });

  it("tells a lender viewer plainly that a screen is outside their access", async () => {
    renderApp("/cash", { signedInAs: LENDER });
    expect(await screen.findByRole("heading", { level: 2, name: "Not available for your role" })).toBeInTheDocument();
    expect(
      screen.getByText("Your role (Lender (view only)) doesn't use this screen. Ask the owner if you need access."),
    ).toBeInTheDocument();
  });

  it("signs out, drops cached business data and returns to the sign-in screen", async () => {
    const { user, db, queryClient } = renderApp("/cash");
    await screen.findByRole("table", { name: "Week-by-week forecast balance" });
    expect(queryClient.getQueryData(["cash", "forecast"])).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Sign in" })).toBeInTheDocument();
    expect(db.session).toBeNull();
    expect(queryClient.getQueryData(["cash", "forecast"])).toBeUndefined();
  });

  it("returns to sign-in when any API call says the session has ended", async () => {
    renderApp("/", {
      overrides: { "GET /api/health": { status: 401, body: { code: "not_authenticated", message_key: "error.not_authenticated" } } },
    });
    expect(await screen.findByRole("heading", { level: 2, name: "Sign in" })).toBeInTheDocument();
  });

  it("opens the full menu from the phone bar's More button", async () => {
    const { user } = renderApp("/");
    const more = await screen.findByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Today" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(more).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a not-found page for unknown addresses", async () => {
    renderApp("/no-such-screen");
    expect(await screen.findByRole("heading", { level: 2, name: "Page not found" })).toBeInTheDocument();
  });
});
