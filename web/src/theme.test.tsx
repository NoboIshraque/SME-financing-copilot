import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "./components/ThemeToggle";
import { getThemePreference, setThemePreference } from "./theme";

function prefersDark(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-color-scheme: dark)" ? matches : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("theme", () => {
  it("applies and remembers an explicit choice", () => {
    setThemePreference("dark");
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("hishab.theme")).toBe("dark");

    setThemePreference("light");
    expect(document.documentElement).not.toHaveClass("dark");
    expect(window.localStorage.getItem("hishab.theme")).toBe("light");
  });

  it("follows the OS setting when the choice is 'system', and stores nothing", () => {
    prefersDark(true);
    setThemePreference("system");
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("hishab.theme")).toBeNull();

    prefersDark(false);
    setThemePreference("system");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("header toggle flips the theme and reports whether dark mode is on", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const toggle = screen.getByRole("button", { name: "Dark mode" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).toHaveClass("dark");
    expect(getThemePreference()).toBe("dark");
  });
});
