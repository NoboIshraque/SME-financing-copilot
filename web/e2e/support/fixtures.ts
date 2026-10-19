// The `test` every journey imports: Playwright's, plus `app` (moving around the signed-in shell
// the way a person does, on a phone or a desktop) and `foreignHosts` (every third-party host the
// page contacted: the China-reachability audit, WP-18 milestone 4).
import { test as base, expect, type Locator, type Page } from "@playwright/test";

import { t, type Language } from "./i18n";

export const SCREENS = [
  "today",
  "cash",
  "receivables",
  "financing",
  "analysis",
  "mesh",
  "market",
  "messages",
  "reports",
  "trust",
  "settings",
] as const;
export type Screen = (typeof SCREENS)[number];

/** Below Tailwind's `md` the shell shows the phone layout: bottom bar plus a "More" drawer. */
const PHONE_MAX_WIDTH = 767;

export class App {
  language: Language = "en";

  constructor(readonly page: Page) {}

  get isPhone(): boolean {
    return (this.page.viewportSize()?.width ?? 1280) <= PHONE_MAX_WIDTH;
  }

  t(key: string, values: Record<string, string | number> = {}): string {
    return t(key, values, this.language);
  }

  heading(screen: Screen): Locator {
    return this.page.getByRole("heading", { level: 2, name: this.t(`nav.${screen}`), exact: true });
  }

  /** Start a journey on a screen (a full page load: the offline mock starts from its seed). */
  async start(screen: Screen): Promise<void> {
    await this.page.goto(screen === "today" ? "/" : `/${screen}`);
    await expect(this.heading(screen)).toBeVisible();
  }

  /** Go to a screen through the navigation, keeping this page's state (no reload). */
  async open(screen: Screen): Promise<void> {
    const name = this.t(`nav.${screen}`);
    if (this.isPhone) {
      const quick = this.page.getByRole("navigation", { name: this.t("nav.quick") });
      const shortcut = quick.getByRole("link", { name, exact: true });
      if ((await shortcut.count()) > 0) {
        await shortcut.click();
      } else {
        await quick.getByRole("button", { name: this.t("nav.more") }).click();
        await this.mainNav().getByRole("link", { name, exact: true }).click();
      }
    } else {
      await this.mainNav().getByRole("link", { name, exact: true }).click();
    }
    await expect(this.heading(screen)).toBeVisible();
  }

  mainNav(): Locator {
    return this.page.getByRole("navigation", { name: this.t("nav.main") });
  }

  /** The language switch in the header of every screen, signed in or not. */
  async switchLanguage(language: Language): Promise<void> {
    await this.page.getByRole("banner").getByRole("combobox").selectOption(language);
    this.language = language;
    await expect(this.page.locator("html")).toHaveAttribute("lang", language);
  }

  banner(): Locator {
    return this.page.getByRole("status").filter({ hasText: this.t("banner.synthetic") });
  }
}

export const test = base.extend<{ app: App; foreignHosts: string[] }>({
  app: async ({ page }, provide) => {
    await provide(new App(page));
  },
  foreignHosts: async ({ page, baseURL }, provide) => {
    const own = new URL(baseURL ?? "http://localhost:5173").host;
    const hosts: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.protocol.startsWith("http") && url.host !== own && !hosts.includes(url.host)) hosts.push(url.host);
    });
    await provide(hosts);
  },
});

export { expect };
