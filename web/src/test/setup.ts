import "@testing-library/jest-dom/vitest";
import "../i18n";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { resetMockUsage } from "../api/mockUsage";
import i18n from "../i18n";
import { setThemePreference } from "../theme";

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  resetMockUsage();
  setThemePreference("system");
  await i18n.changeLanguage("en");
});
