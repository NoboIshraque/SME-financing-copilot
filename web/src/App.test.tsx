import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { SCREENS } from "./components/AppShell";
import i18n from "./i18n";

function stubHealth(banner: "synthetic" | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", contracts_version: "1.0.0", data_mode_banner: banner }), {
        status: 200,
      }),
    ),
  );
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<App initialPath={path} queryClient={queryClient} />);
}

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("App shell", () => {
  it("shows a navigation link for every screen", () => {
    stubHealth(null);
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(SCREENS.length);
  });

  it.each([
    ["/", "Today"],
    ["/cash", "Cash"],
    ["/mesh", "Mesh"],
    ["/trust", "Trust & audit"],
  ])("route %s renders the %s screen", (path, heading) => {
    stubHealth(null);
    renderAt(path);
    expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
  });

  it("shows the synthetic-data banner when the server runs on synthetic data", async () => {
    stubHealth("synthetic");
    renderAt("/");
    expect(await screen.findByRole("status")).toHaveTextContent(/synthetic/i);
  });

  it("shows no banner on real data", async () => {
    stubHealth(null);
    renderAt("/");
    await screen.findByRole("heading", { level: 2 });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("switches the whole UI to Bangla", async () => {
    stubHealth(null);
    renderAt("/cash");
    await userEvent.selectOptions(screen.getByLabelText("Language"), "bn");
    expect(await screen.findByRole("heading", { level: 2, name: "নগদ" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("bn");
  });
});
