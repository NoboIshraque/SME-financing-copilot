import { defineConfig, devices, type Project } from "@playwright/test";

// Two targets (WP-15):
//   local   `npm run e2e`: the dev stack (`npm run dev`: API :8000, web :5173, API mode "auto").
//           Started here when it is not already running.
//   hosted  `E2E_BASE_URL=https://hishab.quadbits.net npm run e2e`: the deployed demo (live API).
// Each target runs every journey twice: desktop Chrome and a phone (Pixel 7). A setup project
// signs the demo roles in once per run (`e2e/auth.setup.ts`), so journeys reuse the sessions
// instead of spending the sign-in rate limit and single-use TOTP codes on every test.
const LOCAL_URL = "http://localhost:5173";
const hostedURL = process.env.E2E_BASE_URL?.replace(/\/+$/, "");
const target = hostedURL ? "hosted" : "local";
const baseURL = hostedURL ?? LOCAL_URL;
// The Docker stack on a PC or in CI serves https://localhost with Caddy's internal CA.
const ignoreHTTPSErrors = hostedURL ? new URL(hostedURL).hostname === "localhost" : false;

const setup = `${target}-setup`;
const projects: Project[] = [
  { name: setup, testMatch: /auth\.setup\.ts$/, use: { ...devices["Desktop Chrome"] } },
  { name: target, dependencies: [setup], use: { ...devices["Desktop Chrome"] } },
  { name: `${target}-mobile`, dependencies: [setup], use: { ...devices["Pixel 7"] } },
];

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  // A journey that needs a fresh TOTP code may wait for the next 30-second step (e2e/support/totp.ts).
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The API rate-limits per client IP (WP-11): a few workers keep the run inside its budget.
  workers: 4,
  reporter: [["list"], ["html", { open: "never", outputFolder: "./playwright-report" }]],
  metadata: { target, baseURL },
  use: {
    baseURL,
    ignoreHTTPSErrors,
    locale: "en-US",
    timezoneId: "Asia/Dhaka",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
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
