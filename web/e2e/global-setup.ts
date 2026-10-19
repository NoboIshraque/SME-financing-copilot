// Local target only: load the synthetic universe into the dev database before the journeys run
// (`app.facts.seed`, idempotent: a second run stores nothing new). Without it the real engines
// abstain for want of history (WP-04 needs 8 weeks of transactions). Hosted demos seed at deploy.
import { execFileSync } from "node:child_process";
import { join } from "node:path";

import { TARGET, WEB_DIR } from "./support/target";

export default function globalSetup(): void {
  if (TARGET !== "local") return;
  execFileSync("uv", ["--directory", join(WEB_DIR, "..", "backend"), "run", "python", "-m", "app.facts.seed"], {
    stdio: "inherit",
    timeout: 300_000,
  });
}
