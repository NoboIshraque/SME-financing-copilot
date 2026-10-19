import { resolve } from "node:path";

import { defineConfig, devices, type Project, type ReporterDescription } from "@playwright/test";

// Two targets (WP-15):
//   local   `npm run e2e`: the dev stack (`npm run dev`: API :8000, web :5173, API mode "auto").
//           Started here when it is not already running.
//   hosted  `E2E_BASE_URL=https://hishab.quadbits.net npm run e2e`: the deployed demo (live API).
//           Evidence run: every test keeps a trace, a video and a screenshot, and a summary is
//           written to docs/submission/evidence/e2e/ (or E2E_EVIDENCE_DIR).
// Each target runs every journey twice: desktop Chrome and a phone (Pixel 7). A setup project
// signs the demo roles in once per run (`e2e/auth.setup.ts`), so journeys reuse the sessions
// instead of spending the sign-in rate limit and single-use TOTP codes on every test; a teardown
// project signs them out again.
const LOCAL_URL = "http://localhost:5173";
const hostedURL = process.env.E2E_BASE_URL?.replace(/\/+$/, "");
const target = hostedURL ? "hosted" : "local";
const baseURL = hostedURL ?? LOCAL_URL;
// The Docker stack on a PC or in CI serves https://localhost with Caddy's internal CA.
const ignoreHTTPSErrors = hostedURL ? new URL(hostedURL).hostname === "localhost" : false;
const evidenceDir = resolve(process.env.E2E_EVIDENCE_DIR ?? "../docs/submission/evidence/e2e");

const setup = `${target}-setup`;
const teardown = `${target}-teardown`;
const projects: Project[] = [
  { name: setup, testMatch: /auth\.setup\.ts$/, teardown, use: { ...devices["Desktop Chrome"] } },
  { name: teardown, testMatch: /auth\.teardown\.ts$/, use: { ...devices["Desktop Chrome"] } },
  { name: target, dependencies: [setup], use: { ...devices["Desktop Chrome"] } },
  { name: `${target}-mobile`, dependencies: [setup], use: { ...devices["Pixel 7"] } },
];

const knownBugs: ReporterDescription = ["./e2e/support/known-bugs-reporter.ts"];
const reporter: ReporterDescription[] = hostedURL
  ? [["list"], ["html", { open: "never", outputFolder: `${evidenceDir}/report` }], knownBugs, ["./e2e/support/evidence-reporter.ts", { dir: evidenceDir }]]
  : [["list"], ["html", { open: "never", outputFolder: "./test-results/report" }], knownBugs];

export default defineConfig({
  testDir: "./e2e",
  // Local: everything a run writes stays under test-results/: git-ignored, and outside the Vite
  // dev server's file watcher (on Windows a watched report file being written crashes `npm run dev`).
  outputDir: hostedURL ? `${evidenceDir}/artifacts` : "./test-results/artifacts",
  // Local: the synthetic universe is loaded into the dev database first (idempotent).
  globalSetup: "./e2e/global-setup.ts",
  // A journey that needs a fresh TOTP code may wait for the next 30-second step (e2e/support/totp.ts).
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The API rate-limits per client IP (WP-11): a few workers keep the run inside its budget. The
  // local dev API runs on SQLite, where parallel engine writes collide ("database is locked").
  workers: hostedURL ? 4 : 2,
  reporter,
  metadata: { target, baseURL },
  use: {
    baseURL,
    ignoreHTTPSErrors,
    locale: "en-US",
    timezoneId: "Asia/Dhaka",
    trace: hostedURL ? "on" : "retain-on-failure",
    screenshot: hostedURL ? "on" : "only-on-failure",
    video: hostedURL ? "on" : "retain-on-failure",
  },
  projects,
  webServer: hostedURL
    ? undefined
    : {
        command: "npm run dev",
        cwd: "..",
        // Through the Vite proxy, so both the web server and the API are up.
        url: `${LOCAL_URL}/api/health`,
        reuseExistingServer: true,
        timeout: 180_000,
        stdout: "ignore",
        stderr: "pipe",
      },
});
