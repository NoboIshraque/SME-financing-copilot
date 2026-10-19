// Fresh TOTP codes for the demo owners, shared safely between Playwright workers.
//
// The real backend (WP-11) accepts each 30-second code once per account, for sign-in and step-up
// alike, and counts every refused code towards a lockout. In demo mode it publishes each owner's
// current code (`totp_hint` in GET /api/auth/demo-accounts). So all workers take codes through one
// lock per account and remember the last code used: a worker that would reuse it waits for the
// next step instead. Routes still answered by the offline mock take the mock's fixed demo code.
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { APIRequestContext } from "@playwright/test";

import { demoAccounts, type DemoAccount } from "./accounts";
import { TARGET, WEB_DIR } from "./target";

const STATE_DIR = join(WEB_DIR, "e2e", ".state");
const STEP_MS = 30_000;
const STALE_LOCK_MS = 3 * 60_000;
const MAX_ATTEMPTS = 3;

/** The offline mock's fixed code, read from its source so the two never drift apart. */
export const MOCK_TOTP_CODE = (() => {
  const source = readFileSync(join(WEB_DIR, "src", "mocks", "db.ts"), "utf8");
  const match = /DEMO_TOTP_CODE = "(\d{6})"/.exec(source);
  if (!match?.[1]) throw new Error("DEMO_TOTP_CODE not found in src/mocks/db.ts");
  return match[1];
})();

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function stateName(email: string): string {
  return `${TARGET}-${email.replace(/[^a-z0-9]+/gi, "_")}`;
}

async function acquire(name: string): Promise<() => void> {
  mkdirSync(STATE_DIR, { recursive: true });
  const lock = join(STATE_DIR, `${name}.lock`);
  for (;;) {
    try {
      mkdirSync(lock); // atomic: exactly one worker creates it
      return () => rmSync(lock, { recursive: true, force: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      try {
        if (Date.now() - statSync(lock).mtimeMs > STALE_LOCK_MS) rmSync(lock, { recursive: true, force: true });
      } catch {
        // released between the two calls
      }
      await sleep(200);
    }
  }
}

function lastUsed(name: string): string | null {
  try {
    return (JSON.parse(readFileSync(join(STATE_DIR, `${name}.json`), "utf8")) as { code: string }).code;
  } catch {
    return null;
  }
}

function remember(name: string, code: string): void {
  writeFileSync(join(STATE_DIR, `${name}.json`), JSON.stringify({ code, at: new Date().toISOString() }));
}

async function currentHint(api: APIRequestContext, email: string): Promise<string> {
  const account = (await demoAccounts(api)).find((candidate) => candidate.email === email);
  if (!account?.totp_hint) throw new Error(`${email} has no published demo code`);
  return account.totp_hint;
}

/** The account's current code once it differs from the last code any worker used. */
async function nextCode(api: APIRequestContext, email: string, used: string | null): Promise<string> {
  for (let poll = 0; poll < 40; poll += 1) {
    const code = await currentHint(api, email);
    if (code !== used) return code;
    // Same step as the last use: wait for the next one (the server clock may differ a little).
    await sleep(poll === 0 ? STEP_MS - (Date.now() % STEP_MS) + 750 : 2_000);
  }
  throw new Error(`no new TOTP step for ${email} after 80 s`);
}

/**
 * Run `submit` with a code the server has not seen yet. `submit` returns true when the code was
 * accepted and false when it was refused as wrong (someone else used that step), which retries
 * with the next step's code. Holds the account's lock until the server has answered.
 */
export async function withFreshCode(
  api: APIRequestContext,
  account: DemoAccount,
  submit: (code: string) => Promise<boolean>,
): Promise<string> {
  const name = stateName(account.email);
  const release = await acquire(name);
  try {
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      const code = await nextCode(api, account.email, lastUsed(name));
      let accepted = false;
      try {
        accepted = await submit(code);
      } finally {
        remember(name, code); // sent once: never offer it again
      }
      if (accepted) return code;
    }
    throw new Error(`${account.email}: ${MAX_ATTEMPTS} fresh TOTP codes refused`);
  } finally {
    release();
  }
}
