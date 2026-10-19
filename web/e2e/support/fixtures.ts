// The `test` every journey imports: Playwright's, plus `app` (moving around the signed-in shell
// the way a person does, on a phone or a desktop) and `foreignHosts` (every third-party host the
// page contacted: the China-reachability audit, WP-18 milestone 4).
import { readFileSync } from "node:fs";

import { test as base, expect, type BrowserContext, type Locator, type Page } from "@playwright/test";

import { demoAccounts, homeAccount, type DemoAccount, type Role } from "./accounts";
import { signInThroughApi } from "./auth";
import { t, type Language } from "./i18n";
import { routeIsLive } from "./target";
import { MOCK_TOTP_CODE, withFreshCode } from "./totp";

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

/** The backend call behind a step-up dialog: probed to pick the code, awaited to read the verdict. */
export interface StepUpCall {
  /** "METHOD /path" for routeIsLive, e.g. "POST /api/approvals/probe/approve". */
  route: string;
  /** Matches the request URL that carries the code. */
  url: RegExp;
}

export const APPROVE_CALL: StepUpCall = { route: "POST /api/approvals/probe/approve", url: /\/api\/approvals\/[^/]+\/approve$/ };

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

  /** The home business's demo account for a role (support/accounts.ts). */
  account(role: Role): Promise<DemoAccount> {
    return homeAccount(this.page.request, role);
  }

  /** Sign this browser context in as `account` (API sign-in; the cookie lands in the context). */
  async signInAs(account: DemoAccount): Promise<void> {
    await signInThroughApi(this.page.request, account);
  }

  /** Put a saved session (support/auth.ts) into this browser context. */
  async useSession(file: string): Promise<void> {
    const state = JSON.parse(readFileSync(file, "utf8")) as { cookies: Parameters<BrowserContext["addCookies"]>[0] };
    await this.page.context().addCookies(state.cookies);
  }

  /** The demo account this context is signed in as. */
  async signedInAccount(): Promise<DemoAccount> {
    const me = (await (await this.page.request.get("/api/auth/me")).json()) as { business_name: string; principal: { role: Role } };
    const account = (await demoAccounts(this.page.request)).find(
      (candidate) => candidate.role === me.principal.role && candidate.business_name === me.business_name,
    );
    if (!account) throw new Error(`no demo ${me.principal.role} for ${me.business_name}`);
    return account;
  }

  stepUpDialog(): Locator {
    return this.page.getByRole("dialog", { name: this.t("stepUp.title") });
  }

  /**
   * Approve the open "Confirm it's you" dialog. A live route gets a fresh code for `account`
   * (support/totp.ts) and a refused code is retried with the next step's; a route the offline
   * mock answers gets the mock's code.
   */
  async confirmStepUp(account: DemoAccount, call: StepUpCall = APPROVE_CALL): Promise<void> {
    const dialog = this.stepUpDialog();
    await expect(dialog).toBeVisible();
    const field = dialog.getByLabel(this.t("auth.code"));
    const confirm = dialog.getByRole("button", { name: this.t("stepUp.confirm") });
    if (!(await routeIsLive(call.route))) {
      await field.fill(MOCK_TOTP_CODE);
      await confirm.click();
      await expect(dialog).toBeHidden();
      return;
    }
    await withFreshCode(this.page.request, account, async (code) => {
      await field.fill(code);
      const answer = this.page.waitForResponse((response) => call.url.test(response.url()) && response.request().method() === "POST");
      await confirm.click();
      const response = await answer;
      if (response.ok()) return true;
      const body = (await response.json().catch(() => ({}))) as { code?: string };
      if (response.status() === 401 && body.code === "invalid_step_up") {
        await expect(dialog.getByRole("alert")).toHaveText(this.t("error.invalid_step_up"));
        return false;
      }
      throw new Error(`step-up refused: HTTP ${response.status()} ${body.code ?? ""}`);
    });
    await expect(dialog).toBeHidden();
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
