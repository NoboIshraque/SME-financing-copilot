import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DEMO_PASSWORD } from "../mocks/db";
import { renderApp, requestedPaths } from "../test/render";
import { safeNext } from "./session";

describe("sign-in screen", () => {
  it("signs a password account in and returns to the page it came from", async () => {
    const { user } = renderApp("/cash", { signedInAs: null });
    expect(await screen.findByRole("heading", { level: 2, name: "Sign in" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "accountant@hishab.demo");
    await user.type(screen.getByLabelText("Password"), DEMO_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Cash" })).toBeInTheDocument();
    expect(screen.getByText("Mirpur Mudi Store")).toBeInTheDocument();
  });

  it("explains a wrong password and stays signed out", async () => {
    const { user, db } = renderApp("/", { signedInAs: null });
    await user.type(await screen.findByLabelText("Email"), "accountant@hishab.demo");
    await user.type(screen.getByLabelText("Password"), "not-the-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That email and password don't match.");
    expect(screen.getByRole("alert")).toHaveTextContent("After 5 wrong tries the account locks for 15 minutes.");
    expect(db.session).toBeNull();
  });

  it("asks for the TOTP code next and accepts it typed in Bangla digits", async () => {
    const { user } = renderApp("/", { signedInAs: null });
    await user.type(await screen.findByLabelText("Email"), "owner@hishab.demo");
    await user.type(screen.getByLabelText("Password"), DEMO_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Enter your code" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("6-digit code"), "২৪৬৮১০");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Today" })).toBeInTheDocument();
  });

  it("rejects a malformed code without calling the server", async () => {
    const { user, fetchMock } = renderApp("/", { signedInAs: null });
    await user.type(await screen.findByLabelText("Email"), "owner@hishab.demo");
    await user.type(screen.getByLabelText("Password"), DEMO_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.type(await screen.findByLabelText("6-digit code"), "24a8");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the 6 digits of the code.");
    expect(requestedPaths(fetchMock)).not.toContain("/api/auth/login/totp");
  });

  it("offers one-tap demo accounts and shows the demo code to TOTP accounts", async () => {
    const { user } = renderApp("/", { signedInAs: null });
    await user.click(await screen.findByRole("button", { name: /Sign in as Owner.*Mirpur Mudi Store/ }));

    expect(await screen.findByRole("heading", { level: 2, name: "Enter your code" })).toBeInTheDocument();
    expect(screen.getByText("Demo code: 246810")).toBeInTheDocument();
  });

  it("shows the demo code fetched on reaching the code step, not the one from page load", async () => {
    // The listing loaded with the page holds a code that has expired by the time the owner taps.
    let listings = 0;
    const { user, db, fetchMock } = renderApp("/", {
      signedInAs: null,
      overrides: {
        "GET /api/auth/demo-accounts": () => {
          listings += 1;
          const code = listings === 1 ? "111111" : "222222";
          return { body: db.users.map((u) => ({ email: u.email, password: u.password, role: u.role, business_name: u.business_name, totp_hint: u.totp ? code : null })) };
        },
      },
    });
    await user.click(await screen.findByRole("button", { name: /Sign in as Owner.*Mirpur Mudi Store/ }));

    expect(await screen.findByText("Demo code: 222222")).toBeInTheDocument();
    expect(screen.queryByText("Demo code: 111111")).not.toBeInTheDocument();
    expect(requestedPaths(fetchMock).filter((path) => path === "/api/auth/demo-accounts")).toHaveLength(2);
  });

  it("says the free server is waking up when sign-in gets no answer from the API", async () => {
    const { user } = renderApp("/", { signedInAs: null, overrides: { "POST /api/auth/login": { status: 503 } } });
    await user.type(await screen.findByLabelText("Email"), "accountant@hishab.demo");
    await user.type(screen.getByLabelText("Password"), DEMO_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is waking up");
  });

  it("sends a lender viewer to the only screens their consent covers", async () => {
    const { user } = renderApp("/", { signedInAs: null });
    await user.click(await screen.findByRole("button", { name: /Sign in as Lender \(view only\)/ }));

    expect(await screen.findByRole("heading", { level: 2, name: "Reports" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(["Reports", "Settings"]);
  });

  it("keeps the language switch on the sign-in screen", async () => {
    const { user } = renderApp("/", { signedInAs: null });
    await user.selectOptions(await screen.findByLabelText("Language"), "zh");
    expect(await screen.findByRole("heading", { level: 2, name: "登录" })).toBeInTheDocument();
  });
});

describe("safeNext", () => {
  it.each([
    [null, "/"],
    ["/cash?tab=gaps", "/cash?tab=gaps"],
    ["https://evil.example/phish", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    ["/login?next=/cash", "/"],
  ])("%s -> %s", (next, expected) => {
    expect(safeNext(next)).toBe(expected);
  });
});
