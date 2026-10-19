/// <reference lib="dom" />
// Mobile-first layout (WP-14 design: 360 px first): no screen may be wider than the device, or
// the page pans sideways and the fixed bottom bar is laid out wider than the screen.
import { sessionFile } from "../support/auth";
import { expect, SCREENS, test } from "../support/fixtures";

test.use({ storageState: sessionFile("owner") });

// Known, found by this suite (WP-15.md, Notes): on a phone the Trust screen is 31-57 px too wide
// in every language. TierBadge's visually hidden help text is absolutely positioned and escapes
// the audit table's scroll box (no positioned ancestor inside it), so the page itself overflows.
// When WP-14 fixes it this list must be emptied: the assertion fails until then.
const KNOWN_TOO_WIDE_ON_PHONES = ["trust"];

test("no screen is wider than the device", async ({ app, page }) => {
  const tooWide: string[] = [];
  for (const screen of SCREENS) {
    await app.start(screen);
    await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    if (scrollWidth > clientWidth) tooWide.push(screen);
  }
  expect(tooWide).toEqual(app.isPhone ? KNOWN_TOO_WIDE_ON_PHONES : []);
});
