import { expect, test } from "@playwright/test";

// External-domain audit (WP-18 extends this to every screen): the app must only talk to its
// own host, so nothing depends on services blocked in mainland China.
test("home loads and contacts no third-party host", async ({ page, baseURL }) => {
  const ownHost = new URL(baseURL ?? "http://localhost:5173").host;
  const foreign: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith("http") && url.host !== ownHost) foreign.push(url.host);
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 2, name: "Today" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(foreign, `third-party hosts contacted: ${foreign.join(", ")}`).toEqual([]);
});

test("the synthetic-data banner is visible in demo mode", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText(/synthetic/i);
});
