import "@fontsource-variable/inter";
import "@fontsource/noto-sans-bengali/400.css";
import "@fontsource/noto-sans-bengali/600.css";
import "@fontsource/noto-sans-sc/400.css";
import "./index.css";
import "./i18n";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { readSavedApiMode, resolveApiMode } from "./api/apiMode";
import { applyTheme, watchSystemTheme } from "./theme";

async function start() {
  applyTheme();
  watchSystemTheme();
  const mode = resolveApiMode(import.meta.env, readSavedApiMode());
  if (mode !== "live") {
    // Loaded only when needed, so live builds never ship the mock fixtures.
    const { installMockApi } = await import("./mocks/mockApi");
    installMockApi(mode, { latencyMs: 250 }, window);
  }
  const root = document.getElementById("root");
  if (!root) throw new Error("missing #root");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
