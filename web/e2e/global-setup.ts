// Local target only, once before the journeys (Playwright has started `npm run dev` by now):
// 1. load the synthetic universe into the dev database (`app.facts.seed`, idempotent: a second run
//    stores nothing new). Without it the real engines abstain for want of history (WP-04 needs
//    8 weeks of transactions). Hosted demos seed at deploy.
// 2. ask for the demo accounts once, so the API creates them (WP-11 does it on first use) before
//    the setup project's parallel sign-ins: on a fresh database two first requests at once can
//    collide while creating them.
import { execFileSync } from "node:child_process";
import { join } from "node:path";

import { BASE_URL, TARGET, WEB_DIR } from "./support/target";

export default async function globalSetup(): Promise<void> {
  if (TARGET !== "local") return;
  execFileSync("uv", ["--directory", join(WEB_DIR, "..", "backend"), "run", "python", "-m", "app.facts.seed"], {
    stdio: "inherit",
    timeout: 300_000,
  });
  const accounts = await fetch(`${BASE_URL}/api/auth/demo-accounts`);
  if (!accounts.ok) throw new Error(`demo accounts: HTTP ${accounts.status} from ${BASE_URL} (is DEMO_MODE on?)`);
}
